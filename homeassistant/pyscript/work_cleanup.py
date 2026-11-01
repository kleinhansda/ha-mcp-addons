"""Arbeitsordner aufräumen (Pyscript für Home Assistant).

Dateien in inbox/ und out/ des Arbeitsordners werden 14 Tage nach ihrem ersten
Auftauchen gelöscht. 2 Tage vorher kommt eine Benachrichtigung aufs Handy mit dem
Knopf "Alle behalten"; der verschiebt die Dateien nach behalten/ (wird nicht
aufgeräumt).

Das Alter zählt ab dem ersten Scan, nicht ab dem Änderungsdatum der Datei. Kamerafotos
behalten ihr Aufnahmedatum; nach mtime würden sie sofort gelöscht.

Installation: Datei nach /config/pyscript/work_cleanup.py kopieren. Pyscript lädt sie
selbst neu. Werte unten anpassen. Manuell: Dienst pyscript.work_cleanup_run.
"""

WORK_DIR = "/share/artcraft/work"
SUBDIRS = ["inbox", "out"]
KEEP_DIR = "behalten"
DAYS = 14
WARN_DAYS = 2
NOTIFY_SERVICE = "notify.mobile_app_xp1v"   # leer = nur Benachrichtigung in HA
STATE_FILE = "/config/.work_cleanup.json"
DRY_RUN = False                              # True = nur melden, nichts löschen
KEEP_ACTION = "WORK_CLEANUP_KEEP"
NOTIFICATION_ID = "work_cleanup"
DAY = 86400


@pyscript_compile
def _now():
    import time
    return time.time()


@pyscript_compile
def _load(path):
    import json, os
    if not os.path.exists(path):
        return {"files": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("files", {})
    return data


@pyscript_compile
def _save(path, data):
    import json, os
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


@pyscript_compile
def _scan(work, subdirs, data, now):
    """Neue Dateien mit Zeitpunkt des ersten Auftauchens eintragen, verschwundene austragen."""
    import os
    seen = {}
    for sub in subdirs:
        base = os.path.join(work, sub)
        os.makedirs(base, exist_ok=True)
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if name.startswith("."):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, work)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                entry = data["files"].get(rel) or {"first_seen": now, "warned_at": None}
                entry["size"] = size
                seen[rel] = entry
    data["files"] = seen
    return data


@pyscript_compile
def _plan(data, now, days, warn_days, dry_run):
    """Liefert (neu zu warnen, zu löschen). Gelöscht wird nur, was mindestens
    warn_days vorher gemeldet wurde (1 h Toleranz für den täglichen Lauf)."""
    warn, delete = [], []
    for rel, e in sorted(data["files"].items()):
        age = now - e["first_seen"]
        if e.get("warned_at") is None:
            if age >= (days - warn_days) * 86400:
                warn.append(rel)
        elif age >= days * 86400 and now - e["warned_at"] >= warn_days * 86400 - 3600:
            if not (dry_run and e.get("dry_reported")):
                delete.append(rel)
    return warn, delete


@pyscript_compile
def _delete(work, subdirs, rels):
    import os
    done = []
    for rel in rels:
        try:
            os.remove(os.path.join(work, rel))
            done.append(rel)
        except FileNotFoundError:
            done.append(rel)
        except OSError:
            pass
    for sub in subdirs:            # leere Unterordner entfernen, inbox/ und out/ bleiben
        base = os.path.join(work, sub)
        for root, dirs, files in os.walk(base, topdown=False):
            if root != base and not os.listdir(root):
                try:
                    os.rmdir(root)
                except OSError:
                    pass
    return done


