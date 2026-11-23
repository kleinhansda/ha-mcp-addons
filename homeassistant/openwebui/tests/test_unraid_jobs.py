#!/usr/bin/env python3
"""Tests für die Hintergrund-Jobs des Unraid-Werkzeugs. Statt SSH führt eine Ersatzverbindung die
Befehle lokal mit bash aus; geprüft werden Start, Warten, Job-ID, Doppelstart, Status, Bereinigung.

  python3 homeassistant/openwebui/tests/test_unraid_jobs.py
"""
import asyncio, importlib.util, sys, tempfile, re, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("u", Path(__file__).resolve().parents[1] / "unraid_tool.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
d = tempfile.mkdtemp(); u.JOB_ORDNER = d + "/jobs"
class R:  # Ergebnis wie asyncssh
    def __init__(s, rc, out): s.exit_status, s.stdout, s.stderr = rc, out, ""
class Conn:
    async def run(s, cmd, input=None, check=False):
        p = await asyncio.create_subprocess_exec("bash", "-c", cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        o, _ = await p.communicate(); return R(p.returncode, o.decode())
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
ok = 0
def check(b, w):
    global ok
    assert b, w; ok += 1; print("ok  ", w)
async def main():
    t = u.Tools(); t.valves.warten = 2; t.valves.timeout = 30
    async def verb(): return Conn()
    t._verbinden = verb
    c = Conn()
    rc, out = await t._job(c, "echo hallo; exit 3", "kurz")
    check(rc == 3 and out.strip() == "hallo", f"kurzer Befehl: Exit-Code und Ausgabe ({rc}, {out!r})")
    t0 = time.time()
    rc, out = await t._job(c, "echo start; sleep 4; echo ende password=geheim123456", "lang")
    check(rc is None and "Job " in out and "start" in out and time.time() - t0 < 4, "langer Befehl: kehrt nach warten mit Job-ID zurück")
    jid = re.search(r"Job (\d{10}-[0-9a-f]{8})", out).group(1)
    rc, out2 = await t._job(c, "echo start; sleep 4; echo ende", "lang")
    check(rc is None and "läuft schon" in out2 and jid in out2, "gleicher Befehl läuft schon: nicht doppelt gestartet")
    s = await t.unraid_job_status(jid)
    check("läuft seit" in s and "start" in s, "Status: läuft")
    liste = await t.unraid_job_status("")
    check(jid in liste and "lang" in liste, "Liste nennt den Job")
    await asyncio.sleep(3)
    s = await t.unraid_job_status(jid)
    check("fertig, exit 0" in s and "ende" in s and "geheim123456" not in s, "Status: fertig, Ausgabe bereinigt: " + s.replace("\n"," | "))
    s = await t.unraid_job_status(jid)
    check("gibt es nicht" in s, "abgefragter fertiger Job wird entfernt")
    check((await t.unraid_job_status("x; rm -rf /")).startswith("Fehler"), "ungültige Job-ID abgelehnt")
    rc, out = await t._job(c, "echo neu", "lang")
    check(rc == 0, "nach Ende darf derselbe Befehl wieder starten")
asyncio.run(main()); print(ok, "Prüfungen bestanden")
