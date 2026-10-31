#!/usr/bin/env python3
"""Foto MCP: MCP-Server (stdio, JSON-RPC) für Fotos im Arbeitsordner.

  server.py --root /share/artcraft/work

Werkzeuge: sichten, Vorschau mit Hilfslinien, Schräglage messen, aussortieren (verschieben),
optimieren und retuschieren als Hintergrundjob, Jobstatus. Alle Pfade relativ zum Arbeitsordner,
Zugriffe außerhalb werden abgelehnt. Originale werden nie überschrieben und nie gelöscht.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import shutil
import sys
import threading
import time
import traceback
import uuid
from collections import OrderedDict

import numpy as np

import fotolib as fl

VERSION = os.environ.get('FOTO_VERSION', 'dev')
PROTOCOLS = ('2025-06-18', '2025-03-26', '2024-11-05')
IMG_EXT = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp')
SKIP_DIRS = ('final', '_aussortiert')
ROOT = ''
OUT_LOCK = threading.Lock()


class ToolError(Exception):
    pass


def log(*a):
    print('[foto]', *a, file=sys.stderr, flush=True)


# ---------- Pfade ----------
def resolve(rel: str, must_exist: bool = True) -> str:
    if not isinstance(rel, str) or not rel.strip():
        raise ToolError('Pfad fehlt')
    r = rel.strip()
    for pre in (ROOT, '/work'):
        if r == pre or r.startswith(pre + '/'):
            r = r[len(pre):]
    p = os.path.realpath(os.path.join(ROOT, r.lstrip('/')))
    if p != ROOT and not p.startswith(ROOT + os.sep):
        raise ToolError(f'außerhalb des Arbeitsordners: {rel}')
    if must_exist and not os.path.exists(p):
        raise ToolError(f'nicht gefunden: {rel}')
    return p


def rel(p: str) -> str:
    return os.path.relpath(p, ROOT)


def stem(p: str) -> str:
    return os.path.splitext(os.path.basename(p))[0]


def out_dir(src: str, ausgabe: str | None) -> str:
    if not ausgabe:
        d = os.path.dirname(src)
    elif ausgabe.startswith('/'):
        d = resolve(ausgabe, must_exist=False)
    else:
        d = os.path.realpath(os.path.join(os.path.dirname(src), ausgabe))
        if not d.startswith(ROOT + os.sep):
            raise ToolError(f'Ausgabe außerhalb des Arbeitsordners: {ausgabe}')
    os.makedirs(d, exist_ok=True)
    return d


def list_images(folder: str) -> list[str]:
    out = []
    for n in sorted(os.listdir(folder)):
        p = os.path.join(folder, n)
        if n.startswith('.') or not os.path.isfile(p) or not n.lower().endswith(IMG_EXT):
            continue
        out.append(p)
    return out


def files_arg(args) -> list[str]:
    fs = args.get('dateien')
    if isinstance(fs, str):
        fs = [fs]
    if not fs:
        raise ToolError('dateien fehlt')
    out = []
    for f in fs:
        p = resolve(f)
        if os.path.isdir(p):
            out += list_images(p)
        else:
            out.append(p)
    return out


def by_stem(d: dict | None, name: str, default=None):
    if not d:
        return default
    return d.get(name, d.get(name.replace('_final', ''), default))


# ---------- Inhalte ----------
def text(obj) -> dict:
    return {'type': 'text', 'text': obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1)}


def image(rgb, quality=80) -> dict:
    return {'type': 'image', 'mimeType': 'image/jpeg', 'data': base64.b64encode(fl.jpeg_bytes(rgb, quality)).decode()}


# ---------- Jobs ----------
JOBS: OrderedDict[str, dict] = OrderedDict()
QUEUE: queue.Queue = queue.Queue()


def new_job(kind: str, files: list[str], params: dict) -> dict:
    jid = uuid.uuid4().hex[:8]
    job = dict(id=jid, art=kind, status='wartet', fortschritt=f'0/{len(files)}', dateien=[rel(f) for f in files],
               ergebnisse=[], fehler=[], vorschau=[], gestartet=None, fertig=None, _files=files, _params=params)
    JOBS[jid] = job
    while len(JOBS) > 12:
        JOBS.popitem(last=False)
    QUEUE.put(jid)
    return job


def worker():
    while True:
        jid = QUEUE.get()
        job = JOBS.get(jid)
        if not job:
            continue
        job['status'] = 'läuft'; job['gestartet'] = time.strftime('%H:%M:%S')
        for i, f in enumerate(job['_files']):
            try:
                if job['art'] == 'optimieren':
                    res, prev = do_optimize(f, job['_params'])
                else:
                    res, prev = do_retouch(f, job['_params'])
                job['ergebnisse'].append(res)
                if prev is not None:
                    job['vorschau'].append((stem(f), prev))
            except Exception as e:  # ein Bild darf den Job nicht abbrechen
                log(traceback.format_exc())
                job['fehler'].append({'datei': rel(f), 'fehler': str(e)})
            job['fortschritt'] = f'{i + 1}/{len(job["_files"])}'
        job['status'] = 'fertig'; job['fertig'] = time.strftime('%H:%M:%S')


def do_optimize(src: str, prm: dict):
    name = stem(src)
    d = out_dir(src, prm.get('ausgabe', 'final'))
    rgb, exif, icc = fl.load(src)
    iso = fl.iso_of(exif)
    f = rgb.astype(np.float32) / 255; del rgb
    f = fl.usm(fl.denoise(fl.auto_tone(f), iso), 0.5 if iso >= 400 else 0.6)
    wk = by_stem(prm.get('winkel'), name)
    if wk is None:
        u8 = (f * 255).astype(np.uint8)
        deg, quelle, _ = fl.tilt(u8, fl.person_boxes(fl.faces(u8), u8.shape)); del u8
        deg = deg if 0.3 <= abs(deg) <= 6 else 0.0
    else:
        deg, quelle = float(wk), 'vorgegeben'
    g = fl.rotate(f, deg); del f
    h, w = g.shape[:2]
    forced = by_stem(prm.get('format'), name)
    if forced and forced != 'original' and forced not in fl.ASPECTS:
        raise ToolError(f'unbekanntes Format {forced}')
    u8 = (g * 255).astype(np.uint8)
    fs = fl.main_faces(fl.faces(u8)) if forced != 'original' else []
    subj = fl.subject_box(g.shape, fs)
    mitte = by_stem(prm.get('mitte'), name)
    if subj is None and mitte is not None:
        cx = float(mitte) * w
        subj = dict(x0=cx - 0.06 * w, x1=cx + 0.06 * w, y0=0.0, y1=float(h), cx=cx, eyes=0.33 * h, ganz=True)
    crop = fl.best_crop(w, h, deg, subj, forced)
    prev = fl.grid_preview(u8, 0, crop, lines=8, max_side=900, label=f"{name} {crop['format']} {deg:+.2f}")
    x, y, cw, ch = (int(round(v)) for v in (crop['x'], crop['y'], crop['w'], crop['h']))
    g = g[y:y + ch, x:x + cw]; del u8
    outs = []
    p = os.path.join(d, f'{name}_final.jpg'); fl.save_jpg(g, p, exif, icc); outs.append(rel(p))
    effs = by_stem(prm.get('effekte'), name, []) or []
    if isinstance(effs, str):
        effs = [effs]
    for e in effs:
        p = os.path.join(d, f'{name}_{e}.jpg'); fl.save_jpg(fl.effect(g, e), p, exif, icc); outs.append(rel(p))
    ret = prm.get('retusche')
    if ret is True or (isinstance(ret, list) and name in ret):
        rimg = (g * 255).astype(np.uint8); rf = fl.main_faces(fl.faces(rimg))
        if rf:
            r, _ = fl.retouch(rimg, rf, float(prm.get('retusche_staerke', 1.0)))
            p = os.path.join(d, f'{name}_retusche.jpg'); fl.save_jpg(r, p, exif, icc); outs.append(rel(p))
    return dict(bild=name, winkel=round(deg, 2), quelle=quelle, gesichter=len(fs), format=crop['format'],
                motivanteil=crop.get('motivanteil'), groesse=[cw, ch], dateien=outs), prev


def do_retouch(src: str, prm: dict):
    name = stem(src).replace('_final', '')
    d = out_dir(src, prm.get('ausgabe'))
    rgb, exif, icc = fl.load(src)
    fs = fl.main_faces(fl.faces(rgb))
    if not fs:
        return dict(bild=name, gesichter=0, hinweis='kein Gesicht gefunden, nichts geschrieben'), None
    res, info = fl.retouch(rgb, fs, float(prm.get('staerke', 1.0)))
    p = os.path.join(d, f'{name}_retusche.jpg')
    if os.path.realpath(p) == os.path.realpath(src):
        raise ToolError('Ausgabe wäre das Original')
    fl.save_jpg(res, p, exif, icc)
    tiles = []
    for pts in fs[:2]:
        fw = np.ptp(pts[:, 0]); x0, y0 = np.maximum(pts.min(0) - fw * 0.15, 0).astype(int)
        x1, y1 = np.minimum(pts.max(0) + fw * 0.15, rgb.shape[1::-1]).astype(int)
        tiles += [rgb[y0:y1, x0:x1], res[y0:y1, x0:x1]]
    return dict(bild=name, gesichter=len(fs), details=info, datei=rel(p)), fl.side_by_side(tiles, 420)


# ---------- Werkzeuge ----------
def t_sichten(a):
    folder = resolve(a.get('ordner', ''))
    if not os.path.isdir(folder):
        raise ToolError('ordner ist kein Ordner')
    files = list_images(folder)
    seite = max(1, int(a.get('seite', 1))); pro = 24
    part = files[(seite - 1) * pro: seite * pro]
    sums: dict[str, str] = {}
    by_size: dict[int, list[str]] = {}
    for f in files:
        by_size.setdefault(os.path.getsize(f), []).append(f)
    for grp in by_size.values():
        if len(grp) > 1:
            for f in grp:
                sums[f] = fl.md5(f)
    first: dict[str, str] = {}; dup = {}
    for f in files:
        if f in sums:
            if sums[f] in first:
                dup[f] = os.path.basename(first[sums[f]])
            else:
                first[sums[f]] = f
    rows, thumbs = [], []
    for f in part:
        info = fl.exif_info(f)
        rgb, _, _ = fl.load(f, max_side=1200)
        s, p98 = fl.sharpness(rgb)
        row = dict(datei=os.path.basename(f), mb=round(os.path.getsize(f) / 1e6, 1), schaerfe=s, schaerfe_p98=p98,
                   helligkeit=round(float(rgb.mean()), 1), **info)
        if f in dup:
            row['kopie_von'] = dup[f]
        rows.append(row); thumbs.append((os.path.basename(f), rgb))
    serien: dict[str, list[str]] = {}
    for r in rows:
        if r.get('aufnahme') and 'kopie_von' not in r:
            serien.setdefault(f"{r['aufnahme']}|{r.get('brennweite')}", []).append(r['datei'])
    res = dict(ordner=rel(folder), bilder=len(files), seite=seite, seiten=(len(files) + pro - 1) // pro,
               kopien=len(dup), serien=[v for v in serien.values() if len(v) > 1], details=rows)
    return [text(res), image(fl.contact_sheet(thumbs, cols=6, cell=300), 75)] if thumbs else [text(res)]


def t_vorschau(a):
    items = a.get('bilder') or []
    if isinstance(items, dict):
        items = [items]
    if not items or len(items) > 6:
        raise ToolError('bilder: 1 bis 6 Einträge')
    tiles = []
    for it in items:
        p = resolve(it['datei'])
        rgb, _, _ = fl.load(p, max_side=int(it.get('max_seite', 1600)))
        deg = float(it.get('winkel', 0))
        img = fl.rotate(rgb, deg) if deg else rgb
        if it.get('ausschnitt'):
            x0, y0, x1, y1 = (float(v) for v in it['ausschnitt'])
            H, W = img.shape[:2]
            img = img[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
        img = fl.grid_preview(np.ascontiguousarray(img), 0, None, lines=int(it.get('linien', 12)),
                              max_side=1200, label=f'{stem(p)} {deg:+.2f}')
        tiles.append(img)
    return [image(fl.side_by_side(tiles, int(a.get('hoehe', 600))), 85)]


def t_neigung(a):
    out = []
    for f in files_arg(a):
        rgb, _, _ = fl.load(f, max_side=3000)
        fs = fl.faces(rgb)
        deg, quelle, wt = fl.tilt(rgb, fl.person_boxes(fs, rgb.shape))
        out.append(dict(datei=rel(f), winkel=deg, quelle=quelle, gewicht=wt, gesichter=len(fs),
                        hauptgesichter=len(fl.main_faces(fs))))
    return [text(out)]


def t_aussortieren(a):
    ziel = a.get('ziel', '_aussortiert')
    moved, skipped = [], []
    for f in files_arg(a):
        d = out_dir(f, ziel)
        dst = os.path.join(d, os.path.basename(f))
        if os.path.exists(dst):
            skipped.append(rel(f)); continue
        shutil.move(f, dst); moved.append(rel(dst))
    return [text(dict(verschoben=moved, uebersprungen_weil_vorhanden=skipped))]


def t_optimieren(a):
    files = files_arg(a)
    prm = {k: a.get(k) for k in ('ausgabe', 'winkel', 'format', 'mitte', 'effekte', 'retusche', 'retusche_staerke')
           if a.get(k) is not None}
    prm.setdefault('ausgabe', 'final')
    job = new_job('optimieren', files, prm)
    return [text(dict(job_id=job['id'], bilder=len(files), hinweis='Fortschritt und Ergebnis mit job_status abfragen.'))]


def t_retusche(a):
    files = files_arg(a)
    prm = {k: a.get(k) for k in ('ausgabe', 'staerke') if a.get(k) is not None}
    job = new_job('retusche', files, prm)
    return [text(dict(job_id=job['id'], bilder=len(files), hinweis='Fortschritt und Ergebnis mit job_status abfragen.'))]


def t_job(a):
    jid = a.get('job_id')
    if not jid:
        return [text([{k: j[k] for k in ('id', 'art', 'status', 'fortschritt', 'gestartet', 'fertig')}
                      for j in JOBS.values()])]
    job = JOBS.get(jid)
    if not job:
        raise ToolError(f'Job {jid} unbekannt (nach Neustart des Add-ons sind Jobs weg)')
    pub = {k: v for k, v in job.items() if not k.startswith('_') and k != 'vorschau'}
    out = [text(pub)]
    if job['status'] == 'fertig' and a.get('vorschau', True) and job['vorschau']:
        prev = job['vorschau']
        if job['art'] == 'optimieren':
            for i in range(0, len(prev), 12):
                out.append(image(fl.contact_sheet(prev[i:i + 12], cols=4, cell=420), 75))
        else:
            for name, img in prev[:6]:
                out.append(image(img, 85))
    return out


NAME_MAP = {'type': 'object', 'additionalProperties': {'type': 'number'}}
TOOLS = [
    ('ordner_sichten', t_sichten, True,
     'Bilder eines Ordners sichten: EXIF (Kamera, Brennweite, Blende, Zeit, ISO, Aufnahmezeit), Schärfe '
     '(Laplace-Varianz und 98.-Perzentil der Blockvarianz, für Serienvergleich), Helligkeit, byte-gleiche Kopien, '
     'Serien (gleiche Sekunde und Brennweite) und ein Kontaktbogen. 24 Bilder je Seite. Unterordner final/ und '
     '_aussortiert/ werden nicht mitgezählt.',
     {'ordner': {'type': 'string', 'description': 'Ordner relativ zum Arbeitsordner, z. B. Salzburg'},
      'seite': {'type': 'integer', 'minimum': 1, 'default': 1}}, ['ordner']),
    ('vorschau', t_vorschau, True,
     'Vorschau mit Hilfslinien, bis zu 6 Bilder nebeneinander. Zum Prüfen der Schräglage: dasselbe Bild mit '
     'winkel 0 und einem Kandidatwinkel, bei Bedarf mit ausschnitt vergrößert. Winkel in Grad, gegen den '
     'Uhrzeigersinn positiv.',
     {'bilder': {'type': 'array', 'maxItems': 6, 'items': {'type': 'object', 'required': ['datei'], 'properties': {
         'datei': {'type': 'string'}, 'winkel': {'type': 'number', 'default': 0},
         'ausschnitt': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4,
                        'description': '[x0, y0, x1, y1] als Anteil 0..1 nach dem Drehen'},
         'linien': {'type': 'integer', 'default': 12, 'description': 'senkrechte Hilfslinien (0 = keine)'}}}},
      'hoehe': {'type': 'integer', 'default': 600}}, ['bilder']),
    ('neigung_messen', t_neigung, True,
     'Schräglage je Bild schätzen (Senkrechte mit Korrektur stürzender Linien, sonst Horizont) und Hauptgesichter '
     'zählen. Ergebnis ist ein Vorschlag: mit vorschau prüfen, bevor er in optimieren als winkel landet.',
     {'dateien': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Dateien oder Ordner'}}, ['dateien']),
    ('aussortieren', t_aussortieren, False,
     'Bilder in einen Unterordner verschieben (Standard _aussortiert neben dem Bild). Löscht nie, überschreibt '
     'nie: vorhandene Ziele werden übersprungen.',
     {'dateien': {'type': 'array', 'items': {'type': 'string'}},
      'ziel': {'type': 'string', 'default': '_aussortiert'}}, ['dateien']),
    ('optimieren', t_optimieren, False,
     'Startet einen Hintergrundjob: Tonwert, Entrauschen (ab ISO 400), Schärfen, Begradigen, motivgerechter '
     'Zuschnitt (Hauptpersonen mittig, Augen auf dem oberen Drittel, passendes Seitenverhältnis), optionale '
     'Effekte und Hautretusche. Schreibt <name>_final.jpg (+ _<effekt>.jpg, _retusche.jpg) in ausgabe '
     '(Standard final/ neben dem Bild). Originale bleiben unverändert. Die Schlüssel von winkel, format, mitte, '
     'effekte sind Dateinamen ohne Endung. Etwa 1 bis 2 Minuten je 20-MP-Bild auf einem Raspberry Pi 4.',
     {'dateien': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Dateien oder Ordner'},
      'ausgabe': {'type': 'string', 'default': 'final'},
      'winkel': dict(NAME_MAP, description='Grad gegen den Uhrzeigersinn; fehlt ein Bild, wird gemessen'),
      'format': {'type': 'object', 'additionalProperties': {'type': 'string', 'enum': ['original'] + list(fl.ASPECTS)},
                 'description': 'Seitenverhältnis erzwingen, original = nur Drehränder entfernen'},
      'mitte': dict(NAME_MAP, description='waagrechte Motivmitte 0..1, wenn kein Gesicht erkannt wird'),
      'effekte': {'type': 'object', 'additionalProperties': {'type': 'array', 'items': {
          'type': 'string', 'enum': ['bw', 'film', 'glow', 'clarity']}}},
      'retusche': {'description': 'true = alle Bilder mit Gesicht, oder Liste von Namen',
                   'anyOf': [{'type': 'boolean'}, {'type': 'array', 'items': {'type': 'string'}}]},
      'retusche_staerke': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': 1}}, ['dateien']),
    ('retusche', t_retusche, False,
     'Startet einen Hintergrundjob für dezente Hautretusche: Gesichter mit 478 Punkten finden, Pickel und kleine '
     'Flecken entfernen, Rötungen um 40 % mindern, Haut minimal glätten (Poren bleiben). Augen, Brauen, Lippen, '
     'Bart und Haare bleiben unberührt. Schreibt <name>_retusche.jpg (Standard: neben das Bild).',
     {'dateien': {'type': 'array', 'items': {'type': 'string'}},
      'ausgabe': {'type': 'string'}, 'staerke': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': 1}},
     ['dateien']),
    ('job_status', t_job, True,
     'Stand eines Jobs (ohne job_id: Liste der Jobs). Wenn fertig: Ergebnisse je Bild und Vorschauen '
     '(Zuschnitt mit Drittel- und Mittellinie bzw. vorher/nachher je Gesicht).',
     {'job_id': {'type': 'string'}, 'vorschau': {'type': 'boolean', 'default': True}}, []),
]
TOOL_FN = {t[0]: t[1] for t in TOOLS}


def tool_list():
    return [{'name': n, 'description': d, 'annotations': {'readOnlyHint': ro, 'destructiveHint': False},
             'inputSchema': {'type': 'object', 'properties': props, 'required': req}}
            for n, _, ro, d, props, req in TOOLS]


# ---------- JSON-RPC ----------
def send(msg):
    with OUT_LOCK:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + '\n'); sys.stdout.flush()


def handle(msg):
    mid = msg.get('id'); method = msg.get('method')
    if mid is None:
        return  # Benachrichtigung
    try:
        if method == 'initialize':
            want = (msg.get('params') or {}).get('protocolVersion')
            res = {'protocolVersion': want if want in PROTOCOLS else PROTOCOLS[0],
                   'capabilities': {'tools': {'listChanged': False}},
                   'serverInfo': {'name': 'foto-mcp', 'version': VERSION},
                   'instructions': 'Fotos im Arbeitsordner sichten, begradigen, zuschneiden, retuschieren. '
                                   'Pfade relativ zum Arbeitsordner. Lange Arbeiten laufen als Job: job_status abfragen.'}
        elif method == 'ping':
            res = {}
        elif method == 'tools/list':
            res = {'tools': tool_list()}
        elif method == 'tools/call':
            p = msg.get('params') or {}
            fn = TOOL_FN.get(p.get('name'))
            if not fn:
                send({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32602, 'message': f"unbekanntes Tool {p.get('name')}"}})
                return
            try:
                res = {'content': fn(p.get('arguments') or {}), 'isError': False}
            except ToolError as e:
                res = {'content': [text(f'Fehler: {e}')], 'isError': True}
            except Exception as e:
                log(traceback.format_exc())
                res = {'content': [text(f'Fehler: {type(e).__name__}: {e}')], 'isError': True}
        else:
            send({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'unbekannte Methode {method}'}})
            return
        send({'jsonrpc': '2.0', 'id': mid, 'result': res})
    except Exception as e:
        log(traceback.format_exc())
        send({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32603, 'message': str(e)}})


def main():
    global ROOT
    ap = argparse.ArgumentParser(); ap.add_argument('--root', required=True)
    a = ap.parse_args()
    ROOT = os.path.realpath(a.root)
    if not os.path.isdir(ROOT):
        sys.exit(f'Arbeitsordner fehlt: {ROOT}')
    threading.Thread(target=worker, daemon=True).start()
    log(f'Foto MCP {VERSION} auf stdio, Arbeitsordner {ROOT}')
    # Anfragen nebenläufig bearbeiten, damit job_status nicht hinter einer langen Sichtung wartet
    for line in sys.stdin:  # endet, wenn der Proxy die Verbindung schließt
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'ungültiges JSON'}})
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            threading.Thread(target=handle, args=(m,), daemon=True).start()
    fl._close_landmarker()
    sys.stdout.flush()
    os._exit(0)


if __name__ == '__main__':
    main()
