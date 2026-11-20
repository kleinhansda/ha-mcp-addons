"""
title: Unraid
author: David
version: 0.3.0
description: Docker-Compose-Stacks auf dem Unraid-Server per SSH: auflisten, lesen, anlegen und ändern (mit Prüfung und Sicherung), starten, stoppen, Logs; dazu lesende Docker-Befehle, lesende Host-Abfragen und docker exec mit Befehlsliste (z. B. occ, Logs, Rechte). Jede Ausgabe wird vor der Übergabe an das Modell von Passwörtern, Tokens und Schlüsseln bereinigt. Schlüssel und Host-Fingerprint nur in den Ventilen.
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
# Lesende Host-Abfragen für unraid_host: Name -> (Befehl, braucht Pfad)
HOST_BEFEHLE = {
    "ls": ("ls -la --time-style=long-iso --", True),
    "du": ("du -sh --", True),
    "du1": ("du -h --max-depth=1 --", True),
    "df": ("df -h", False),
    "free": ("free -h", False),
    "uptime": ("uptime", False),
    "nproc": ("nproc", False),
}
PFAD_RE = re.compile(r"^/[A-Za-z0-9_./ @+=:-]{0,300}$")

# ---------------------------------------------------------------- Schwärzen
# Alles, was an das Modell geht, läuft durch _schwaerzen: Werte unter geheim klingenden Namen,
# Zugangsdaten in URLs, Bearer-Tokens, private Schlüssel, JWTs, bekannte Token-Formate und lange
# zufällig aussehende Zeichenketten werden durch *** ersetzt.
GEHEIM_TEIL = ("pass", "secret", "token", "apikey", "api_key", "api-key", "salt", "credential", "cookie",
               "instanceid", "signature", "private_key", "privatekey", "dsn", "jwt", "otp")
NAME = r"[A-Za-z_][A-Za-z0-9_.-]*"


def _geheim_name(name: str) -> bool:
    n = name.lower()
    return (any(t in n for t in GEHEIM_TEIL) or n in ("key", "auth", "authorization")
            or n.endswith(("_key", "-key", ".key")))


def _schwaerzen(text: str) -> str:
    if not text:
        return text
    t = re.sub(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
               "[privater Schlüssel entfernt]", text, flags=re.S)
    # PHP-Arrays: 'dbpassword' => 'wert',
    t = re.sub(r"""(['"])(""" + NAME + r""")\1(\s*=>\s*)(['"])((?:\\.|(?!\4).)*)\4""",
               lambda m: m.group(0) if not _geheim_name(m.group(2)) else
               f"{m.group(1)}{m.group(2)}{m.group(1)}{m.group(3)}{m.group(4)}{VERDECKT}{m.group(4)}", t)
    # JSON: "password": "wert"
    t = re.sub(r'"(' + NAME + r')"(\s*:\s*)"((?:\\.|[^"\\])*)"',
               lambda m: m.group(0) if not _geheim_name(m.group(1)) else f'"{m.group(1)}"{m.group(2)}"{VERDECKT}"', t)
    # YAML/INI: password: wert  bzw.  password = wert (ganze Zeile)
    t = re.sub(r"^(\s*-?\s*)(" + NAME + r")(\s*:\s+|\s*=\s*)(?!\s*$)(.+)$",
               lambda m: m.group(0) if not _geheim_name(m.group(2)) or m.group(4).strip() in ("|", ">", "{", "[")
               else f"{m.group(1)}{m.group(2)}{m.group(3)}{VERDECKT}", t, flags=re.M)
    # KEY=wert mitten im Text (Umgebung, Kommandozeile, URL-Parameter)
    t = re.sub(r"(?<![A-Za-z0-9_.-])(-{0,2}" + NAME + r")=([^\s\"',;&]+)",
               lambda m: m.group(0) if not _geheim_name(m.group(1).lstrip("-")) else f"{m.group(1)}={VERDECKT}", t)
    # Zugangsdaten in URLs: scheme://benutzer:passwort@host
    t = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@]+:)([^\s@/]+)@", r"\1" + VERDECKT + "@", t)
    t = re.sub(r"(?i)\b(bearer|basic|token)(\s+)[A-Za-z0-9._~+/=-]{8,}", r"\1\2" + VERDECKT, t)
    t = re.sub(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", VERDECKT, t)
    t = re.sub(r"\b(?:ghp_|gho_|ghs_|ghu_|github_pat_|glpat-|sk-|xox[abprs]-|hf_|AKIA)[A-Za-z0-9_-]{10,}", VERDECKT, t)
    # lange Zeichenketten mit Groß-, Kleinbuchstaben und Ziffern (keine reinen Hex-IDs oder Hashes)
    t = re.sub(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{32,}={0,2}(?![A-Za-z0-9+/_-])",
               lambda m: VERDECKT if (re.search(r"[a-z]", m.group(0)) and re.search(r"[A-Z]", m.group(0))
                                       and re.search(r"[0-9]", m.group(0))) else m.group(0), t)
    return t


def _wiederherstellen(neu: str, alt: str, datei: str) -> str:
    """Zeilen mit *** durch die bisherige Zeile ersetzen, deren geschwärzte Fassung gleich ist."""
    karte: dict = {}
    for z in alt.splitlines():
        g = _schwaerzen(z)
        if g != z:
            karte.setdefault(g.strip(), set()).add(z.strip())
    out = []
    for nr, z in enumerate(neu.splitlines(), 1):
        if VERDECKT in z:
            treffer = karte.get(z.strip())
            if not treffer or len(treffer) != 1:
                raise ValueError(f"{datei} Zeile {nr}: {VERDECKT} ohne eindeutige bisherige Zeile. Zeile unverändert lassen "
                                 f"oder den Wert von David eintragen lassen.")
            z = z[: len(z) - len(z.lstrip())] + next(iter(treffer))
        out.append(z)
    return "\n".join(out) + ("\n" if neu.endswith("\n") else "")


# ---------------------------------------------------------------- docker exec
CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
EXEC_LESEND = {"ls", "cat", "head", "tail", "grep", "find", "stat", "readlink", "id", "whoami", "ps", "df", "du",
               "env", "printenv", "date", "wc", "which", "test", "realpath"}
EXEC_SCHREIBEND = {"chown", "chmod", "cp", "mkdir", "touch"}
EXEC_GENAU = {("php", "-v"), ("php", "-m"), ("nginx", "-t")}
FIND_VERBOTEN = {"-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
OCC_LESEND = ("status", "check", "list", "help", "app:list", "config:list", "config:system:get", "config:app:get",
              "integrity:check-core", "integrity:check-app", "setupchecks", "background-job:list", "user:list",
              "user:info", "group:list", "log:tail", "maintenance:repair --dry-run", "db:add-missing-indices --dry-run",
              "richdocuments:activate-config --help", "update:check", "app:update --showonly")
OCC_GESPERRT = ("user:resetpassword", "user:delete", "user:add", "app:remove", "encryption:", "security:",
                "twofactorauth:", "trashbin:cleanup", "versions:cleanup", "files_external:", "db:convert-type",
                "maintenance:data-fingerprint", "config:import", "user:auth-tokens", "ldap:")


class Tools:
    class Valves(BaseModel):
        host: str = Field(default="192.168.10.40", description="Adresse des Unraid-Servers")
        port: int = Field(default=22, description="SSH-Port")
        benutzer: str = Field(default="root", description="SSH-Benutzer (bei Unraid root)")
        privater_schluessel: str = Field(default="", description="Privater SSH-Schlüssel (OpenSSH-Format, nur für dieses Werkzeug); öffentlichen Teil in Unraid unter Benutzer root → SSH-Schlüssel eintragen")
        host_fingerprint: str = Field(default="", description="SHA256-Fingerprint des Unraid-Hostschlüssels (ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub); leer = Verbindung wird abgelehnt und der Fingerprint gemeldet")
        lese_ordner: str = Field(default="/mnt/user,/mnt/cache,/boot/config/plugins/compose.manager", description="Kommagetrennt: nur darunter darf unraid_host ls/du ausführen (Inhalte werden nie gelesen)")
        stacks_ordner: str = Field(default="/boot/config/plugins/compose.manager/projects", description="Ordner der Stacks (Compose Manager): je Stack ein Unterordner mit docker-compose.yml")
        erlaubte_aktionen: str = Field(default="ps,logs,config,pull,up,restart,start,stop,down", description="Kommagetrennt, was unraid_stack_aktion darf")
        schreiben_erlaubt: bool = Field(default=True, description="Stacks anlegen und ändern")
        max_zeichen: int = Field(default=12000, description="Ausgabe an das Modell kürzen")
        timeout: int = Field(default=300, description="Sekunden je Befehl (pull und up können dauern)")
        exec_container: str = Field(default="*", description="Kommagetrennt: Container, in denen unraid_exec Befehle ausführen darf; * = alle")
        exec_schreiben: bool = Field(default=True, description="unraid_exec: chown, chmod, cp, mkdir, touch und ändernde occ-Befehle zulassen")
        exec_schreibpfade: str = Field(default="/config,/data,/var/www,/app/www", description="Kommagetrennt: nur darunter darf unraid_exec schreiben (Pfade im Container)")

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
                agent_path=None, password=None, kbdint_auth=False, server_host_key_algs=["ssh-ed25519"]), timeout=20)
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
        text = _schwaerzen(text.strip())
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
            if VERDECKT in compose:
                # geschwärzte Werte aus unraid_stack_lesen: bisherige Werte wieder einsetzen
                if not vorhanden:
                    return f"Fehler: compose enthält {VERDECKT}, aber es gibt keine bisherige Datei mit echten Werten."
                _, alt_compose = await self._sh(conn, f"cat {q(ordner + '/docker-compose.yml')}")
                try:
                    compose = _wiederherstellen(compose, alt_compose, "docker-compose.yml")
                except ValueError as e:
                    return f"Fehler: {e} Nichts geändert."
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

    async def unraid_host(self, befehle: list[str], __event_emitter__=None) -> str:
        """
        Lesende Host-Abfragen auf Unraid, mehrere in einer Verbindung, z. B. ["ls /mnt/user/appdata/nc", "du /mnt/user/appdata/nc", "free", "uptime"].
        Erlaubt: ls <pfad> (Ordnerinhalt mit Größen), du <pfad> (Gesamtgröße), du1 <pfad> (Größe je Unterordner), df, free, uptime, nproc.
        Pfade absolut unter den freigegebenen Ordnern (Ventil lese_ordner). Dateiinhalte werden nicht gelesen.
        :param befehle: Liste der Abfragen (als Liste, nicht als Text), höchstens 10
        :return: je Abfrage Exit-Code und Ausgabe
        """
        if isinstance(befehle, str):
            befehle = [b for b in befehle.splitlines() if b.strip()]
        if not isinstance(befehle, list) or not befehle or len(befehle) > 10:
            return "Fehler: befehle muss eine Liste mit 1 bis 10 Abfragen sein."
        erlaubt = [o.strip().rstrip("/") for o in self.valves.lese_ordner.split(",") if o.strip()]
        plan = []
        for b in befehle:
            b = " ".join(str(b).split())
            name, _, pfad = b.partition(" ")
            if name not in HOST_BEFEHLE:
                return f"Fehler bei „{b}“: erlaubt sind {', '.join(HOST_BEFEHLE)}. Nichts ausgeführt."
            cmd, braucht_pfad = HOST_BEFEHLE[name]
            if braucht_pfad:
                if not PFAD_RE.match(pfad) or ".." in pfad:
                    return f"Fehler bei „{b}“: absoluter Pfad ohne '..' und ohne Sonderzeichen nötig. Nichts ausgeführt."
            elif pfad:
                return f"Fehler bei „{b}“: {name} ohne Pfad. Nichts ausgeführt."
            plan.append((b, cmd, pfad.rstrip("/") or "/" if braucht_pfad else ""))
        try:
            conn = await self._verbinden()
        except Exception as e:
            return f"Fehler: {e}"
        q = shlex.quote
        je = max(800, self.valves.max_zeichen // len(plan))
        teile = []
        async with conn:
            for i, (b, cmd, pfad) in enumerate(plan, 1):
                if __event_emitter__:
                    await __event_emitter__({"type": "status", "data": {"description": f"Unraid {i}/{len(plan)}: {b}", "done": False}})
                if pfad:
                    # Symlinks auflösen, dann gegen die freigegebenen Ordner prüfen
                    rc, echt = await self._sh(conn, f"realpath -e -- {q(pfad)}")
                    echt = echt.strip()
                    if rc or not any(echt == o or echt.startswith(o + "/") for o in erlaubt):
                        teile.append(f"## {b}\nFehler: Pfad nicht vorhanden oder nicht freigegeben (Ventil lese_ordner: {', '.join(erlaubt)}).")
                        continue
                    befehl = f"{cmd} {q(echt)} 2>&1"
                else:
                    befehl = cmd + " 2>&1"
                try:
                    rc, aus = await self._sh(conn, befehl)
                except asyncio.TimeoutError:
                    teile.append(f"## {b}\nFehler: länger als {self.valves.timeout} s (Ventil timeout).")
                    continue
                aus = _schwaerzen(aus.strip())
                if len(aus) > je:
                    aus = aus[: je * 3 // 4] + f"\n[…{len(aus)} Zeichen, gekürzt…]\n" + aus[-(je // 4):]
                teile.append(f"## {b}\nexit {rc}\n{aus or '(keine Ausgabe)'}")
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Unraid: fertig", "done": True}})
        return "\n\n".join(teile)

    def _exec_pruefen(self, befehl: str) -> tuple:
        """Gibt (argumente, schreibend, fehler) zurück."""
        if re.search(r"[;&|`$<>\n\\]", befehl or ""):
            return None, False, "keine Shell-Zeichen (; & | ` $ < > Zeilenumbruch)"
        try:
            a = shlex.split(befehl or "")
        except ValueError as e:
            return None, False, str(e)
        if not a:
            return None, False, "leerer Befehl"
        if any(".." in x for x in a):
            return None, False, "'..' ist nicht erlaubt"
        cmd = a[0]
        if cmd == "occ":
            rest = " ".join(a[1:])
            unter = a[1] if len(a) > 1 else "list"
            if any(unter.startswith(g) for g in OCC_GESPERRT):
                return None, False, f"occ {unter} ist gesperrt (Benutzer, Verschlüsselung, Sicherheit, Löschen)"
            lesend = unter in ("status", "check", "list", "help") or any(rest == o or rest.startswith(o + " ") or unter == o for o in OCC_LESEND)
            return a, not lesend, None
        if tuple(a) in EXEC_GENAU:
            return a, False, None
        if cmd in EXEC_LESEND:
            if cmd == "find" and any(x in FIND_VERBOTEN for x in a):
                return None, False, f"find ohne {', '.join(sorted(FIND_VERBOTEN))}"
            if cmd == "tail" and any(x in ("-f", "-F", "--follow") for x in a):
                return None, False, "tail ohne -f"
            return a, False, None
        if cmd in EXEC_SCHREIBEND:
            pfade = [x for x in a[1:] if x.startswith("/")]
            erlaubt = [p.strip().rstrip("/") for p in self.valves.exec_schreibpfade.split(",") if p.strip()]
            if not pfade:
                return None, True, f"{cmd} braucht absolute Pfade"
            for x in pfade:
                if not any(x == p or x.startswith(p + "/") for p in erlaubt):
                    return None, True, f"Pfad {x} nicht freigegeben (Ventil exec_schreibpfade: {', '.join(erlaubt)})"
            if cmd == "cp":
                a = ["cp", "-n"] + [x for x in a[1:] if x != "-n"]   # nie überschreiben
            return a, True, None
        return None, False, (f"Befehl {cmd} nicht erlaubt. Lesend: occ (lesende Unterbefehle), {', '.join(sorted(EXEC_LESEND))}, "
                             f"php -v/-m, nginx -t; schreibend: {', '.join(sorted(EXEC_SCHREIBEND))} und ändernde occ-Befehle. "
                             f"Nicht möglich: rm, mv, sh, Skripte, Netzwerk.")

    async def unraid_exec(self, container: str, befehle: list[str], benutzer: str = "", __event_emitter__=None) -> str:
        """
        Führt Befehle in einem laufenden Container auf Unraid aus (docker exec), mehrere in einer Verbindung, z. B. container="nc", befehle=["occ status", "ls -ln /config/www/nextcloud/config", "tail -n 100 /data/nextcloud.log"].
        Erlaubt: occ (Nextcloud; lesend immer, ändernd per Ventil; Benutzer-, Verschlüsselungs- und Löschbefehle gesperrt), ls, cat, head, tail, grep, find, stat, readlink, realpath, id, whoami, ps, df, du, env, printenv, date, wc, which, test, php -v/-m, nginx -t; ändernd: chown, chmod, cp (überschreibt nie), mkdir, touch unter freigegebenen Pfaden.
        Keine Shell, kein rm/mv. Passwörter, Tokens und Schlüssel in der Ausgabe werden durch *** ersetzt; Dateien mit Zugangsdaten (z. B. config.php) dürfen daher gelesen werden.
        :param container: Containername, z. B. nc
        :param befehle: Liste der Befehle (als Liste, nicht als Text), höchstens 10
        :param benutzer: optional Benutzer im Container (-u), z. B. abc oder 99:100
        :return: je Befehl Exit-Code und bereinigte Ausgabe
        """
        if isinstance(befehle, str):
            befehle = [b for b in befehle.splitlines() if b.strip()]
        if not isinstance(befehle, list) or not befehle or len(befehle) > 10:
            return "Fehler: befehle muss eine Liste mit 1 bis 10 Befehlen sein."
        if not CONTAINER_RE.match(container or ""):
            return "Fehler: ungültiger Containername."
        erlaubt_c = [c.strip() for c in self.valves.exec_container.split(",") if c.strip()]
        if "*" not in erlaubt_c and container not in erlaubt_c:
            return f"Fehler: Container {container} nicht freigegeben (Ventil exec_container: {', '.join(erlaubt_c)})."
        if benutzer and not re.fullmatch(r"[A-Za-z0-9_-]{1,32}(:[A-Za-z0-9_-]{1,32})?", benutzer):
            return "Fehler: ungültiger Benutzer."
        plan = []
        for b in befehle:
            a, schreibend, f = self._exec_pruefen(str(b))
            if f:
                return f"Fehler bei „{b}“: {f.rstrip('.')}. Nichts ausgeführt."
            if schreibend and not self.valves.exec_schreiben:
                return f"Fehler bei „{b}“: ändernde Befehle sind abgeschaltet (Ventil exec_schreiben). Nichts ausgeführt."
            plan.append((str(b), a))
        try:
            conn = await self._verbinden()
        except Exception as e:
            return f"Fehler: {e}"
        q = shlex.quote
        u = f"-u {q(benutzer)} " if benutzer else ""
        je = max(800, self.valves.max_zeichen // len(plan))
        teile = []
        async with conn:
            rc, _ = await self._sh(conn, f"docker inspect -f '{{{{.State.Running}}}}' {q(container)} 2>/dev/null | grep -qx true")
            if rc:
                return f"Fehler: Container {container} läuft nicht oder existiert nicht."
            for i, (b, a) in enumerate(plan, 1):
                if __event_emitter__:
                    await __event_emitter__({"type": "status", "data": {"description": f"Unraid exec {i}/{len(plan)}: {b}", "done": False}})
                if a[0] == "occ":
                    args = " ".join(q(x) for x in a[1:]) + " --no-interaction"
                    befehl = (f"if docker exec {q(container)} sh -c 'command -v occ' >/dev/null 2>&1; "
                              f"then docker exec {u}{q(container)} occ {args}; "
                              f"else docker exec {u or '-u www-data '}{q(container)} php occ {args}; fi 2>&1")
                else:
                    befehl = f"docker exec {u}{q(container)} " + " ".join(q(x) for x in a) + " 2>&1"
                try:
                    rc, aus = await self._sh(conn, befehl)
                except asyncio.TimeoutError:
                    teile.append(f"## {b}\nFehler: länger als {self.valves.timeout} s (Ventil timeout).")
                    continue
                aus = _schwaerzen(aus.strip())
                if len(aus) > je:
                    aus = aus[: je * 3 // 4] + f"\n[…{len(aus)} Zeichen, gekürzt…]\n" + aus[-(je // 4):]
                teile.append(f"## {b}\nexit {rc}\n{aus or '(keine Ausgabe)'}")
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Unraid exec: fertig", "done": True}})
        return "\n\n".join(teile)
