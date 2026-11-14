"""Arbeitsordner aufräumen (Pyscript für Home Assistant).

Dateien in den Eingangs- und Ausgabeordnern (siehe ZIELE) werden eine Frist lang nach ihrem
ersten Auftauchen gelöscht. 2 Tage vorher kommt eine Benachrichtigung aufs Handy mit dem
Knopf "Alle behalten"; der verschiebt die Dateien in den Ordner behalten/ neben dem
jeweiligen Eingang (wird nicht aufgeräumt).

Das Alter zählt ab dem ersten Scan, nicht ab dem Änderungsdatum der Datei. Kamerafotos
behalten ihr Aufnahmedatum; nach mtime würden sie sofort gelöscht.

Installation: Datei nach /config/pyscript/work_cleanup.py kopieren. Pyscript lädt sie
selbst neu. Werte unten anpassen. Manuell: Dienst pyscript.work_cleanup_run.
"""

# Je Ziel: Wurzel (darf * enthalten, z. B. ein Ordner je Nutzer), aufzuräumende Unterordner,
# Frist in Tagen, Wurzeln, die bei * auszulassen sind. "behalten" liegt jeweils in der Wurzel.
ZIELE = [
    {"name": "ArtCraft/Foto", "wurzel": "/share/artcraft/work", "unter": ["inbox", "out"], "tage": 14},
    {"name": "Chat-Anhänge", "wurzel": "/share/openwebui", "unter": ["inbox"], "tage": 30},
    {"name": "Chat-Anhänge Familie", "wurzel": "/share/owuiusers/*", "unter": ["inbox"], "tage": 30,
     "ohne": ["gemeinsam"]},
]
KEEP_DIR = "behalten"
WARN_DAYS = 2
NOTIFY_SERVICE = "notify.mobile_app_xp1v"   # leer = nur Benachrichtigung in HA
STATE_FILE = "/config/.work_cleanup.json"
ALT_WORK_DIR = "/share/artcraft/work"        # bis 2026-11: Pfade im Zustand relativ dazu
DRY_RUN = False                              # True = nur melden, nichts löschen
KEEP_ACTION = "WORK_CLEANUP_KEEP"
NOTIFICATION_ID = "work_cleanup"


@pyscript_compile
def _now():
    import time
    return time.time()


