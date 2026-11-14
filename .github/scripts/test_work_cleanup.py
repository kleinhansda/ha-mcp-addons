# Szenariotest für homeassistant/pyscript/work_cleanup.py mit nachgebauten Pyscript-Funktionen.
#   python3 .github/scripts/test_work_cleanup.py homeassistant/pyscript/work_cleanup.py
import asyncio, os, sys, tempfile, json, types
src = open(sys.argv[1]).read()
calls = []
class Task:
    @staticmethod
    async def executor(fn, *a, **k): return fn(*a, **k)
class Svc:
    @staticmethod
    async def call(domain, name, **k): calls.append((domain, name, k))
class Log:
    info = staticmethod(lambda m: print("LOG", m))
ident = lambda *a, **k: (lambda f: f)
def service(f=None, **k): return f if f else (lambda g: g)
clock = [1_800_000_000.0]
g = dict(pyscript_compile=lambda f: f, time_trigger=ident, event_trigger=ident, service=service,
         task=Task, log=Log, __name__="ws")
exec(compile(src, "work_cleanup.py", "exec"), g)
g["service"] = Svc
tmp = tempfile.mkdtemp()
work = os.path.join(tmp, "work"); os.makedirs(work)
chat = os.path.join(tmp, "openwebui"); users = os.path.join(tmp, "owuiusers")
for d in (os.path.join(chat, "inbox"), os.path.join(users, "f00dbabe", "inbox"), os.path.join(users, "gemeinsam", "inbox")):
    os.makedirs(d)
