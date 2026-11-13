"""Schutz der Datei-Werkzeuge im Mehrbenutzer-Modus (App Open Terminal).

Open Terminal führt Befehle unter dem Konto des Nutzers aus, liest und schreibt Dateien über die
Datei-API aber selbst, als "user". Seine einzige Prüfung (UserFS.is_path_allowed) sperrt nur
fremde Homes unter /home. Dieses Modul ersetzt die Prüfung für Konten, die keine Administratoren
sind: erlaubt sind nur das eigene Home, der eigene Arbeitsbereich und der gemeinsame Ordner unter
dem Familienordner sowie Systempfade zum Lesen (Schreiben verhindern dort die Dateirechte).
Geprüft wird der echte Pfad (Links aufgelöst), damit ein Link im Home nicht hinausführt.

Ist der Speicher eines Kontos voll (Datei .speicher-voll im Arbeitsbereich, gesetzt von
terminal-konten), lehnt die Datei-API Schreiben ab; Löschen bleibt erlaubt.

Aktiv nur mit OT_SCHUTZ=1 (setzt run.sh im Mehrbenutzer-Modus), geladen über eine .pth-Datei.
Umgebung:
  OT_SCHUTZ_ADMIN_HOME  Home der Administratoren (/data/home): dort keine Einschränkung
  OT_SCHUTZ_FAMILIE     Familienordner, z. B. /share/owuiusers (leer = keiner)
"""

import os

LESEN = ("/usr", "/opt", "/etc")
GEMEINSAM = "gemeinsam"
VOLL = ".speicher-voll"


def _unter(pfad, wurzel):
    wurzel = wurzel.rstrip("/") or "/"
    return pfad == wurzel or pfad.startswith(wurzel + "/")


def einrichten():
    if os.environ.get("OT_SCHUTZ") != "1":
        return False
    try:
        from open_terminal.utils import fs as _fs
    except Exception:
        return False
    if getattr(_fs.UserFS, "_ot_schutz", False):
        return True

    admin_home = os.path.realpath(os.environ.get("OT_SCHUTZ_ADMIN_HOME") or "/data/home")
    familie = os.environ.get("OT_SCHUTZ_FAMILIE", "").rstrip("/")
    original = _fs.UserFS.is_path_allowed

    def ist_admin(self):
        return not self.username or os.path.realpath(self.home) == admin_home

    def bereich(self):
        return os.path.join(familie, self.username) if familie else ""

    def is_path_allowed(self, path):
        if ist_admin(self):
            return original(self, path)
        echt = os.path.realpath(path)
        erlaubt = [os.path.realpath(self.home)]
        if familie:
            erlaubt += [os.path.realpath(bereich(self)), os.path.realpath(os.path.join(familie, GEMEINSAM))]
        if any(_unter(echt, w) for w in erlaubt):
            return True
        return any(_unter(echt, w) for w in LESEN)

    def _check_path(self, path):
        if not self.is_path_allowed(path):
            raise PermissionError(
                f"Zugriff verweigert: {os.path.abspath(path)} liegt außerhalb deines Bereichs "
                f"(Home, {bereich(self) or 'kein Arbeitsbereich'}, {familie + '/' + GEMEINSAM if familie else ''})"
            )

    def voll(self):
        if ist_admin(self) or not familie:
            return False
        return os.path.exists(os.path.join(bereich(self), VOLL))

    def schreibschutz(methode):
        async def geschuetzt(self, *args, **kwargs):
            if voll(self):
                raise PermissionError(
                    "Speicher voll: Dein Speicherplatz ist aufgebraucht. Lösche Dateien, dann kannst du "
                    "wieder speichern."
                )
            return await methode(self, *args, **kwargs)
        geschuetzt.__name__ = methode.__name__
        return geschuetzt

    _fs.UserFS.is_path_allowed = is_path_allowed
    _fs.UserFS._check_path = _check_path
    for name in ("write", "write_bytes", "mkdir", "move"):
        setattr(_fs.UserFS, name, schreibschutz(getattr(_fs.UserFS, name)))
    _fs.UserFS._ot_schutz = True
    return True


try:
    einrichten()
except Exception as e:  # nie den Start verhindern, aber laut melden
    print(f"[open-terminal-app] WARNUNG: Schutz der Datei-Werkzeuge nicht aktiv: {e}", flush=True)