@pyscript_compile
def _load(path, alt_work):
    import json, os
    if not os.path.exists(path):
        return {"files": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    files = data.get("files") or {}
    # ältere Fassung: Schlüssel relativ zum einen Arbeitsordner
    data["files"] = {(k if k.startswith("/") else os.path.join(alt_work, k)): v for k, v in files.items()}
    return data


@pyscript_compile
def _save(path, data):
    import json, os
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


@pyscript_compile
def _ordner(ziele):
    """(Wurzel, Unterordner, Frist, Name) für jedes Ziel; * in der Wurzel aufgelöst."""
    import glob, os
    out = []
    for z in ziele:
        wurzeln = sorted(glob.glob(z["wurzel"])) if "*" in z["wurzel"] else [z["wurzel"]]
        for w in wurzeln:
            if not os.path.isdir(w) or os.path.basename(w) in z.get("ohne", []):
                continue
            for sub in z["unter"]:
                out.append((w, sub, z["tage"], z["name"]))
    return out


@pyscript_compile
def _scan(ordner, data, now):
    """Neue Dateien mit Zeitpunkt des ersten Auftauchens eintragen, verschwundene austragen."""
    import os
    seen = {}
    for wurzel, sub, tage, name in ordner:
        base = os.path.join(wurzel, sub)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for datei in files:
                if datei.startswith("."):
                    continue
                full = os.path.join(root, datei)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                entry = data["files"].get(full) or {"first_seen": now, "warned_at": None}
                entry.update(size=size, days=tage, root=wurzel, label=name)
                seen[full] = entry
    data["files"] = seen
    return data


@pyscript_compile
def _plan(data, now, warn_days, dry_run):
    """Liefert (neu zu warnen, zu löschen). Gelöscht wird nur, was mindestens
    warn_days vorher gemeldet wurde (1 h Toleranz für den täglichen Lauf)."""
    warn, delete = [], []
    for full, e in sorted(data["files"].items()):
        age = now - e["first_seen"]
        days = e.get("days", 14)
        if e.get("warned_at") is None:
            if age >= (days - warn_days) * 86400:
                warn.append(full)
        elif age >= days * 86400 and now - e["warned_at"] >= warn_days * 86400 - 3600:
            if not (dry_run and e.get("dry_reported")):
                delete.append(full)
    return warn, delete


@pyscript_compile
def _delete(ordner, fulls):
    import os
    done = []
    for full in fulls:
        try:
            os.remove(full)
            done.append(full)
        except FileNotFoundError:
            done.append(full)
        except OSError:
            pass
    for wurzel, sub, tage, name in ordner:   # leere Unterordner entfernen, inbox/ und out/ bleiben
        base = os.path.join(wurzel, sub)
        for root, dirs, files in os.walk(base, topdown=False):
            if root != base and not os.listdir(root):
                try:
                    os.rmdir(root)
                except OSError:
                    pass
    return done


@pyscript_compile
def _keep(data, keep_dir, fulls):
    """Nach <wurzel>/behalten/<pfad> verschieben; bei Namensgleichheit -1, -2 … anhängen."""
    import os, shutil
    moved = []
    for full in fulls:
        if not os.path.exists(full):
            continue
        wurzel = data["files"][full]["root"]
        dst = os.path.join(wurzel, keep_dir, os.path.relpath(full, wurzel))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        stem, ext = os.path.splitext(dst)
        n = 1
        while os.path.exists(dst):
            dst = f"{stem}-{n}{ext}"
            n += 1
        shutil.move(full, dst)
        moved.append(dst)
    return moved


@pyscript_compile
def _summary(data, fulls, limit=8):
    import os
    size = sum(data["files"].get(f, {}).get("size", 0) for f in fulls)
    lines = []
    for f in fulls[:limit]:
        e = data["files"].get(f, {})
        lines.append(f"• {e.get('label', '')}: {f.removeprefix('/share/')}")
    if len(fulls) > limit:
        lines.append(f"… und {len(fulls) - limit} weitere")
    return f"{len(fulls)} Dateien, {size / 1e6:.1f} MB", "\n".join(lines)


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
    ordner = await task.executor(_ordner, ZIELE)
    data = await task.executor(_load, STATE_FILE, ALT_WORK_DIR)
    data = await task.executor(_scan, ordner, data, now)
    warn, delete = _plan(data, now, WARN_DAYS, dry_run)

    if warn:
        for full in warn:
            data["files"][full]["warned_at"] = now
        head, body = _summary(data, warn)
        prefix = "Probelauf: " if dry_run else ""
        await _notify(
            f"{prefix}Aufräumen: {head} werden in {WARN_DAYS} Tagen gelöscht",
            f"{body}\n\nBehalten: Knopf „Alle behalten“ (verschiebt nach {KEEP_DIR}/ im jeweiligen "
            f"Ordner) oder die Dateien selbst aus inbox/ bzw. out/ herausnehmen.",
            actions=True)

    if delete:
        head, body = _summary(data, delete)
        if dry_run:
            for full in delete:
                data["files"][full]["dry_reported"] = True
            await _notify(f"Probelauf: Aufräumen würde {head} löschen", body)
        else:
            done = await task.executor(_delete, ordner, delete)
            for full in done:
                data["files"].pop(full, None)
            await service.call("persistent_notification", "create",
                         title=f"Aufräumen: {len(done)} Dateien gelöscht", message=body,
                         notification_id=NOTIFICATION_ID)
        log.info(f"work_cleanup: {len(delete)} fällig, Probelauf={dry_run}")

    await task.executor(_save, STATE_FILE, data)
    log.info(f"work_cleanup: {len(data['files'])} Dateien in {len(ordner)} Ordnern verfolgt, "
             f"{len(warn)} gewarnt, {len(delete)} fällig")


@time_trigger("startup", "cron(7 * * * *)")
async def work_cleanup_scan():
    """Stündlich neue Dateien erfassen, damit das Alter ab dem Auftauchen zählt."""
    ordner = await task.executor(_ordner, ZIELE)
    data = await task.executor(_load, STATE_FILE, ALT_WORK_DIR)
    data = await task.executor(_scan, ordner, data, _now())
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
    ordner = await task.executor(_ordner, ZIELE)
    data = await task.executor(_load, STATE_FILE, ALT_WORK_DIR)
    data = await task.executor(_scan, ordner, data, _now())
    pending = [f for f, e in sorted(data["files"].items()) if e.get("warned_at") is not None]
    moved = await task.executor(_keep, data, KEEP_DIR, pending)
    for full in pending:
        data["files"].pop(full, None)
    await task.executor(_save, STATE_FILE, data)
    await service.call("persistent_notification", "create",
                 title=f"Aufräumen: {len(moved)} Dateien behalten",
                 message="\n".join(f"• {m}" for m in moved[:12]) or "nichts zu verschieben",
                 notification_id=NOTIFICATION_ID)
    log.info(f"work_cleanup: {len(moved)} Dateien nach {KEEP_DIR}/ verschoben")
