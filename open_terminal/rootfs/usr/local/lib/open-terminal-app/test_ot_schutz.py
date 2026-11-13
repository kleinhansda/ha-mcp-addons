"""Selbsttest für ot_schutz (läuft beim Bau des Images, ohne Server).

Baut in einem Temp-Ordner Homes, Familienordner und eine Datei außerhalb und prüft die
Datei-API-Klasse UserFS von Open Terminal mit eingeschaltetem Schutz.
"""

import asyncio
import os
import sys
import tempfile

t = tempfile.mkdtemp()
admin_home = os.path.join(t, "data/home")
fam_home = os.path.join(t, "data/homes/f00dbabe")
familie = os.path.join(t, "share/owuiusers")
for d in (admin_home, fam_home, os.path.join(familie, "f00dbabe/dokumente"),
          os.path.join(familie, "gemeinsam"), os.path.join(familie, "andere1"), os.path.join(t, "share/dokumente")):
    os.makedirs(d, exist_ok=True)
geheim = os.path.join(t, "share/dokumente/geheim.txt")
open(geheim, "w").write("vertraulich")
open(os.path.join(familie, "andere1/privat.txt"), "w").write("privat")
os.symlink(os.path.join(t, "share/dokumente"), os.path.join(fam_home, "abkuerzung"))
os.symlink(os.path.join(familie, "f00dbabe/dokumente"), os.path.join(fam_home, "dokumente"))

os.environ.update(OT_SCHUTZ="1", OT_SCHUTZ_ADMIN_HOME=admin_home, OT_SCHUTZ_FAMILIE=familie)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ot_schutz  # noqa: E402

assert ot_schutz.einrichten(), "Schutz nicht eingerichtet"
from open_terminal.utils.fs import UserFS  # noqa: E402


# Besitz und Elternordner legt Open Terminal per sudo als Konto an; die Testkonten gibt es hier
# nicht, geprüft wird nur die Pfadregel.
async def _ohne_konto(self, path):
    os.makedirs(path, exist_ok=True)


UserFS._ensure_parents = _ohne_konto


async def _kein_chown(self, path):
    return None


UserFS._chown = _kein_chown

fam = UserFS(username="f00dbabe", home=fam_home)
admin = UserFS(username="u0928ab8", home=admin_home)
fehler = []


def soll(bedingung, text):
    print(("ok    " if bedingung else "FEHLER ") + text)
    if not bedingung:
        fehler.append(text)


def verboten(coro):
    try:
        asyncio.run(coro)
    except PermissionError:
        return True
    return False


soll(fam.is_path_allowed(os.path.join(fam_home, "x.txt")), "Familie: eigenes Home")
soll(fam.is_path_allowed(os.path.join(familie, "f00dbabe/dokumente/a.pdf")), "Familie: eigener Arbeitsbereich")
soll(fam.is_path_allowed(os.path.join(familie, "gemeinsam/a.pdf")), "Familie: gemeinsamer Ordner")
soll(fam.is_path_allowed(os.path.join(fam_home, "dokumente/a.pdf")), "Familie: Link ~/dokumente in den Arbeitsbereich")
soll(fam.is_path_allowed("/usr/bin/env"), "Familie: Systempfade lesen")
soll(not fam.is_path_allowed(geheim), "Familie: /share/dokumente gesperrt")
soll(not fam.is_path_allowed(os.path.join(fam_home, "abkuerzung/geheim.txt")), "Familie: Link aus dem Home hinaus gesperrt")
soll(not fam.is_path_allowed(os.path.join(familie, "andere1/privat.txt")), "Familie: fremder Arbeitsbereich gesperrt")
soll(not fam.is_path_allowed(os.path.join(fam_home, "../../home/x")), "Familie: Home des Administrators gesperrt")
soll(not fam.is_path_allowed(os.path.join(familie, "f00dbabe-zwilling/x")), "Familie: ähnlicher Name gesperrt")
soll(not fam.is_path_allowed("/data/options.json"), "Familie: /data gesperrt")
soll(verboten(fam.read(geheim)), "Familie: read() auf /share/dokumente wirft PermissionError")
soll(verboten(fam.read(os.path.join(fam_home, "abkuerzung/geheim.txt"))), "Familie: read() über Link wirft PermissionError")
soll(admin.is_path_allowed(geheim), "Administrator: /share/dokumente erlaubt")

asyncio.run(fam.write(os.path.join(familie, "f00dbabe/dokumente/neu.txt"), "hallo"))
soll(open(os.path.join(familie, "f00dbabe/dokumente/neu.txt")).read() == "hallo", "Familie: schreibt in den Arbeitsbereich")
open(os.path.join(familie, "f00dbabe", ".speicher-voll"), "w").close()
soll(verboten(fam.write(os.path.join(familie, "f00dbabe/dokumente/zwei.txt"), "x")), "Speicher voll: write() verweigert")
soll(verboten(fam.mkdir(os.path.join(fam_home, "neu"))), "Speicher voll: mkdir() verweigert")
asyncio.run(fam.remove(os.path.join(familie, "f00dbabe/dokumente/neu.txt")))
soll(not os.path.exists(os.path.join(familie, "f00dbabe/dokumente/neu.txt")), "Speicher voll: Löschen bleibt erlaubt")
asyncio.run(admin.write(os.path.join(admin_home, "a.txt"), "x"))
soll(True, "Administrator: schreibt trotz voller Familie")

if fehler:
    sys.exit(f"{len(fehler)} Prüfung(en) fehlgeschlagen")
print("Schutz der Datei-Werkzeuge: Selbsttest bestanden")
