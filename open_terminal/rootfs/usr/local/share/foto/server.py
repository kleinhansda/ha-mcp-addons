#!/usr/bin/env python3
"""Foto MCP: MCP-Server (stdio, JSON-RPC) für Fotos im Arbeitsordner.

  server.py --root /share/artcraft/work

Werkzeuge: sichten, Vorschau mit Hilfslinien, Schräglage und Bildtyp messen, aussortieren
(verschieben), optimieren, anpassen und retuschieren als Hintergrundjob, Rezepte, Jobstatus mit
Protokoll. Alle Pfade relativ zum Arbeitsordner, Zugriffe außerhalb werden abgelehnt. Originale
werden nie überschrieben und nie gelöscht.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import traceback
import uuid
from collections import Counter, OrderedDict

import cv2
import numpy as np

import fotolib as fl
import szene as sz

VERSION = os.environ.get('FOTO_VERSION', 'dev')
PROTOCOLS = ('2025-06-18', '2025-03-26', '2024-11-05')
IMG_EXT = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp')
SKIP_DIRS = ('final', '_aussortiert')
REZEPT_DIR = 'rezepte'
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


# ---------- Rezepte und Regler ----------
def pruefe_look(p, wo='anpassen') -> dict:
    """Regler -100..100 global und je Bereich. Wirft ToolError bei Unbekanntem."""
    if p is None:
        return {}
    if not isinstance(p, dict):
        raise ToolError(f'{wo}: Objekt erwartet')
    out = {}
    for k, v in p.items():
        if k in fl.REGLER:
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not -100 <= v <= 100:
                raise ToolError(f'{wo}.{k}: Zahl von -100 bis 100 erwartet')
            out[k] = float(v)
        elif k in fl.BEREICHE:
            out[k] = pruefe_look(v, f'{wo}.{k}')
            if any(isinstance(x, dict) for x in out[k].values()):
                raise ToolError(f'{wo}.{k}: Bereiche lassen sich nicht schachteln')
        else:
            raise ToolError(f"{wo}: unbekannter Regler oder Bereich {k} (Regler: {', '.join(fl.REGLER)}; "
                            f"Bereiche: {', '.join(fl.BEREICHE)})")
    return out


def pruefe_effekte(e, wo='effekte') -> list:
    if e is None:
        return []
    if isinstance(e, str):
        e = [e]
    if not isinstance(e, list) or any(x not in fl.EFFEKTE for x in e):
        raise ToolError(f"{wo}: Liste aus {', '.join(fl.EFFEKTE)}")
    return list(e)


def pruefe_rezept(r: dict) -> dict:
    if not isinstance(r, dict):
        raise ToolError('rezept: Objekt erwartet')
    bad = set(r) - {'anpassen', 'effekte', 'beschreibung'}
    if bad:
        raise ToolError(f"rezept: unbekannte Schlüssel {', '.join(sorted(bad))} (erlaubt: anpassen, effekte, beschreibung)")
    out = {'anpassen': pruefe_look(r.get('anpassen'), 'rezept.anpassen'),
           'effekte': pruefe_effekte(r.get('effekte'), 'rezept.effekte')}
    if r.get('beschreibung'):
        out['beschreibung'] = str(r['beschreibung'])[:300]
    return out


def rezept_pfad(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
        raise ToolError('Rezeptname: Buchstaben, Ziffern, _ und -, bis 64 Zeichen')
    return os.path.join(ROOT, REZEPT_DIR, name + '.json')


def lade_rezept(r) -> tuple[dict, str | None]:
    """rezept als Name (Datei in rezepte/) oder Objekt. Liefert (rezept, name)."""
    if r is None:
        return {'anpassen': {}, 'effekte': []}, None
    if isinstance(r, str):
        p = rezept_pfad(r)
        if not os.path.isfile(p):
            raise ToolError(f'Rezept {r} nicht gefunden (rezepte zeigt alle)')
        with open(p, encoding='utf-8') as f:
            return pruefe_rezept(json.load(f)), r
    return pruefe_rezept(r), 'eigenes'


def pruefe_vorgaben(prm: dict, files: list[str]):
    """Fehler in Vorgaben sofort melden, nicht erst im Job: Regler, Effekte, Bildnamen."""
    namen = {stem(f) for f in files} | {stem(f).replace('_final', '') for f in files}
    arg = prm.get('anpassen')
    if arg and isinstance(arg, dict) and not any(k in fl.REGLER or k in fl.BEREICHE for k in arg):
        fremd = sorted(set(arg) - namen)
        if fremd:
            raise ToolError(f"anpassen: {', '.join(fremd)} ist weder Regler noch Bereich noch Bildname "
                            f"(Regler: {', '.join(fl.REGLER)}; Bereiche: {', '.join(fl.BEREICHE)})")
    for f in files:
        look_fuer(arg, stem(f)); pruefe_effekte(by_stem(prm.get('effekte'), stem(f), []))


def look_fuer(arg, name: str):
    """anpassen-Argument: global ({'struktur': 20}) oder je Bild ({'DSC01': {...}})."""
    if not arg:
        return {}
    if not isinstance(arg, dict):
        raise ToolError('anpassen: Objekt erwartet')
    if any(k in fl.REGLER or k in fl.BEREICHE for k in arg):
        return pruefe_look(arg)
    return pruefe_look(by_stem(arg, name), f'anpassen.{name}')


def mische(*looks) -> dict:
    """Spätere Looks überschreiben frühere, Bereiche werden zusammengeführt."""
    out: dict = {}
    for lk in looks:
        for k, v in (lk or {}).items():
            if isinstance(v, dict):
                out[k] = {**out.get(k, {}), **v}
            else:
                out[k] = v
    return {k: v for k, v in out.items() if (v if not isinstance(v, dict) else any(v.values()))}


def look_text(lk: dict) -> str:
    if not lk:
        return 'keine'
    teile = [f'{k} {v:+.0f}' for k, v in lk.items() if not isinstance(v, dict)]
    teile += [f"{k}: " + ', '.join(f'{a} {b:+.0f}' for a, b in v.items()) for k, v in lk.items() if isinstance(v, dict)]
    return '; '.join(teile)


# ---------- Szene ----------
def klein(rgb, seite: int = 2000):
    """Verkleinerte Kopie für die Szenenanalyse und den Maßstab (klein / groß)."""
    s = min(1.0, seite / max(rgb.shape[:2]))
    return (cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else rgb), s


def analyse(u8, gesichter=None, fs=None, skala: float = 1.0) -> dict:
    """Objekte, Szenenhinweise, Bereiche, Horizont und Bildtyp eines (gedrehten) Bildes.
    Analysiert wird das unbearbeitete Bild (vor Tonwert und Schärfen), damit Sichtung, Messung und
    Optimierung dasselbe sehen. skala: u8 ist um diesen Faktor verkleinert; Boxen kommen in
    Pixeln des großen Bildes zurück. gesichter: Zahl der Hauptgesichter, wenn schon bekannt."""
    hin = sz.hinweise(u8)
    objs = sz.tiere_korrigieren(sz.objekte(u8), hin)
    if skala != 1.0:
        objs = [dict(o, box=[round(v / skala) for v in o['box']]) for o in objs]
    ber = sz.bereiche(u8, hin.get('gruppen', {}).get('wasser', 0))
    hz = sz.horizont(u8, ber); ber['_horizont'] = hz
    if gesichter is None:
        gesichter = len(fl.main_faces(fs)) if fs is not None else 0
    return dict(hin=hin, objs=objs, ber=ber, hz=hz, gesichter=gesichter)


def bildtyp_von(shape, a: dict, senkrecht: float = 0.0) -> dict:
    return sz.bildtyp(shape, a['gesichter'], a['objs'], a['ber'], a['hin'], senkrecht)


def erkannt_text(a: dict, typ: dict) -> str:
    c = Counter(o['klasse'] for o in a['objs'])
    obj = ', '.join(f'{k} ×{v}' for k, v in c.most_common(6)) or 'keine Objekte'
    an = a['ber']['anteil']
    top = (a['hin'] or {}).get('top') or []
    sc = f"; Szene: {top[0][0]} {top[0][1]:.0%}" if top else ''
    return (f"{a['gesichter']} Hauptgesicht(er), {obj}; Himmel {an['himmel']:.0%}, Grün {an['gruen']:.0%}, "
            f"Wasser {an['wasser']:.0%}{sc}")


def motiv_boxen(typ: str, shape, a: dict, fs: list, box_baum=None) -> tuple[list, list]:
    """(Personenboxen, Motivboxen) in Pixeln eines Bildes der Größe shape."""
    H, W = shape[:2]
    pers = [o['box'] for o in sz.hauptpersonen(a['objs'], shape)]
    for b in fl.person_boxes(fs, shape):  # Gesichter ohne erkannte Person (z. B. abgeschnitten)
        cx = (b[0] + b[2]) / 2
        if not any(p[0] <= cx <= p[2] for p in pers):
            pers.append(list(b))
    mot = list(pers) + [o['box'] for o in sz.haupttiere(a['objs'], shape)]
    if typ == 'baum' and box_baum:
        mot.append([box_baum[0] * W, box_baum[1] * H, box_baum[2] * W, box_baum[3] * H])
    return pers, mot


def subjekt_aus_boxen(fs, boxen, shape):
    """Motivbereich für best_crop: Gesichter wie bisher, dazu Boxen von Personen, Tieren, Baum."""
    h, w = shape[:2]
    subj = fl.subject_box(shape, fs) if fs else None
    if not boxen:
        return subj
    x0 = min(b[0] for b in boxen); x1 = max(b[2] for b in boxen)
    y0 = min(b[1] for b in boxen); y1 = max(b[3] for b in boxen)
    m = 0.06 * (x1 - x0)
    if subj is None:
        return dict(x0=max(0.0, x0 - m), x1=min(float(w), x1 + m), y0=max(0.0, y0 - 0.04 * (y1 - y0)), y1=float(h),
                    cx=(x0 + x1) / 2, eyes=y0 + 0.22 * (y1 - y0), ganz=True)
    subj = dict(subj)
    subj['x0'] = max(0.0, min(subj['x0'], x0 - m)); subj['x1'] = min(float(w), max(subj['x1'], x1 + m))
    subj['y0'] = max(0.0, min(subj['y0'], y0)); subj['cx'] = (subj['x0'] + subj['x1']) / 2
    return subj


def horizont_crop(w, h, deg, y_rel, ber):
    """Originalformat, Höhe bis auf 85 % kürzen, damit der Horizont auf ein Drittel fällt:
    mehr Himmel als Wasser/Land -> unteres Drittel, sonst oberes Drittel."""
    base = fl.best_crop(w, h, deg, None)
    an = ber['anteil']; ziel = 2 / 3 if an['himmel'] > an['wasser'] + an['gruen'] else 1 / 3
    hy = y_rel * h
    if abs((hy - base['y']) / base['h'] - ziel) < 0.03:
        return dict(base, format='original (Horizont liegt schon auf dem Drittel)')
    for k in (0.95, 0.9, 0.85):
        ch = base['h'] * k; y = hy - ziel * ch
        if base['y'] <= y and y + ch <= base['y'] + base['h']:
            return dict(base, y=y, h=ch, format=f'horizont-drittel ({k:.0%} Höhe)')
    return dict(base, format='original (Horizont zu nah am Rand für ein Drittel)')


# ---------- Protokoll ----------
def schritt(P: list, name: str, txt: str, **daten):
    P.append({'schritt': name, 'text': txt, **({'daten': daten} if daten else {})})


def protokoll_md(job: dict, auswahl=None) -> str:
    z = [f"# Protokoll {job['art']} {job['id']}", '',
         f"Foto MCP {VERSION}, gestartet {job.get('gestartet_datum', '')} {job.get('gestartet') or ''}, "
         f"fertig {job.get('fertig') or '–'}.", '']
    pr = {k: v for k, v in job['_params'].items() if k not in ('_rezept',)}
    if pr:
        z += ['Vorgaben: `' + json.dumps(pr, ensure_ascii=False) + '`', '']
    for e in job['ergebnisse']:
        if auswahl is not None and e.get('_dir') != auswahl:
            continue
        z.append(f"## {e.get('quelle_datei', e.get('bild'))}")
        for s in e.get('protokoll', []):
            z.append(f"- **{s['schritt']}:** {s['text']}")
        z.append('')
    for f in job['fehler']:
        z += [f"## {f['datei']}", f"- **Fehler:** {f['fehler']}", '']
    return '\n'.join(z)


def protokoll_schreiben(job: dict):
    dirs = sorted({e['_dir'] for e in job['ergebnisse'] if e.get('_dir')})
    ts = time.strftime('%Y%m%d-%H%M%S')
    for d in dirs:
        p = os.path.join(d, f"protokoll_{ts}_{job['id']}.md")
        try:
            with open(p, 'w', encoding='utf-8') as f:
                f.write(protokoll_md(job, d))
            job['protokoll_dateien'].append(rel(p))
        except OSError as e:
            log(f'Protokoll nicht geschrieben: {p}: {e}')


# ---------- Jobs ----------
JOBS: OrderedDict[str, dict] = OrderedDict()
QUEUE: queue.Queue = queue.Queue()


def new_job(kind: str, files: list[str], params: dict) -> dict:
    jid = uuid.uuid4().hex[:8]
    job = dict(id=jid, art=kind, status='wartet', fortschritt=f'0/{len(files)}', dateien=[rel(f) for f in files],
               ergebnisse=[], fehler=[], vorschau=[], protokoll_dateien=[], gestartet=None, fertig=None,
               gestartet_datum=time.strftime('%Y-%m-%d'), _files=files, _params=params)
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
        fn = {'optimieren': do_optimize, 'retusche': do_retouch, 'anpassen': do_anpassen}[job['art']]
        for i, f in enumerate(job['_files']):
            try:
                res, prev = fn(f, job['_params'])
                job['ergebnisse'].append(res)
                if prev is not None:
                    job['vorschau'].append((stem(f), prev))
            except Exception as e:  # ein Bild darf den Job nicht abbrechen
                log(traceback.format_exc())
                job['fehler'].append({'datei': rel(f), 'fehler': str(e)})
            job['fortschritt'] = f'{i + 1}/{len(job["_files"])}'
        job['fertig'] = time.strftime('%H:%M:%S')
        protokoll_schreiben(job)
        job['status'] = 'fertig'


def effekte_schreiben(g, name, d, effs, ctx, exif, icc, P, outs):
    for e in effs:
        p = os.path.join(d, f'{name}_{e}.jpg'); fl.save_jpg(fl.effect(g, e, ctx), p, exif, icc); outs.append(rel(p))
    if effs:
        schritt(P, 'Effekte', ', '.join(f'{e} → {name}_{e}.jpg' for e in effs) + ' (zusätzlich zur normalen Fassung)')


def do_optimize(src: str, prm: dict):
    name = stem(src); P: list = []
    d = out_dir(src, prm.get('ausgabe', 'final'))
    rgb, exif, icc = fl.load(src)
    iso = fl.iso_of(exif); H0, W0 = rgb.shape[:2]
    schritt(P, 'Laden', f'{W0}×{H0} px, ISO {iso}, nach EXIF gedreht')
    k0, ks = klein(rgb)  # unbearbeitet, für die Szenenanalyse
    f = rgb.astype(np.float32) / 255; del rgb
    it, idn = {}, {}
    f = fl.auto_tone(f, info=it)
    schritt(P, 'Tonwert', f"Schwarzpunkt {it['schwarzpunkt']:.3f}, Weißpunkt {it['weisspunkt']:.3f}, "
                          f"Lichter über die Basisebene um bis zu {it['lichter']:.0%} gesenkt; kein Weißabgleich", **it)
    f = fl.denoise(f, iso, idn)
    schritt(P, 'Entrauschen', 'aus (ISO unter 400)' if not idn['farbe'] else
            f"Farbe (a/b) Stärke {idn['farbe']}" + (', Helligkeit halb' if idn['helligkeit'] else ', Helligkeit unverändert'), **idn)
    amount = 0.5 if iso >= 400 else 0.6
    f = fl.usm(f, amount)
    schritt(P, 'Schärfen', f'Unscharf maskieren {amount}, Radius 1,2 px, mit Schwelle (glatte Flächen bleiben glatt)')

    regeln = prm.get('regeln', True) is not False
    u8 = (f * 255).astype(np.uint8)
    fs_all = fl.faces(u8)
    a0 = analyse(k0, gesichter=len(fl.main_faces(fs_all)), skala=ks)
    wk = by_stem(prm.get('winkel'), name)
    if wk is None:
        people = fl.person_boxes(fs_all, u8.shape) + [o['box'] for o in a0['objs'] if o['klasse'] == 'person']
        deg, quelle, gewicht = fl.tilt(u8, people, a0['hz'])
        roh = deg
        deg = deg if 0.3 <= abs(deg) <= 6 else 0.0
        hz = a0['hz']
        wie = {'horizont': f"Horizont ({'Himmelsgrenze' if hz and hz['linie'] == 'himmel' else 'Uferlinie'}, "
                           f"{hz['abdeckung']:.0%} der Breite)" if hz else 'Horizont',
               'senkrecht': 'senkrechte Kanten (stürzende Linien herausgerechnet)',
               'waagrecht': 'waagrechte Linien'}.get(quelle, 'kein Bezug gefunden')
        if quelle == 'senkrecht' and hz:
            wie += f"; Horizont-Kandidat {hz['winkel']:+.2f}° verworfen (widerspricht den Senkrechten)"
        if deg:
            txt = f'{deg:+.2f}° gedreht, gemessen an {wie}'
        elif roh:
            txt = f'nicht gedreht: {wie} ergibt {roh:+.2f}° (unter 0,3° oder über 6°)'
        else:
            txt = 'nicht gedreht: ' + (f'{wie} ergibt 0°' if quelle else 'kein Bezug gefunden')
        schritt(P, 'Schräglage', txt, winkel=deg, gemessen=roh, quelle=quelle, horizont=hz)
    else:
        deg, quelle, gewicht = float(wk), 'vorgegeben', 0.0
        schritt(P, 'Schräglage', f'{deg:+.2f}° vorgegeben', winkel=deg, quelle=quelle)
    g = fl.rotate(f, deg); del f, u8
    h, w = g.shape[:2]
    u8 = (g * 255).astype(np.uint8)
    kr = fl.rotate(k0, deg) if deg else k0
    a = analyse(kr, gesichter=a0['gesichter'], skala=ks) if deg else a0
    vorgabe_typ = by_stem(prm.get('typ'), name)
    if vorgabe_typ:
        if vorgabe_typ not in sz.REGELN:
            raise ToolError(f"unbekannter Bildtyp {vorgabe_typ} ({', '.join(sz.TYPEN)})")
        typ = dict(typ=vorgabe_typ, begruendung='vorgegeben')
    else:
        typ = bildtyp_von(g.shape, a, gewicht if quelle == 'senkrecht' else 0.0)
    regel = sz.REGELN[typ['typ']] if regeln else None
    schritt(P, 'Erkannt', erkannt_text(a, typ), objekte=a['objs'], anteile=a['ber']['anteil'],
            szene=(a['hin'] or {}).get('top'))
    schritt(P, 'Bildtyp', f"{typ['typ']} ({typ['begruendung']})" + ('' if regeln else '; Regeln ausgeschaltet'),
            typ=typ['typ'])

    forced = by_stem(prm.get('format'), name)
    if forced and forced != 'original' and forced not in fl.ASPECTS:
        raise ToolError(f'unbekanntes Format {forced}')
    art = 'vorgabe' if forced else (regel['zuschnitt'] if regel else 'motiv')
    fs = fl.main_faces(fl.faces(u8)) if art in ('motiv', 'vorgabe') and forced != 'original' else []
    pers, mot = motiv_boxen(typ['typ'], g.shape, a, fs, typ.get('box')) if (art in ('motiv', 'vorgabe') or regel) else ([], [])
    subj = None
    if art in ('motiv', 'vorgabe') and forced != 'original':
        subj = subjekt_aus_boxen(fs, mot if regel or not fs else [], g.shape)
    mitte = by_stem(prm.get('mitte'), name)
    if mitte is not None and (subj is None or not fs):
        cx = float(mitte) * w
        subj = dict(x0=cx - 0.06 * w, x1=cx + 0.06 * w, y0=0.0, y1=float(h), cx=cx, eyes=0.33 * h, ganz=True)
    if art == 'horizont' and a['hz'] and not forced:
        crop = horizont_crop(w, h, deg, a['hz']['y'], a['ber'])
    else:
        crop = fl.best_crop(w, h, deg, subj, forced)
    grund = {'vorgabe': f'Format {forced} vorgegeben', 'motiv': 'Motiv im Ausschnitt' if subj else 'kein Motiv erkannt',
             'horizont': 'Horizont auf ein Drittel' if a['hz'] else 'kein Horizont, Originalformat',
             'original': 'Originalformat, nur Drehränder entfernt'}[art]
    if mitte is not None and (subj is not None and not fs):
        grund += f', Motivmitte {float(mitte):.2f} vorgegeben'
    prev = fl.grid_preview(u8, 0, crop, lines=8, max_side=900, label=f"{name} {typ['typ']} {crop['format']} {deg:+.2f}")
    x, y, cw, ch = (int(round(v)) for v in (crop['x'], crop['y'], crop['w'], crop['h']))
    schritt(P, 'Zuschnitt', f"{crop['format']}, {cw}×{ch} px ab ({x}, {y}); {grund}"
            + (f", Motivanteil {crop['motivanteil']:.2f}" if crop.get('motivanteil') else '')
            + (f" (Regel {typ['typ']})" if regel and not forced else ''), box=[x, y, cw, ch], format=crop['format'])
    g = g[y:y + ch, x:x + cw]; del u8
    kc = kr[int(y * ks):int((y + ch) * ks), int(x * ks):int((x + cw) * ks)]

    rez, rez_name = prm.get('_rezept') or ({'anpassen': {}, 'effekte': []}, None)
    eigen = look_fuer(prm.get('anpassen'), name)
    look = mische(regel['look'] if regel else {}, rez['anpassen'], eigen)
    herkunft = [t for t, lk in ((f"Regel {typ['typ']}", regel['look'] if regel else {}),
                                (f'Rezept {rez_name}', rez['anpassen']), ('Vorgabe', eigen)) if lk]
    effs = list(dict.fromkeys(rez['effekte'] + pruefe_effekte(by_stem(prm.get('effekte'), name, []))))
    ctx = None
    if any(isinstance(v, dict) for v in look.values()) or 'lens_blur' in effs:
        ac = analyse(kc, gesichter=a['gesichter'], skala=ks)
        sh = np.array([x, y, x, y], np.float32)
        pb = [list(np.array(b, np.float32) - sh) for b in pers]; mb = [list(np.array(b, np.float32) - sh) for b in mot]
        pb = pb or [o['box'] for o in sz.hauptpersonen(ac['objs'], g.shape)]
        ctx = sz.masken(kc, ac['ber'], pb, mb or pb, breite=cw)
    if look:
        g = fl.anpassen(g, look, ctx)
    schritt(P, 'Look', look_text(look) + (f" ({' < '.join(herkunft)})" if herkunft else ''), regler=look)
    outs = []
    p = os.path.join(d, f'{name}_final.jpg'); fl.save_jpg(g, p, exif, icc); outs.append(rel(p))
    schritt(P, 'Gespeichert', f'{rel(p)} (JPEG 92, EXIF und Farbprofil übernommen)')
    effekte_schreiben(g, name, d, effs, ctx, exif, icc, P, outs)
    ret = prm.get('retusche')
    if ret is None:
        ret = bool(regel and regel['retusche'])
        ret_grund = f"Regel {typ['typ']}" if ret else ''
    else:
        ret_grund = 'vorgegeben'
    if ret is True or (isinstance(ret, list) and name in ret):
        rimg = (g * 255).astype(np.uint8); rf = fl.main_faces(fl.faces(rimg))
        if rf:
            r, info = fl.retouch(rimg, rf, float(prm.get('retusche_staerke', 1.0)))
            p = os.path.join(d, f'{name}_retusche.jpg'); fl.save_jpg(r, p, exif, icc); outs.append(rel(p))
            schritt(P, 'Retusche', f"{len(rf)} Gesicht(er), {sum(i['flecken'] for i in info)} Flecken, Stärke "
                                  f"{float(prm.get('retusche_staerke', 1.0)):.1f} ({ret_grund}) → {os.path.basename(p)}")
        else:
            schritt(P, 'Retusche', f'kein Gesicht im Ausschnitt, nichts geschrieben ({ret_grund})')
    return dict(bild=name, quelle_datei=rel(src), typ=typ['typ'], winkel=round(deg, 2), quelle=quelle,
                gesichter=len(fs), format=crop['format'], motivanteil=crop.get('motivanteil'), groesse=[cw, ch],
                look=look, dateien=outs, protokoll=P, _dir=d), prev


def do_anpassen(src: str, prm: dict):
    name = stem(src); P: list = []
    d = out_dir(src, prm.get('ausgabe'))
    suffix = prm.get('suffix') or 'angepasst'
    rgb, exif, icc = fl.load(src)
    schritt(P, 'Laden', f'{rgb.shape[1]}×{rgb.shape[0]} px (kein Tonwert, keine Drehung, kein Zuschnitt)')
    rez, rez_name = prm.get('_rezept') or ({'anpassen': {}, 'effekte': []}, None)
    eigen = look_fuer(prm.get('anpassen'), name)
    look = mische(rez['anpassen'], eigen)
    effs = list(dict.fromkeys(rez['effekte'] + pruefe_effekte(by_stem(prm.get('effekte'), name, []))))
    if not look and not effs:
        raise ToolError('nichts zu tun: anpassen, rezept oder effekte angeben')
    ctx = None
    if any(isinstance(v, dict) for v in look.values()) or 'lens_blur' in effs:
        fs = fl.main_faces(fl.faces(rgb)) if any(k in look for k in ('person', 'motiv', 'hintergrund')) or 'lens_blur' in effs else []
        kl, ks = klein(rgb)
        a = analyse(kl, fs=fs, skala=ks)
        typ = bildtyp_von(rgb.shape, a)
        pers, mot = motiv_boxen(typ['typ'], rgb.shape, a, fs, typ.get('box'))
        ctx = sz.masken(kl, a['ber'], pers, mot or pers, breite=rgb.shape[1])
        schritt(P, 'Erkannt', erkannt_text(a, typ) + f"; Bildtyp {typ['typ']}")
    g = rgb.astype(np.float32) / 255; del rgb
    if look:
        g = fl.anpassen(g, look, ctx)
    herkunft = [t for t, lk in ((f'Rezept {rez_name}', rez['anpassen']), ('Vorgabe', eigen)) if lk]
    schritt(P, 'Look', look_text(look) + (f" ({' < '.join(herkunft)})" if herkunft else ''), regler=look)
    outs = []
    if look:
        p = os.path.join(d, f'{name}_{suffix}.jpg')
        if os.path.realpath(p) == os.path.realpath(src):
            raise ToolError('Ausgabe wäre die Quelldatei')
        fl.save_jpg(g, p, exif, icc); outs.append(rel(p))
        schritt(P, 'Gespeichert', rel(p))
    effekte_schreiben(g, name, d, effs, ctx, exif, icc, P, outs)
    prev = fl.contact_sheet([(name, (g * 255).astype(np.uint8))], cols=1, cell=600)
    return dict(bild=name, quelle_datei=rel(src), look=look, effekte=effs, dateien=outs, protokoll=P, _dir=d), prev


def do_retouch(src: str, prm: dict):
    name = stem(src).replace('_final', ''); P: list = []
    d = out_dir(src, prm.get('ausgabe'))
    rgb, exif, icc = fl.load(src)
    fs = fl.main_faces(fl.faces(rgb))
    if not fs:
        schritt(P, 'Retusche', 'kein Gesicht gefunden, nichts geschrieben')
        return dict(bild=name, quelle_datei=rel(src), gesichter=0, hinweis='kein Gesicht gefunden, nichts geschrieben',
                    protokoll=P, _dir=d), None
    st = float(prm.get('staerke', 1.0))
    res, info = fl.retouch(rgb, fs, st)
    p = os.path.join(d, f'{name}_retusche.jpg')
    if os.path.realpath(p) == os.path.realpath(src):
        raise ToolError('Ausgabe wäre das Original')
    fl.save_jpg(res, p, exif, icc)
    schritt(P, 'Retusche', f"{len(fs)} Gesicht(er), {sum(i['flecken'] for i in info)} Flecken entfernt, Rötung "
                          f"−{0.4 * st:.0%}, Haut minimal geglättet (Stärke {st:.1f}) → {rel(p)}")
    tiles = []
    for pts in fs[:2]:
        fw = np.ptp(pts[:, 0]); x0, y0 = np.maximum(pts.min(0) - fw * 0.15, 0).astype(int)
        x1, y1 = np.minimum(pts.max(0) + fw * 0.15, rgb.shape[1::-1]).astype(int)
        tiles += [rgb[y0:y1, x0:x1], res[y0:y1, x0:x1]]
    return dict(bild=name, quelle_datei=rel(src), gesichter=len(fs), details=info, datei=rel(p), protokoll=P,
                _dir=d), fl.side_by_side(tiles, 420)


# ---------- Werkzeuge ----------
def t_sichten(a):
    folder = resolve(a.get('ordner', ''))
    if not os.path.isdir(folder):
        raise ToolError('ordner ist kein Ordner')
    files = list_images(folder)
    seite = max(1, int(a.get('seite', 1))); pro = 24
    erkennen = a.get('erkennen', True) is not False
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
        if erkennen:  # ohne Gesichtssuche (schnell); Personen kommen aus der Objekterkennung
            an = analyse(rgb)
            t = bildtyp_von(rgb.shape, an)
            row['typ'] = t['typ']; row['typ_grund'] = t['begruendung']
        if f in dup:
            row['kopie_von'] = dup[f]
        rows.append(row); thumbs.append((os.path.basename(f) + (f" · {row['typ']}" if 'typ' in row else ''), rgb))
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
        kl, ks = klein(rgb)
        an = analyse(kl, gesichter=len(fl.main_faces(fs)), skala=ks)
        people = fl.person_boxes(fs, rgb.shape) + [o['box'] for o in an['objs'] if o['klasse'] == 'person']
        deg, quelle, wt = fl.tilt(rgb, people, an['hz'])
        t = bildtyp_von(rgb.shape, an, wt if quelle == 'senkrecht' else 0.0)
        c = Counter(o['klasse'] for o in an['objs'])
        out.append(dict(datei=rel(f), winkel=deg, quelle=quelle, gewicht=wt, horizont=an['hz'], gesichter=len(fs),
                        hauptgesichter=an['gesichter'], bildtyp=t['typ'], begruendung=t['begruendung'],
                        objekte=dict(c), anteile=an['ber']['anteil']))
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


def _rezept_param(a, prm):
    if a.get('rezept') is not None:
        prm['_rezept'] = lade_rezept(a['rezept'])


def t_optimieren(a):
    files = files_arg(a)
    prm = {k: a.get(k) for k in ('ausgabe', 'winkel', 'format', 'mitte', 'effekte', 'retusche', 'retusche_staerke',
                                 'typ', 'regeln', 'anpassen', 'rezept') if a.get(k) is not None}
    prm.setdefault('ausgabe', 'final')
    _rezept_param(a, prm)
    pruefe_vorgaben(prm, files)
    job = new_job('optimieren', files, prm)
    return [text(dict(job_id=job['id'], bilder=len(files),
                      hinweis='Fortschritt, Ergebnis und Protokoll mit job_status abfragen.'))]


def t_anpassen(a):
    files = files_arg(a)
    prm = {k: a.get(k) for k in ('ausgabe', 'anpassen', 'effekte', 'rezept', 'suffix') if a.get(k) is not None}
    if prm.get('suffix') and not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', prm['suffix']):
        raise ToolError('suffix: Buchstaben, Ziffern, _ und -')
    _rezept_param(a, prm)
    pruefe_vorgaben(prm, files)
    job = new_job('anpassen', files, prm)
    return [text(dict(job_id=job['id'], bilder=len(files),
                      hinweis='Fortschritt, Ergebnis und Protokoll mit job_status abfragen.'))]


def t_retusche(a):
    files = files_arg(a)
    prm = {k: a.get(k) for k in ('ausgabe', 'staerke') if a.get(k) is not None}
    job = new_job('retusche', files, prm)
    return [text(dict(job_id=job['id'], bilder=len(files), hinweis='Fortschritt und Ergebnis mit job_status abfragen.'))]


def t_rezept_speichern(a):
    name = a.get('name'); p = rezept_pfad(name)
    r = pruefe_rezept(a.get('rezept'))
    if os.path.exists(p) and not a.get('ueberschreiben'):
        raise ToolError(f'Rezept {name} gibt es schon (ueberschreiben: true ersetzt es)')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return [text(dict(gespeichert=rel(p), rezept=r))]


def t_rezepte(a):
    d = os.path.join(ROOT, REZEPT_DIR); out = []
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            if n.endswith('.json'):
                try:
                    with open(os.path.join(d, n), encoding='utf-8') as f:
                        out.append(dict(name=n[:-5], **pruefe_rezept(json.load(f))))
                except (OSError, ValueError, ToolError) as e:
                    out.append(dict(name=n[:-5], fehler=str(e)))
    return [text(dict(ordner=REZEPT_DIR, rezepte=out, regeln={k: v['look'] for k, v in sz.REGELN.items()}))]


def _oeffentlich(e: dict) -> dict:
    return {k: v for k, v in e.items() if not k.startswith('_') and k != 'protokoll'}


def t_job(a):
    jid = a.get('job_id')
    if not jid:
        return [text([{k: j[k] for k in ('id', 'art', 'status', 'fortschritt', 'gestartet', 'fertig')}
                      for j in JOBS.values()])]
    job = JOBS.get(jid)
    if not job:
        raise ToolError(f'Job {jid} unbekannt (nach Neustart des Add-ons sind Jobs weg)')
    pub = {k: v for k, v in job.items() if not k.startswith('_') and k not in ('vorschau', 'ergebnisse')}
    pub['ergebnisse'] = [_oeffentlich(e) for e in job['ergebnisse']]
    out = [text(pub)]
    if job['status'] == 'fertig':
        if a.get('protokoll', True):
            out.append(text(protokoll_md(job)))
        if a.get('vorschau', True) and job['vorschau']:
            prev = job['vorschau']
            if job['art'] in ('optimieren', 'anpassen'):
                for i in range(0, len(prev), 12):
                    out.append(image(fl.contact_sheet(prev[i:i + 12], cols=4, cell=420), 75))
            else:
                for name, img in prev[:6]:
                    out.append(image(img, 85))
    return out


NAME_MAP = {'type': 'object', 'additionalProperties': {'type': 'number'}}
LOOK = {'type': 'object', 'description':
        'Regler -100..100 wie in Snapseeds Feinabstimmung: ' + ', '.join(fl.REGLER) + '. Je Bereich als '
        'Unterobjekt: ' + ', '.join(fl.BEREICHE) + ', z. B. {"struktur": 20, "himmel": {"helligkeit": -15}}. '
        'Statt global auch je Bild: {"DSC01234": {...}}.'}
EFFEKT_MAP = {'type': 'object', 'additionalProperties': {'type': 'array', 'items': {'type': 'string', 'enum': list(fl.EFFEKTE)}},
              'description': 'je Bild (Dateiname ohne Endung) eine Liste von Effekten, jeder als eigene Datei'}
REZEPT = {'description': 'Name eines gespeicherten Rezepts (rezepte) oder ein Rezept-Objekt {anpassen, effekte}',
          'anyOf': [{'type': 'string'}, {'type': 'object'}]}
TOOLS = [
    ('ordner_sichten', t_sichten, True,
     'Bilder eines Ordners sichten: EXIF (Kamera, Brennweite, Blende, Zeit, ISO, Aufnahmezeit), Schärfe '
     '(Laplace-Varianz und 98.-Perzentil der Blockvarianz, für Serienvergleich), Helligkeit, Bildtyp mit '
     'Begründung (ohne Gesichtssuche), byte-gleiche Kopien, Serien (gleiche Sekunde und Brennweite) und ein '
     'Kontaktbogen. 24 Bilder je Seite. Unterordner final/ und _aussortiert/ werden nicht mitgezählt.',
     {'ordner': {'type': 'string', 'description': 'Ordner relativ zum Arbeitsordner, z. B. Salzburg'},
      'seite': {'type': 'integer', 'minimum': 1, 'default': 1},
      'erkennen': {'type': 'boolean', 'default': True, 'description': 'Bildtyp erkennen (etwas langsamer)'}},
     ['ordner']),
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
     'Schräglage je Bild schätzen und Bildtyp erkennen. Reihenfolge: echter Horizont (gerade Grenze Himmel/Land '
     'oder Uferlinie), dann senkrechte Kanten mit Korrektur stürzender Linien, zuletzt übrige Waagrechte. Linien '
     'von Personen zählen nicht. Dazu Bildtyp mit Begründung, Objekte und Flächenanteile. Ergebnis ist ein '
     'Vorschlag: mit vorschau prüfen, bevor er in optimieren als winkel landet.',
     {'dateien': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Dateien oder Ordner'}}, ['dateien']),
    ('aussortieren', t_aussortieren, False,
     'Bilder in einen Unterordner verschieben (Standard _aussortiert neben dem Bild). Löscht nie, überschreibt '
     'nie: vorhandene Ziele werden übersprungen.',
     {'dateien': {'type': 'array', 'items': {'type': 'string'}},
      'ziel': {'type': 'string', 'default': '_aussortiert'}}, ['dateien']),
    ('optimieren', t_optimieren, False,
     'Startet einen Hintergrundjob: Tonwert, Entrauschen (ab ISO 400), Schärfen, Begradigen, Bildtyp erkennen '
     '(' + ', '.join(sz.TYPEN) + ') und dessen Regel anwenden (Zuschnitt und dezenter Look, bei Porträts '
     'Retusche), danach Rezept und eigene Regler, optionale Effekte. Schreibt <name>_final.jpg (+ _<effekt>.jpg, '
     '_retusche.jpg) in ausgabe (Standard final/ neben dem Bild) und ein Protokoll protokoll_<zeit>_<job>.md. '
     'Originale bleiben unverändert. Die Schlüssel von winkel, format, mitte, typ, effekte sind Dateinamen ohne '
     'Endung. Reihenfolge der Looks: Regel < Rezept < anpassen.',
     {'dateien': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Dateien oder Ordner'},
      'ausgabe': {'type': 'string', 'default': 'final'},
      'winkel': dict(NAME_MAP, description='Grad gegen den Uhrzeigersinn; fehlt ein Bild, wird gemessen'),
      'format': {'type': 'object', 'additionalProperties': {'type': 'string', 'enum': ['original'] + list(fl.ASPECTS)},
                 'description': 'Seitenverhältnis erzwingen, original = nur Drehränder entfernen'},
      'mitte': dict(NAME_MAP, description='waagrechte Motivmitte 0..1, wenn kein Motiv erkannt wird'),
      'typ': {'type': 'object', 'additionalProperties': {'type': 'string', 'enum': list(sz.TYPEN)},
              'description': 'Bildtyp je Bild vorgeben statt erkennen'},
      'regeln': {'type': 'boolean', 'default': True,
                 'description': 'false = keine Regeln je Bildtyp (Zuschnitt nur nach Gesichtern, kein Look)'},
      'anpassen': LOOK, 'rezept': REZEPT, 'effekte': EFFEKT_MAP,
      'retusche': {'description': 'true = alle Bilder mit Gesicht, false = keine, Liste von Namen; ohne Angabe '
                                  'nach Regel (Porträt)',
                   'anyOf': [{'type': 'boolean'}, {'type': 'array', 'items': {'type': 'string'}}]},
      'retusche_staerke': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': 1}}, ['dateien']),
    ('anpassen', t_anpassen, False,
     'Startet einen Hintergrundjob, der nur Regler und Effekte anwendet, ohne Tonwert, Drehung und Zuschnitt, '
     'z. B. auf fertige _final.jpg. Regler wie in Snapseeds Feinabstimmung, auch je Bereich (Himmel, Grün, '
     'Wasser, Person, Motiv, Hintergrund). Schreibt <name>_<suffix>.jpg (Standard _angepasst) neben das Bild '
     'und ein Protokoll. Die Quelldatei wird nie überschrieben.',
     {'dateien': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Dateien oder Ordner'},
      'anpassen': LOOK, 'rezept': REZEPT, 'effekte': EFFEKT_MAP,
      'suffix': {'type': 'string', 'default': 'angepasst'}, 'ausgabe': {'type': 'string'}}, ['dateien']),
    ('rezept_speichern', t_rezept_speichern, False,
     'Einen Look als Rezept im Arbeitsordner speichern (rezepte/<name>.json), z. B. für eine ganze Serie. '
     'Ein vorhandenes Rezept wird nur mit ueberschreiben: true ersetzt.',
     {'name': {'type': 'string'}, 'rezept': {'type': 'object', 'description':
                                             '{"anpassen": {...Regler...}, "effekte": [...], "beschreibung": "..."}'},
      'ueberschreiben': {'type': 'boolean', 'default': False}}, ['name', 'rezept']),
    ('rezepte', t_rezepte, True,
     'Gespeicherte Rezepte und die eingebauten Looks je Bildtyp anzeigen.', {}, []),
    ('retusche', t_retusche, False,
     'Startet einen Hintergrundjob für dezente Hautretusche: Gesichter mit 478 Punkten finden, Pickel und kleine '
     'Flecken entfernen, Rötungen um 40 % mindern, Haut minimal glätten (Poren bleiben). Augen, Brauen, Lippen, '
     'Bart und Haare bleiben unberührt. Schreibt <name>_retusche.jpg (Standard: neben das Bild).',
     {'dateien': {'type': 'array', 'items': {'type': 'string'}},
      'ausgabe': {'type': 'string'}, 'staerke': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': 1}},
     ['dateien']),
    ('job_status', t_job, True,
     'Stand eines Jobs (ohne job_id: Liste der Jobs). Wenn fertig: Ergebnisse je Bild, Protokoll (wie jedes Bild '
     'bearbeitet wurde, auch als Datei neben den Ergebnissen) und Vorschauen (Zuschnitt mit Drittel- und '
     'Mittellinie bzw. vorher/nachher je Gesicht).',
     {'job_id': {'type': 'string'}, 'vorschau': {'type': 'boolean', 'default': True},
      'protokoll': {'type': 'boolean', 'default': True}}, []),
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
                   'instructions': 'Fotos im Arbeitsordner sichten, begradigen, zuschneiden, anpassen, retuschieren. '
                                   'Pfade relativ zum Arbeitsordner. Lange Arbeiten laufen als Job: job_status '
                                   'abfragen, dort steht auch das Protokoll.'}
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
    m = sz.modelle()
    log(f"Foto MCP {VERSION} auf stdio, Arbeitsordner {ROOT}, Objekterkennung {'an' if m['objekte'] else 'AUS'}, "
        f"Szenenerkennung {'an' if m['szene'] else 'AUS'}")
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