g["ZIELE"] = [
    {"name": "ArtCraft/Foto", "wurzel": work, "unter": ["inbox", "out"], "tage": 14},
    {"name": "Chat-Anhänge", "wurzel": chat, "unter": ["inbox"], "tage": 30},
    {"name": "Chat-Anhänge Familie", "wurzel": os.path.join(users, "*"), "unter": ["inbox"], "tage": 30, "ohne": ["gemeinsam"]},
]
g["STATE_FILE"] = os.path.join(tmp, "state.json"); g["ALT_WORK_DIR"] = work
W = lambda rel: os.path.join(work, rel)
g["_now"] = lambda: clock[0]
DAY = 86400
def mk(rel, mtime=0):
    p = os.path.join(work, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(b"x" * 1000); os.utime(p, (mtime, mtime))
def at(day, hour=9): clock[0] = 1_800_000_000.0 + day * DAY + (hour - 9) * 3600
run = lambda coro: asyncio.run(coro)
def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond: sys.exit(1)

# Tag 0, 10 Uhr: Foto mit altem Aufnahmedatum (mtime 2020) + Datei in Unterordner
at(0, 10); mk("inbox/IMG_1.jpg", mtime=1_600_000_000); mk("out/sub/a.png"); mk("inbox/.hidden"); mk("root.txt")
run(g["work_cleanup_scan"]())
st = json.load(open(g["STATE_FILE"]))
check(set(st["files"]) == {W("inbox/IMG_1.jpg"), W("out/sub/a.png")}, "nur inbox/out, keine versteckten/Wurzel-Dateien")
at(1); run(g["work_cleanup_daily"]())
check(os.path.exists(W("inbox/IMG_1.jpg")), "altes mtime löscht nicht sofort")
check(not calls, "keine Meldung an Tag 1")
at(12); run(g["work_cleanup_daily"]())
check(not calls, "Tag 12 09:00: Alter 11.96 Tage, noch keine Warnung")
at(13); run(g["work_cleanup_daily"]())
check(len(calls) == 2 and "in 2 Tagen gelöscht" in calls[0][2]["title"], "Tag 13: Warnung (HA + Handy)")
check(calls[1][:2] == ("notify", "mobile_app_xp1v") and calls[1][2]["data"]["actions"][0]["action"] == "WORK_CLEANUP_KEEP", "Handy mit Knopf")
calls.clear()
at(14); run(g["work_cleanup_daily"]())
check(not calls and os.path.exists(os.path.join(work, "out/sub/a.png")), "Tag 14: noch nicht gelöscht (Warnfrist)")
# neue Datei an Tag 14
mk("inbox/neu.jpg"); run(g["work_cleanup_scan"]())
at(15); run(g["work_cleanup_daily"]())
check(not os.path.exists(W("inbox/IMG_1.jpg")) and not os.path.exists(os.path.join(work, "out/sub")), "Tag 15: gelöscht, leerer Unterordner weg")
check(os.path.isdir(os.path.join(work, "out")) and os.path.exists(os.path.join(work, "inbox/neu.jpg")) and os.path.exists(os.path.join(work, "root.txt")), "out/ bleibt, neue Datei und Wurzel bleiben")
check(any("gelöscht" in c[2]["title"] for c in calls), "Meldung über Löschung")
calls.clear()
# Behalten-Knopf
at(27); run(g["work_cleanup_daily"]())
check(any("in 2 Tagen" in c[2]["title"] for c in calls), "Tag 27: Warnung für neu.jpg")
mk("behalten/inbox/neu.jpg")
run(g["work_cleanup_keep"](action="WORK_CLEANUP_KEEP"))
check(os.path.exists(os.path.join(work, "behalten/inbox/neu-1.jpg")) and not os.path.exists(os.path.join(work, "inbox/neu.jpg")), "Behalten verschiebt, Namenskonflikt -1")
at(30); calls.clear(); run(g["work_cleanup_daily"]())
check(os.path.exists(os.path.join(work, "behalten/inbox/neu-1.jpg")) and not calls, "behalten/ wird nicht aufgeräumt")
# Probelauf
at(31); mk("out/p.jpg"); run(g["work_cleanup_scan"]())
at(44); run(g["work_cleanup_run"](dry_run=True)); at(46); calls.clear(); run(g["work_cleanup_run"](dry_run=True))
check(os.path.exists(os.path.join(work, "out/p.jpg")) and any("würde" in c[2]["title"] for c in calls), "Probelauf löscht nicht, meldet")
calls.clear(); at(47); run(g["work_cleanup_run"](dry_run=True))
check(not calls, "Probelauf meldet nicht täglich erneut")
# Weitere Ordner: Chat-Anhänge (30 Tage), je Nutzer per *, gemeinsam ausgelassen
def mkp(p):
    os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(b"y" * 10)
at(50); calls.clear()
a = os.path.join(chat, "inbox", "2026-11-01", "brief.pdf"); b = os.path.join(users, "f00dbabe", "inbox", "d", "foto.jpg")
c = os.path.join(users, "gemeinsam", "inbox", "x.txt"); idx = os.path.join(chat, "inbox", ".index.json")
for p in (a, b, c, idx): mkp(p)
run(g["work_cleanup_scan"]())
st = json.load(open(g["STATE_FILE"]))
check(a in st["files"] and b in st["files"] and c not in st["files"] and idx not in st["files"],
      "Chat-Anhänge und Arbeitsbereiche erfasst, gemeinsam/ und .index.json nicht")
at(64); run(g["work_cleanup_daily"]())
check(not any(a in str(x) for x in calls), "Chat-Anhang nach 14 Tagen noch nicht gewarnt (Frist 30)")
at(78); run(g["work_cleanup_daily"]())
check(any("brief.pdf" in x[2].get("message", "") and "f00dbabe" in x[2].get("message", "") for x in calls), "Tag 28: Warnung für beide mit Pfad")
run(g["work_cleanup_keep"](action="WORK_CLEANUP_KEEP"))
check(os.path.exists(os.path.join(users, "f00dbabe", "behalten", "inbox", "d", "foto.jpg"))
      and os.path.exists(os.path.join(chat, "behalten", "inbox", "2026-11-01", "brief.pdf")), "Behalten je Wurzel")
check(os.path.exists(c), "gemeinsam/ bleibt unberührt")
# alter Zustand mit relativen Pfaden wird übernommen (Warnung bleibt gültig)
mk("inbox/alt.zip")
json.dump({"files": {"inbox/alt.zip": {"first_seen": clock[0] - 14 * DAY, "warned_at": clock[0] - 2 * DAY, "size": 1}}},
          open(g["STATE_FILE"], "w"))
calls.clear(); run(g["work_cleanup_daily"]())
check(not os.path.exists(W("inbox/alt.zip")), "relativer Altzustand: gewarnte Datei fristgerecht gelöscht")
print("ALLE TESTS OK")
