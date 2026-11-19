"""
title: HA-SSH
author: David
version: 1.0.0
description: Eingeschränkter SSH-Zugang zu Home Assistant über das Advanced-SSH-Add-on: Logs (Core, Supervisor, Host, Apps), Konfigurationsprüfung, Infos, Dateien unter /config, /share und /media lesen (ohne Geheimnisse), Speicherplatz; Neustarts nur per Ventil. Ein Prüfskript auf dem HA-Host erzwingt die Befehlsliste.
requirements: asyncssh
"""

# Sicherheit in drei Schichten:
# 1. Eigener Schlüssel, vom Werkzeug erzeugt (privater Teil verlässt Open WebUI nie, kein Passwort).
# 2. Auf dem HA-Host erzwingt authorized_keys mit restrict,command="… owui_ssh_gate.sh" die Befehlsliste;
#    selbst ein kompromittiertes Modell bekommt keine Shell.
# 3. Hier: dieselbe Zeichenprüfung, Neustarts nur mit Ventil, Hostschlüssel fest eingetragen.

import asyncio
import os
import re
from typing import Optional

from pydantic import BaseModel, Field

BEFEHL_RE = re.compile(r"^[A-Za-z0-9_./:@+= -]{1,400}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SCHREIBEND = {"neustart", "app_start", "app_stop"}
GATE = 'restrict,command="bash /config/pyscript/shell/owui_ssh_gate.sh"'


class Tools:
    class Valves(BaseModel):
        host: str = Field(default="172.30.32.1", description="Adresse des HA-Hosts aus Sicht von Open WebUI (Advanced SSH läuft im Host-Netz)")
        port: int = Field(default=22, description="SSH-Port des Advanced-SSH-Add-ons")
        benutzer: str = Field(default="root", description="Benutzername wie im Add-on eingestellt")
        host_fingerprint: str = Field(default="", description="SHA256-Fingerprint des Hostschlüssels; leer = keine Verbindung, ha_ssh_einrichten meldet ihn")
        neustart_erlaubt: bool = Field(default=False, description="Aktionen neustart, app_start, app_stop zulassen")
        max_zeichen: int = Field(default=12000, description="Ausgabe an das Modell kürzen")
        timeout: int = Field(default=120, description="Sekunden je Befehl")

    def __init__(self):
        # Pflicht: ohne dieses Attribut setzt Open WebUI die eingetragenen Ventile nicht.
        self.valves = self.Valves()

    @staticmethod
    def _schluesseldatei() -> str:
        ordner = os.path.join(os.environ.get("DATA_DIR", "/app/backend/data"), "ha_ssh")
        return os.path.join(ordner, "id_ed25519")

    def _pruefen(self, befehl: str) -> Optional[str]:
        b = " ".join((befehl or "").split())
        if not BEFEHL_RE.match(b) or ".." in b:
            return "Befehl ungültig: nur Buchstaben, Ziffern, _ . / : @ + = - und Leerzeichen, ohne '..'. Beispiel: logs core 100"
        if b.split()[0] in SCHREIBEND and not self.valves.neustart_erlaubt:
            return "Neustarts sind abgeschaltet (Ventil neustart_erlaubt). Den Nutzer fragen."
        return None

    async def _verbinden(self):
        import asyncssh
        v = self.valves
        datei = self._schluesseldatei()
        if not os.path.isfile(datei):
            raise ValueError("Noch kein Schlüssel. Erst ha_ssh_einrichten aufrufen.")
        soll = v.host_fingerprint.strip()
        if not soll:
            raise ValueError("Host-Fingerprint fehlt im Ventil host_fingerprint. ha_ssh_einrichten meldet ihn.")
        try:
            conn = await asyncio.wait_for(asyncssh.connect(
                v.host, port=v.port, username=v.benutzer, client_keys=[datei], known_hosts=None,
                agent_path=None, password=None, kbdint_auth=False), timeout=20)
        except asyncssh.PermissionDenied:
            raise ValueError("Schlüssel abgelehnt. Ist die Zeile aus ha_ssh_einrichten im Advanced-SSH-Add-on unter authorized_keys eingetragen und das Add-on neu gestartet?")
        except (OSError, asyncio.TimeoutError, asyncssh.Error) as e:
            raise ValueError(f"SSH unter {v.host}:{v.port} nicht erreichbar ({type(e).__name__}).")
        fp = conn.get_server_host_key().get_fingerprint("sha256")
        if fp != soll:
            conn.close()
            raise ValueError(f"Host-Fingerprint stimmt nicht: erwartet {soll}, Server meldet {fp}. Verbindung abgebrochen.")
        return conn

    async def _ausfuehren(self, conn, befehl: str, n: int) -> str:
        r = await asyncio.wait_for(conn.run(" ".join(befehl.split()), check=False), timeout=self.valves.timeout)
        text = ANSI_RE.sub("", (r.stdout or "") + (r.stderr or "")).strip()
        if len(text) > n:
            text = text[: n * 3 // 4] + f"\n[…{len(text)} Zeichen, gekürzt…]\n" + text[-(n // 4):]
        return f"(exit {r.exit_status})\n{text}"

    async def ha_ssh_einrichten(self) -> str:
        """
        Richtet den Zugang ein oder zeigt ihn an: erzeugt einmalig einen eigenen SSH-Schlüssel und gibt die Zeile für authorized_keys im Advanced-SSH-Add-on sowie den Host-Fingerprint aus. Der private Schlüssel bleibt in Open WebUI.
        :return: Anleitung mit authorized_keys-Zeile und Fingerprint
        """
        import asyncssh
        datei = self._schluesseldatei()
        neu = False
        if not os.path.isfile(datei):
            os.makedirs(os.path.dirname(datei), mode=0o700, exist_ok=True)
            k = asyncssh.generate_private_key("ssh-ed25519", comment="owui-ha-ssh")
            k.write_private_key(datei)
            os.chmod(datei, 0o600)
            neu = True
        oeffentlich = asyncssh.read_private_key(datei).export_public_key().decode().strip()
        try:
            hk = await asyncio.wait_for(asyncssh.get_server_host_key(self.valves.host, self.valves.port), timeout=15)
            fp = hk.get_fingerprint("sha256")
        except Exception as e:
            fp = f"(nicht ermittelt: {type(e).__name__})"
        stand = "eingetragen und passend" if self.valves.host_fingerprint.strip() == fp else "noch eintragen"
        return (
            f"Schlüssel {'neu erzeugt' if neu else 'vorhanden'}.\n"
            f"1. Im Advanced-SSH-Add-on unter authorized_keys diese Zeile ergänzen (genau so, mit dem Präfix):\n"
            f"{GATE} {oeffentlich}\n"
            f"2. Prüfskript liegt unter /config/pyscript/shell/owui_ssh_gate.sh (muss vorhanden sein). Add-on neu starten.\n"
            f"3. Host-Fingerprint von {self.valves.host}:{self.valves.port}: {fp} ({stand}). David vergleicht ihn im SSH-Terminal mit "
            f"`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` und trägt ihn ins Ventil host_fingerprint ein.\n"
            f"4. Test: ha_ssh(\"hilfe\")."
        )

    async def ha_ssh(self, befehl: str, __event_emitter__=None) -> str:
        """
        Eine Aktion auf dem HA-Host. Aktionen: hilfe; info [core|supervisor|os|host|resolution]; check; logs <core|supervisor|host|app-slug> [zeilen]; apps; ls <pfad>; cat <datei>; tail <datei> [zeilen]; grep <wort> <datei>; du <pfad>; df; neustart <core|app-slug>; app_start/app_stop <app-slug>. Pfade absolut unter /config, /share, /media.
        :param befehl: z. B. "logs core 200" oder "cat /config/automations.yaml"
        :return: Exit-Code und Ausgabe (gekürzt)
        """
        f = self._pruefen(befehl)
        if f:
            return "Fehler: " + f
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": f"HA-SSH: {befehl}", "done": False}})
        try:
            conn = await self._verbinden()
            async with conn:
                return await self._ausfuehren(conn, befehl, self.valves.max_zeichen)
        except Exception as e:
            return f"Fehler: {e}"
        finally:
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": f"HA-SSH: {befehl}", "done": True}})

    async def ha_ssh_mehrere(self, befehle: list[str], __event_emitter__=None) -> str:
        """
        Mehrere Aktionen in einer Verbindung, z. B. ["check", "logs core 100", "logs core_mosquitto 50"]. Aktionen wie bei ha_ssh.
        :param befehle: Liste der Befehle (als Liste, nicht als Text)
        :return: je Befehl Exit-Code und Ausgabe
        """
        if isinstance(befehle, str):
            befehle = [b for b in befehle.splitlines() if b.strip()]
        if not isinstance(befehle, list) or not befehle or len(befehle) > 15:
            return "Fehler: befehle muss eine Liste mit 1 bis 15 Befehlen sein."
        for b in befehle:
            f = self._pruefen(str(b))
            if f:
                return f"Fehler bei „{b}“: {f} Nichts ausgeführt."
        je = max(800, self.valves.max_zeichen // len(befehle))
        teile = []
        try:
            conn = await self._verbinden()
            async with conn:
                for i, b in enumerate(befehle, 1):
                    if __event_emitter__:
                        await __event_emitter__({"type": "status", "data": {"description": f"HA-SSH {i}/{len(befehle)}: {b}", "done": False}})
                    teile.append(f"## {b}\n" + await self._ausfuehren(conn, str(b), je))
        except Exception as e:
            teile.append(f"Fehler: {e}")
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "HA-SSH: fertig", "done": True}})
        return "\n\n".join(teile)
