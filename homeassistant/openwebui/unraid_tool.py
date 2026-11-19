"""
title: Unraid
author: David
version: 0.1.0
description: Docker-Compose-Stacks auf dem Unraid-Server per SSH: auflisten, lesen, anlegen und ändern (mit Prüfung und Sicherung), starten, stoppen, Logs; dazu lesende Docker-Befehle. Schlüssel und Host-Fingerprint nur in den Ventilen.
requirements: asyncssh
"""

import asyncio
import re
import shlex
import time
from typing import Optional

from pydantic import BaseModel, Field

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ENV_RE = re.compile(r"^\s*(export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
VERDECKT = "***"
# Lesende Docker-Befehle für unraid_docker (erstes Wort nach "docker")
DOCKER_LESEND = {"ps", "logs", "inspect", "images", "stats", "top", "port", "version", "info", "network", "volume", "system", "compose"}
DOCKER_UNTER = {"network": {"ls", "inspect"}, "volume": {"ls", "inspect"}, "system": {"df"}, "compose": {"ls", "ps"}}


class Tools:
    class Valves(BaseModel):
        host: str = Field(default="192.168.10.40", description="Adresse des Unraid-Servers")
        port: int = Field(default=22, description="SSH-Port")
        benutzer: str = Field(default="root", description="SSH-Benutzer (bei Unraid root)")
        privater_schluessel: str = Field(default="", description="Privater SSH-Schlüssel (OpenSSH-Format, nur für dieses Werkzeug); öffentlichen Teil in Unraid unter Benutzer root → SSH-Schlüssel eintragen")
        host_fingerprint: str = Field(default="", description="SHA256-Fingerprint des Unraid-Hostschlüssels (ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub); leer = Verbindung wird abgelehnt und der Fingerprint gemeldet")
        stacks_ordner: str = Field(default="/boot/config/plugins/compose.manager/projects", description="Ordner der Stacks (Compose Manager): je Stack ein Unterordner mit docker-compose.yml")
        erlaubte_aktionen: str = Field(default="ps,logs,config,pull,up,restart,start,stop,down", description="Kommagetrennt, was unraid_stack_aktion darf")
        schreiben_erlaubt: bool = Field(default=True, description="Stacks anlegen und ändern")
        max_zeichen: int = Field(default=12000, description="Ausgabe an das Modell kürzen")
        timeout: int = Field(default=300, description="Sekunden je Befehl (pull und up können dauern)")

    def __init__(self):
        self.valves = self.Valves()

    # ---------------------------------------------------------------- Verbindung

    async def _verbinden(self):
        import asyncssh
        v = self.valves
        if not v.privater_schluessel.strip():
            raise ValueError("Kein privater Schlüssel im Ventil privater_schluessel. David muss ihn eintragen.")
        schluessel = asyncssh.import_private_key(v.privater_schluessel.strip())
        try:
            conn = await asyncio.wait_for(asyncssh.connect(
                v.host, port=v.port, username=v.benutzer, client_keys=[schluessel], known_hosts=None,
                agent_path=None, password=None, kbdint_auth=False), timeout=20)
        except (OSError, asyncio.TimeoutError) as e:
            raise ValueError(f"Unraid unter {v.host}:{v.port} nicht erreichbar ({type(e).__name__}). "
                             "Schläft der Server oder ist er aus?")
        fp = conn.get_server_host_key().get_fingerprint("sha256")
        soll = v.host_fingerprint.strip()
        if not soll or soll != fp:
            conn.close()
            if not soll:
                raise ValueError(f"Host-Fingerprint nicht eingetragen. Der Server meldet {fp}. David vergleicht ihn auf "
                                 "Unraid (ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub) und trägt ihn ins Ventil host_fingerprint ein.")
            raise ValueError(f"Host-Fingerprint stimmt nicht: erwartet {soll}, Server meldet {fp}. Verbindung abgebrochen.")
        return conn

    async def _sh(self, conn, befehl: str, eingabe: Optional[str] = None) -> tuple[int, str]:
        r = await asyncio.wait_for(conn.run(befehl, input=eingabe, check=False), timeout=self.valves.timeout)
        text = ANSI_RE.sub("", (r.stdout or "") + (r.stderr or ""))
        return r.exit_status if r.exit_status is not None else 1, text

    def _kurz(self, text: str) -> str:
        n = self.valves.max_zeichen
        text = text.strip()
        return text if len(text) <= n else text[: n * 3 // 4] + f" […{len(text)} Zeichen, gekürzt…] " + text[-(n // 4):]

    def _ordner(self, name: str) -> str:
        if not NAME_RE.match(name or ""):
            raise ValueError("Stack-Name: klein, a–z, 0–9, - und _, höchstens 64 Zeichen, z. B. formbricks.")
        return self.valves.stacks_ordner.rstrip("/") + "/" + name

    def _compose(self, name: str, ordner: str, datei: str = "docker-compose.yml") -> str:
        q = shlex.quote
        return (f"cd {q(ordner)} && docker compose -p {q(name)} -f {q(datei)} "
                f"$( [ -f .env ] && echo --env-file .env ) ")

    @staticmethod
    def _env_verdecken(text: str) -> str:
        out = []
        for z in text.splitlines():
            m = ENV_RE.match(z)
            out.append(f"{m.group(1) or ''}{m.group(2)}={VERDECKT}" if m and m.group(3).strip() else z)
        return "\n".join(out)

    @staticmethod
    def _env_zusammen(neu: str, alt: str) -> str:
        """Werte *** im neuen Text durch die bisherigen ersetzen (Geheimnisse bleiben, ohne dass das Modell sie sieht)."""
        alte = {m.group(2): m.group(3) for z in alt.splitlines() if (m := ENV_RE.match(z))}
        out = []
        for z in neu.splitlines():
            m = ENV_RE.match(z)
            if m and m.group(3).strip() == VERDECKT:
                if m.group(2) not in alte:
                    raise ValueError(f".env: {m.group(2)}={VERDECKT}, aber es gibt keinen bisherigen Wert dafür.")
                z = f"{m.group(1) or ''}{m.group(2)}={alte[m.group(2)]}"
            out.append(z)
        return "\n".join(out) + "\n"

    # ---------------------------------------------------------------- Werkzeuge

    async def unraid_stacks(self, __event_emitter__=None) -> str:
        """
        Listet die Docker-Compose-Stacks auf dem Unraid-Server mit Status (laufend, gestoppt, nie gestartet).
        :return: je Stack eine Zeile
        """
        q = shlex.quote
        o = self.valves.stacks_ordner.rstrip("/")
        try:
            conn = await self._verbinden()
        except Exception as e:
            return f"Fehler: {e}"
        async with conn:
            _, liste = await self._sh(conn, f"cd {q(o)} 2>/dev/null && for d in */; do [ -f \"$d/docker-compose.yml\" ] && echo \"${{d%/}}\"; done")
            _, laufend = await self._sh(conn, "docker compose ls --all --format '{{.Name}}\t{{.Status}}' 2>/dev/null || docker compose ls --all")
        status = {}
        for z in laufend.splitlines():
            teile = z.split("\t") if "\t" in z else z.split(None, 1)
            if len(teile) == 2:
                status[teile[0].strip()] = teile[1].strip()
        namen = [n for n in liste.split() if n]
        if not namen and not status:
            return f"Keine Stacks in {o} und keine Compose-Projekte gefunden."
        zeilen = [f"- {n}: {status.get(n, 'nie gestartet')}" for n in namen]
        fremd = [f"- {n}: {s} (nicht in {o})" for n, s in status.items() if n not in namen]
        return "\n".join(zeilen + fremd)

    async def unraid_stack_lesen(self, name: str, __event_emitter__=None) -> str:
        """
        Zeigt docker-compose.yml und .env eines Stacks. Werte in .env erscheinen als ***.
        :param name: Stack-Name, z. B. formbricks
        :return: Inhalt der Dateien
        """
        try:
            ordner = self._ordner(name)
            conn = await self._verbinden()
        except Exception as e:
            return f"Fehler: {e}"
        q = shlex.quote
        async with conn:
            rc, compose = await self._sh(conn, f"cat {q(ordner + '/docker-compose.yml')}")
            if rc:
                return f"Fehler: Stack {name} hat keine docker-compose.yml in {ordner}."
            rc_env, env = await self._sh(conn, f"cat {q(ordner + '/.env')} 2>/dev/null")
        teile = [f"# {ordner}/docker-compose.yml", compose.rstrip()]
        if not rc_env and env.strip():
            teile += ["", f"# {ordner}/.env (Werte verdeckt; beim Schreiben {VERDECKT} lassen, um sie zu behalten)",
                      self._env_verdecken(env)]
        return self._kurz("\n".join(teile))

    async def unraid_stack_schreiben(self, name: str, compose: str, env: Optional[str] = None, neu: bool = False,
                                     __event_emitter__=None) -> str:
        """
        Legt einen Stack an (neu=true) oder ersetzt dessen docker-compose.yml und optional .env. Prüft vorher mit
        docker compose config; die bisherigen Dateien kommen nach backup/ im Stack-Ordner. Startet nichts.
        In env Werte mit *** lassen, um bisherige Geheimnisse zu behalten.
        :param name: Stack-Name, z. B. formbricks
        :param compose: vollständiger Inhalt der docker-compose.yml
        :param env: optional vollständiger Inhalt der .env (KEY=Wert je Zeile)
        :param neu: true für einen neuen Stack; ein bestehender wird dann nicht überschrieben
        :return: Ergebnis der Prüfung und abgelegte Dateien
        """
        if not self.valves.schreiben_erlaubt:
            return "Fehler: Schreiben ist abgeschaltet (Ventil schreiben_erlaubt)."
        try:
            ordner = self._ordner(name)
            conn = await self._verbinden()
        except Exception as e:
            return f"Fehler: {e}"
        q = shlex.quote
        stempel = time.strftime("%Y%m%d-%H%M%S")
        async with conn:
            rc, _ = await self._sh(conn, f"test -f {q(ordner + '/docker-compose.yml')}")
            vorhanden = rc == 0
            if neu and vorhanden:
                return f"Fehler: Stack {name} gibt es schon. Zum Ändern neu=false."
            if not neu and not vorhanden:
                return f"Fehler: Stack {name} gibt es nicht. Zum Anlegen neu=true."
            await self._sh(conn, f"mkdir -p {q(ordner)}")
            if env is not None:
                _, alt_env = await self._sh(conn, f"cat {q(ordner + '/.env')} 2>/dev/null")
                try:
                    env = self._env_zusammen(env, alt_env if vorhanden else "")
                except ValueError as e:
                    return f"Fehler: {e}"
            # Entwurf neben die echten Dateien, prüfen, erst dann ersetzen
            await self._sh(conn, f"cat > {q(ordner + '/.entwurf.yml')}", compose)
            if env is not None:
                await self._sh(conn, f"cat > {q(ordner + '/.entwurf.env')}", env)
            env_arg = "--env-file .entwurf.env" if env is not None else "$( [ -f .env ] && echo --env-file .env )"
            rc, pruef = await self._sh(conn, f"cd {q(ordner)} && docker compose -p {q(name)} -f .entwurf.yml {env_arg} config -q")
            if rc:
                await self._sh(conn, f"rm -f {q(ordner + '/.entwurf.yml')} {q(ordner + '/.entwurf.env')}")
                if not vorhanden:
                    await self._sh(conn, f"rmdir {q(ordner)} 2>/dev/null")
                return "Fehler: docker compose config lehnt die Datei ab, nichts geändert:\n" + self._kurz(pruef)
            schritte = []
            if vorhanden:
                await self._sh(conn, f"mkdir -p {q(ordner + '/backup')} && cp -p {q(ordner + '/docker-compose.yml')} "
                                     f"{q(ordner + '/backup/docker-compose.' + stempel + '.yml')}")
                schritte.append(f"Sicherung backup/docker-compose.{stempel}.yml")
                if env is not None:
                    await self._sh(conn, f"[ -f {q(ordner + '/.env')} ] && cp -p {q(ordner + '/.env')} {q(ordner + '/backup/env.' + stempel)}")
            rc, aus = await self._sh(conn, f"mv {q(ordner + '/.entwurf.yml')} {q(ordner + '/docker-compose.yml')}"
                                           + (f" && mv {q(ordner + '/.entwurf.env')} {q(ordner + '/.env')} && chmod 600 {q(ordner + '/.env')}"
                                              if env is not None else ""))
            if rc:
                return "Fehler beim Ersetzen: " + self._kurz(aus)
            if not vorhanden:
                await self._sh(conn, f"[ -f {q(ordner + '/name')} ] || printf %s {q(name)} > {q(ordner + '/name')}")
        return (f"{'Angelegt' if not vorhanden else 'Geändert'}: {ordner}/docker-compose.yml"
                + (" und .env" if env is not None else "") + "; docker compose config ohne Fehler"
                + (f"; {', '.join(schritte)}" if schritte else "") + ". Gestartet wird erst mit unraid_stack_aktion(up).")

    async def unraid_stack_aktion(self, name: str, aktion: str, dienst: str = "", __event_emitter__=None) -> str:
        """
        Führt docker compose für einen Stack aus: ps, logs (letzte 200 Zeilen), config, pull, up (im Hintergrund),
        restart, start, stop, down (entfernt Container, keine Volumes). Optional nur für einen Dienst.
        :param name: Stack-Name, z. B. formbricks
        :param aktion: ps, logs, config, pull, up, restart, start, stop oder down
        :param dienst: optional ein Dienst aus der docker-compose.yml
        :return: Ausgabe von docker compose
        """
        aktion = (aktion or "").strip().lower()
        erlaubt = {a.strip() for a in self.valves.erlaubte_aktionen.split(",") if a.strip()}
        if aktion not in erlaubt:
            return f"Fehler: Aktion {aktion or '(leer)'} nicht erlaubt. Erlaubt: {', '.join(sorted(erlaubt))}."
        if dienst and not NAME_RE.match(dienst.lower()):
            return "Fehler: ungültiger Dienstname."
        try:
            ordner = self._ordner(name)
            conn = await self._verbinden()
        except Exception as e:
            return f"Fehler: {e}"
        zusatz = {"up": "up -d --remove-orphans", "logs": "logs --no-color --tail 200", "config": "config",
                  "ps": "ps -a", "down": "down --remove-orphans"}.get(aktion, aktion)
        befehl = self._compose(name, ordner) + zusatz + (" " + shlex.quote(dienst) if dienst else "") + " 2>&1"
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"Unraid: {name} {aktion}", "done": False}})
        try:
            async with conn:
                rc, _ = await self._sh(conn, f"test -f {shlex.quote(ordner + '/docker-compose.yml')}")
                if rc:
                    return f"Fehler: Stack {name} hat keine docker-compose.yml in {ordner}."
                rc, aus = await self._sh(conn, befehl)
        except asyncio.TimeoutError:
            return f"Fehler: {aktion} dauerte länger als {self.valves.timeout} s (Ventil timeout). Mit ps nachsehen."
        finally:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"Unraid: {name} {aktion}", "done": True}})
        if aktion == "config":
            aus = re.sub(r"^(\s*[A-Za-z0-9_]*(?:PASS|KEY|SECRET|TOKEN)[A-Za-z0-9_]*\s*:\s*).+$", r"\1" + VERDECKT, aus, flags=re.M | re.I)
        return f"exit {rc}\n" + self._kurz(aus or "(keine Ausgabe)")

    async def unraid_docker(self, befehl: str, __event_emitter__=None) -> str:
        """
        Lesender Docker-Befehl auf Unraid zur Fehlersuche, ohne das Wort docker: z. B. "ps -a",
        "logs --tail 100 formbricks", "inspect formbricks", "stats --no-stream", "system df", "compose ls".
        :param befehl: Befehl nach "docker", nur ps, logs, inspect, images, stats, top, port, version, info, network ls/inspect, volume ls/inspect, system df, compose ls/ps
        :return: Ausgabe des Befehls
        """
        if re.search(r"[;&|`$<>\n\\]", befehl or ""):
            return "Fehler: keine Shell-Zeichen (; & | ` $ < > Zeilenumbruch)."
        try:
            teile = shlex.split(befehl or "")
        except ValueError as e:
            return f"Fehler: {e}"
        if teile and teile[0] == "docker":
            teile = teile[1:]
        if not teile or teile[0] not in DOCKER_LESEND:
            return "Fehler: nur lesende Befehle: " + ", ".join(sorted(DOCKER_LESEND))
        if teile[0] in DOCKER_UNTER and (len(teile) < 2 or teile[1] not in DOCKER_UNTER[teile[0]]):
            return f"Fehler: docker {teile[0]} nur mit {', '.join(sorted(DOCKER_UNTER[teile[0]]))}."
        if teile[0] == "stats" and "--no-stream" not in teile:
            teile.append("--no-stream")
        if teile[0] == "logs" and not any(t.startswith("--tail") or t == "-n" for t in teile):
            teile[1:1] = ["--tail", "200"]
        if teile[0] == "logs" and any(t in ("-f", "--follow") for t in teile):
            return "Fehler: logs ohne -f/--follow."
        try:
            conn = await self._verbinden()
        except Exception as e:
            return f"Fehler: {e}"
        async with conn:
            rc, aus = await self._sh(conn, "docker " + " ".join(shlex.quote(t) for t in teile) + " 2>&1")
        if teile[0] == "inspect":
            aus = re.sub(r'("(?:[A-Z0-9_]*(?:PASS|KEY|SECRET|TOKEN)[A-Z0-9_]*)=)[^"]*"', r'\1' + VERDECKT + '"', aus, flags=re.I)
        return f"exit {rc}\n" + self._kurz(aus or "(keine Ausgabe)")