@pyscript_compile
def _keep(work, keep_dir, rels):
    """Nach behalten/<pfad> verschieben; bei Namensgleichheit -1, -2 … anhängen."""
    import os, shutil
    moved = []
    for rel in rels:
        src = os.path.join(work, rel)
        if not os.path.exists(src):
            continue
        dst = os.path.join(work, keep_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        stem, ext = os.path.splitext(dst)
        n = 1
        while os.path.exists(dst):
            dst = f"{stem}-{n}{ext}"
            n += 1
        shutil.move(src, dst)
        moved.append(os.path.relpath(dst, work))
    return moved


@pyscript_compile
def _summary(data, rels, limit=8):
    size = sum(data["files"].get(r, {}).get("size", 0) for r in rels)
    lines = [f"• {r}" for r in rels[:limit]]
    if len(rels) > limit:
        lines.append(f"… und {len(rels) - limit} weitere")
    return f"{len(rels)} Dateien, {size / 1e6:.1f} MB", "\n".join(lines)


async def _notify(title, message, actions=False):
    await service.call("persistent_notification", "create", title=title, message=message,
                 notification_id=NOTIFICATION_ID)
    if NOTIFY_SERVICE:
        domain, name = NOTIFY_SERVICE.split(".", 1)
        data = {"tag": NOTIFICATION_ID}
        if actions:
            data["actions"] = [{"action": KEEP_ACTION, "title": "Alle behalten"}]
        await service.call(domain, name, title=title, message=message, data=data)


async def _run(dry_run):
    now = _now()
    data = await task.executor(_load, STATE_FILE)
    data = await task.executor(_scan, WORK_DIR, SUBDIRS, data, now)
    warn, delete = _plan(data, now, DAYS, WARN_DAYS, dry_run)

    if warn:
        for rel in warn:
            data["files"][rel]["warned_at"] = now
        head, body = _summary(data, warn)
        prefix = "Probelauf: " if dry_run else ""
        await _notify(
            f"{prefix}Arbeitsordner: {head} werden in {WARN_DAYS} Tagen gelöscht",
            f"{body}\n\nBehalten: Knopf „Alle behalten“ oder Dateien aus inbox/ bzw. out/ "
            f"in einen anderen Ordner von {WORK_DIR} verschieben.",
            actions=True)

    if delete:
        head, body = _summary(data, delete)
        if dry_run:
            for rel in delete:
                data["files"][rel]["dry_reported"] = True
            await _notify(f"Probelauf: Arbeitsordner würde {head} löschen", body)
        else:
            done = await task.executor(_delete, WORK_DIR, SUBDIRS, delete)
            for rel in done:
                data["files"].pop(rel, None)
            await service.call("persistent_notification", "create",
                         title=f"Arbeitsordner: {len(done)} Dateien gelöscht", message=body,
                         notification_id=NOTIFICATION_ID)
        log.info(f"work_cleanup: {len(delete)} fällig, Probelauf={dry_run}")

    await task.executor(_save, STATE_FILE, data)
    log.info(f"work_cleanup: {len(data['files'])} Dateien verfolgt, {len(warn)} gewarnt, "
             f"{len(delete)} fällig")


@time_trigger("startup", "cron(7 * * * *)")
async def work_cleanup_scan():
    """Stündlich neue Dateien erfassen, damit das Alter ab dem Auftauchen zählt."""
    data = await task.executor(_load, STATE_FILE)
    data = await task.executor(_scan, WORK_DIR, SUBDIRS, data, _now())
    await task.executor(_save, STATE_FILE, data)


@time_trigger("cron(0 9 * * *)")
async def work_cleanup_daily():
    await _run(DRY_RUN)


@service
async def work_cleanup_run(dry_run=None):
    """yaml
name: Arbeitsordner aufräumen
description: Warnt und löscht wie der tägliche Lauf um 9 Uhr.
fields:
  dry_run:
    name: Probelauf
    description: Nur melden, nichts löschen. Leer = Wert aus dem Skript.
    selector:
      boolean:
"""
    await _run(DRY_RUN if dry_run is None else bool(dry_run))


@event_trigger("mobile_app_notification_action", "action == 'WORK_CLEANUP_KEEP'")
async def work_cleanup_keep(**kwargs):
    """Knopf „Alle behalten“: gewarnte Dateien nach behalten/ verschieben."""
    data = await task.executor(_load, STATE_FILE)
    data = await task.executor(_scan, WORK_DIR, SUBDIRS, data, _now())
    pending = [r for r, e in sorted(data["files"].items()) if e.get("warned_at") is not None]
    moved = await task.executor(_keep, WORK_DIR, KEEP_DIR, pending)
    for rel in pending:
        data["files"].pop(rel, None)
    await task.executor(_save, STATE_FILE, data)
    await service.call("persistent_notification", "create",
                 title=f"Arbeitsordner: {len(moved)} Dateien behalten",
                 message=f"Verschoben nach {WORK_DIR}/{KEEP_DIR}/",
                 notification_id=NOTIFICATION_ID)
    log.info(f"work_cleanup: {len(moved)} Dateien nach {KEEP_DIR}/ verschoben")
