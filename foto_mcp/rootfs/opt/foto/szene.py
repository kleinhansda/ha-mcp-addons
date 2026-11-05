"""Szenenerkennung von Foto MCP: Objekte, Szenenhinweise, Bereiche, Horizont, Bildtyp und Regeln.

- Objekte: NanoDet-Plus (COCO, 80 Klassen) aus dem OpenCV Model Zoo, über cv2.dnn.
- Szenenhinweise: MobileNetV2 (ImageNet) aus dem OpenCV Model Zoo, zu Gruppen zusammengefasst
  (Berge, Wasser, Architektur, Essen). Nur ein Hinweis, nie allein entscheidend.
- Bereiche: Himmel, Grün, Wasser aus Farbe, Helligkeit und Struktur (keine Segmentierung per
  Modell). Himmel = glatte, helle Fläche, die oben an den Bildrand stößt.
- Horizont: Grenze zwischen Himmel und dem, was darunter liegt, wenn sie über einen großen Teil
  der Breite gerade verläuft.

Alle Funktionen arbeiten auf RGB uint8. Fehlen die Modelle, liefern objekte() und hinweise()
leere Ergebnisse; der Bildtyp stützt sich dann nur auf Gesichter und Bereiche.
"""
from __future__ import annotations

import math
import os
import sys
import threading

import cv2
import numpy as np

HIER = os.path.dirname(os.path.abspath(__file__))
DETEKTOR = os.environ.get('FOTO_DETEKTOR', '/opt/foto/object_detection_nanodet_2022nov.onnx')
KLASSIFIKATOR = os.environ.get('FOTO_KLASSIFIKATOR', '/opt/foto/image_classification_mobilenetv2_2022apr.onnx')

COCO = ('person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat', 'traffic light',
        'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
        'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
        'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard',
        'tennis racket', 'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
        'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
        'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard',
        'cell phone', 'microwave', 'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase',
        'scissors', 'teddy bear', 'hair drier', 'toothbrush')
DEUTSCH = {'person': 'person', 'dog': 'hund', 'cat': 'katze', 'bird': 'vogel', 'horse': 'pferd',
           'sheep': 'schaf', 'cow': 'kuh', 'elephant': 'elefant', 'bear': 'bär', 'zebra': 'zebra',
           'giraffe': 'giraffe', 'car': 'auto', 'bicycle': 'fahrrad', 'motorcycle': 'motorrad', 'bus': 'bus',
           'truck': 'lkw', 'train': 'zug', 'boat': 'boot', 'airplane': 'flugzeug', 'bench': 'bank',
           'bottle': 'flasche', 'wine glass': 'weinglas', 'cup': 'tasse', 'bowl': 'schüssel',
           'dining table': 'tisch', 'chair': 'stuhl', 'potted plant': 'topfpflanze', 'umbrella': 'schirm'}
TIERE = {'hund', 'katze', 'vogel', 'pferd', 'schaf', 'kuh', 'elefant', 'bär', 'zebra', 'giraffe'}
ESSEN = {'banana', 'apple', 'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake',
         'schüssel'}

# ImageNet-Indizes je Gruppe (Namen in imagenet_labels.txt)
GRUPPEN = {
    'berge': [970, 972, 979, 980, 500, 672],
    'wasser': [975, 978, 977, 976, 973, 974, 718, 460, 449, 914, 780, 484, 871, 814, 628, 510, 554, 913, 472, 576],
    'architektur': [497, 483, 698, 663, 668, 538, 442, 873, 682, 832, 425, 624, 727, 839, 821, 888, 525, 900,
                    858, 853, 649, 562, 863, 498, 743, 437],
    'essen': [923, 963, 959, 925, 926, 927, 928, 924, 933, 934, 965, 962, 964, 931, 932, 967, 966, 961, 935,
              936, 937, 938, 950, 951, 954, 953, 949, 957, 952, 948, 922, 762],
    'hund': list(range(151, 269)),
    'katze': list(range(281, 286)),
}

_LOCK = threading.Lock()  # cv2.dnn-Netze nicht parallel benutzen
_NETZE: dict = {}
_GEMELDET: set = set()


def _log(msg):
    print('[foto]', msg, file=sys.stderr, flush=True)


def _netz(pfad):
    if pfad not in _NETZE:
        if os.path.isfile(pfad):
            _NETZE[pfad] = cv2.dnn.readNet(pfad)
        else:
            _NETZE[pfad] = None
            if pfad not in _GEMELDET:
                _GEMELDET.add(pfad); _log(f'Modell fehlt, Erkennung eingeschränkt: {pfad}')
    return _NETZE[pfad]


def modelle() -> dict:
    """Welche Modelle geladen werden können (für Log und Selbsttest)."""
    with _LOCK:
        return {'objekte': _netz(DETEKTOR) is not None, 'szene': _netz(KLASSIFIKATOR) is not None}


# ---------- Objekte (NanoDet-Plus, 416x416, BGR) ----------
_STRIDES = (8, 16, 32, 64)
_ANKER = []
for _s in _STRIDES:
    _n = 416 // _s
    _xv, _yv = np.meshgrid(np.arange(_n) * _s, np.arange(_n) * _s)
    _ANKER.append(np.column_stack((_xv.ravel() + 0.5 * (_s - 1), _yv.ravel() + 0.5 * (_s - 1))))


def objekte(rgb, schwelle: float = 0.35) -> list[dict]:
    """Objekte mit Klasse (deutsch, sonst COCO-Name), Sicherheit und Box [x0, y0, x1, y1] in Pixeln."""
    H, W = rgb.shape[:2]
    s = 416 / max(H, W); nh, nw = max(1, round(H * s)), max(1, round(W * s))
    img = cv2.resize(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), (nw, nh), interpolation=cv2.INTER_AREA)
    top, left = (416 - nh) // 2, (416 - nw) // 2
    img = cv2.copyMakeBorder(img, top, 416 - nh - top, left, 416 - nw - left, cv2.BORDER_CONSTANT, value=0)
    blob = cv2.dnn.blobFromImage((img.astype(np.float32) - [103.53, 116.28, 123.675]) / [57.375, 57.12, 58.395])
    with _LOCK:
        net = _netz(DETEKTOR)
        if net is None:
            return []
        net.setInput(blob)
        outs = net.forward(net.getUnconnectedOutLayersNames())
    boxes, scores = [], []
    for st, cls, reg, anc in zip(_STRIDES, outs[::2], outs[1::2], _ANKER):
        cls = cls.reshape(-1, len(COCO)); reg = reg.reshape(-1, 8)
        e = np.exp(reg - reg.max(1, keepdims=True)); d = (e / e.sum(1, keepdims=True)) @ np.arange(8)
        d = d.reshape(-1, 4) * st
        boxes.append(np.column_stack([anc[:, 0] - d[:, 0], anc[:, 1] - d[:, 1], anc[:, 0] + d[:, 2], anc[:, 1] + d[:, 3]]))
        scores.append(cls)
    boxes = np.clip(np.concatenate(boxes), 0, 416); scores = np.concatenate(scores)
    cid = scores.argmax(1); conf = scores.max(1)
    keep = conf >= schwelle
    if not keep.any():
        return []
    boxes, cid, conf = boxes[keep], cid[keep], conf[keep]
    wh = boxes.copy(); wh[:, 2:] -= wh[:, :2]
    idx = cv2.dnn.NMSBoxesBatched(wh.tolist(), conf.tolist(), cid.tolist(), schwelle, 0.6)
    out = []
    for i in np.array(idx).ravel():
        x0, y0, x1, y1 = boxes[i]
        x0, x1 = (np.clip([x0, x1], left, left + nw) - left) / s
        y0, y1 = (np.clip([y0, y1], top, top + nh) - top) / s
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        name = COCO[cid[i]]
        out.append(dict(klasse=DEUTSCH.get(name, name), sicherheit=round(float(conf[i]), 2),
                        box=[round(float(x0)), round(float(y0)), round(float(x1)), round(float(y1))]))
    return sorted(out, key=lambda o: -(o['box'][2] - o['box'][0]) * (o['box'][3] - o['box'][1]))


# ---------- Szenenhinweise (MobileNetV2, ImageNet) ----------
_LABELS: list[str] = []


def labels() -> list[str]:
    if not _LABELS:
        try:
            with open(os.path.join(HIER, 'imagenet_labels.txt'), encoding='utf-8') as f:
                _LABELS.extend(x.strip() for x in f)
        except OSError:
            pass
    return _LABELS


def hinweise(rgb) -> dict:
    """{'gruppen': {gruppe: Wahrscheinlichkeit}, 'top': [(label, p), ...]} oder leer ohne Modell."""
    img = cv2.resize(rgb, (256, 256), interpolation=cv2.INTER_AREA)[16:240, 16:240].astype(np.float32) / 255
    x = ((img - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype(np.float32)
    with _LOCK:
        net = _netz(KLASSIFIKATOR)
        if net is None:
            return {}
        net.setInput(x)
        o = net.forward().ravel().astype(np.float64)
    if o.min() < 0 or abs(o.sum() - 1) > 0.01:
        o = np.exp(o - o.max()); o /= o.sum()
    lb = labels()
    top = [(lb[i] if i < len(lb) else str(i), round(float(o[i]), 3)) for i in o.argsort()[::-1][:5]]
    return {'gruppen': {g: round(float(o[ix].sum()), 3) for g, ix in GRUPPEN.items()}, 'top': top}


# ---------- Bereiche (Himmel, Grün, Wasser) ----------
def _klein(rgb, seite=512):
    s = min(1.0, seite / max(rgb.shape[:2]))
    return cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else rgb


def bereiche(rgb, wasser_hinweis: float = 0.0) -> dict:
    """Masken (uint8 0/1, ca. 512 px lange Seite) und Anteile für himmel, gruen, wasser.
    'grenze': je Spalte die Zeile unter dem tiefsten Himmelspixel (-1 = kein Himmel in der Spalte),
    'ufer': je Spalte die oberste Wasserzeile (-1 = kein Wasser). Grau gilt nur als Wasser, wenn
    die Szenenerkennung Wasser vermutet (wasser_hinweis), sonst wären Straßen Wasser."""
    k = _klein(rgb); h, w = k.shape[:2]
    f = k.astype(np.float32) / 255
    hsv = cv2.cvtColor(f, cv2.COLOR_RGB2HSV); H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    L = cv2.cvtColor(f, cv2.COLOR_RGB2LAB)[..., 0]
    mu = cv2.GaussianBlur(L, (0, 0), 2.5)
    tex = np.sqrt(np.maximum(cv2.GaussianBlur(L * L, (0, 0), 2.5) - mu * mu, 0))
    blau = (H > 185) & (H < 255) & (S > 0.08)
    grau = S < 0.22
    # glatter blauer oder grauer Himmel, dazu helle Wolken (dürfen etwas Struktur haben)
    himmelig = ((V > 0.42) & (tex < 2.8) & (blau | grau)) | ((V > 0.62) & (S < 0.25) & (tex < 6.0))
    himmelig = cv2.morphologyEx(himmelig.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    # an deutlichen waagrechten Kanten trennen, sonst wächst ruhiges blaues Meer mit dem Himmel zusammen
    Lb = cv2.GaussianBlur(L, (0, 0), 1.0)
    kante = np.abs(cv2.Sobel(Lb, cv2.CV_32F, 0, 1, ksize=3)) / 8 > 2.0
    himmelig[cv2.dilate(kante.astype(np.uint8), np.ones((3, 1), np.uint8)) > 0] = 0
    n, lbl, st, _ = cv2.connectedComponentsWithStats(himmelig, 4)
    oben = set(np.unique(lbl[:max(2, h // 60)])) - {0}
    roh = np.isin(lbl, [i for i in oben if st[i, cv2.CC_STAT_AREA] >= 0.01 * h * w]).astype(np.uint8)
    # Grenze je Spalte: unter dem tiefsten Himmelspixel. Alles darüber zählt als Himmel, auch
    # Wolken mit Struktur, Vögel und Leitungen.
    hat = roh.any(0)
    tief = h - 1 - np.argmax(roh[::-1], axis=0)
    grenze = np.where(hat, tief + 1, -1).astype(np.int32)
    yy = np.arange(h)[:, None]
    himmel = ((yy < np.maximum(grenze, 0)[None, :]) & hat[None, :]).astype(np.uint8)
    gruen = (((H > 60) & (H < 170) & (S > 0.16) & (V > 0.1)) & (himmel == 0)).astype(np.uint8)
    gruen = cv2.morphologyEx(gruen, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    gy = grenze[grenze >= 0]
    unten_ab = int(np.median(gy)) if len(gy) > 0.3 * w else int(0.3 * h)
    farbe = blau | ((H > 160) & (H < 200) & (S > 0.08))
    if wasser_hinweis >= 0.15:
        farbe = farbe | grau
    wasser = ((yy > unten_ab) & (himmel == 0) & (tex < 4.0) & (S < 0.6) & (V > 0.12) & farbe).astype(np.uint8)
    wasser = cv2.morphologyEx(wasser, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n3, lbl3, st3, _ = cv2.connectedComponentsWithStats(wasser, 4)
    gross = [i for i in range(1, n3) if st3[i, cv2.CC_STAT_AREA] >= 0.03 * h * w
             and st3[i, cv2.CC_STAT_WIDTH] >= 0.3 * w]
    wasser = np.isin(lbl3, gross).astype(np.uint8)
    hw = wasser.any(0)
    ufer = np.where(hw, np.argmax(wasser, axis=0), -1).astype(np.int32)
    return dict(himmel=himmel, gruen=gruen, wasser=wasser, grenze=grenze, ufer=ufer, groesse=(w, h),
                anteil={'himmel': round(float(himmel.mean()), 3), 'gruen': round(float(gruen.mean()), 3),
                        'wasser': round(float(wasser.mean()), 3)})


def _gerade(g, w, h):
    """Robuste Gerade durch eine Spaltengrenze. dict(k, c, abdeckung, rest, gewicht) oder None."""
    xs = np.flatnonzero((g > 0.04 * h) & (g < 0.96 * h))
    if len(xs) < 0.5 * w:
        return None
    ys = g[xs].astype(np.float64); m = np.ones(len(xs), bool); k = c = 0.0
    for _ in range(4):  # robust: Masten, Türme und Bäume fallen als Ausreißer heraus
        if m.sum() < 0.35 * w:
            return None
        k, c = np.polyfit(xs[m], ys[m], 1)
        r = np.abs(ys - (k * xs + c))
        m = r < max(2.0, 2.5 * np.median(r[m]) + 0.5)
    if m.sum() < 0.4 * w:
        return None
    abdeckung = (xs[m].max() - xs[m].min()) / w
    rest = float(np.median(np.abs(ys[m] - (k * xs[m] + c)))) / h
    if abdeckung < 0.5 or rest > 0.01 or abs(math.degrees(math.atan(k))) > 5:
        return None
    return dict(k=float(k), c=float(c), abdeckung=float(abdeckung), rest=rest, gewicht=float(m.sum() / w))


def horizont(rgb, ber: dict | None = None):
    """Horizont: gerade Grenze zwischen Himmel und Land/Wasser oder gerade Uferlinie, über
    mindestens die halbe Breite. Liefert dict(winkel, y, linie, abdeckung, rest, gewicht) mit
    winkel in Grad gegen den Uhrzeigersinn (wie fotolib.rotate) und y als Anteil der Höhe in der
    Bildmitte, oder None."""
    ber = ber or bereiche(rgb)
    w, h = ber['groesse']; kand = []
    if 0.05 <= ber['anteil']['himmel'] <= 0.85:
        g = _gerade(ber['grenze'], w, h)
        if g:
            kand.append(('himmel', g))
    if ber['anteil']['wasser'] >= 0.08:
        g = _gerade(ber['ufer'], w, h)
        if g:
            kand.append(('ufer', g))
    if not kand:
        return None
    art, g = min(kand, key=lambda t: t[1]['rest'] / t[1]['gewicht'])
    winkel = math.degrees(math.atan(g['k']))
    fein = _feinwinkel(rgb, g['k'], g['c'] / h)  # Kante in höherer Auflösung nachmessen
    if fein is not None:
        winkel = fein
    return dict(winkel=round(winkel, 2), y=round((g['k'] * w / 2 + g['c']) / h, 3), linie=art,
                abdeckung=round(g['abdeckung'], 2), rest=round(g['rest'], 4), gewicht=round(g['gewicht'], 2))


def _feinwinkel(rgb, k, c_rel):
    """Linien (LSD) nahe der Himmelsgrenze in höherer Auflösung, längengewichtet gemittelt."""
    s = min(1.0, 2000 / max(rgb.shape[:2]))
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if s < 1:
        g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    h, w = g.shape
    L = cv2.createLineSegmentDetector().detect(g)[0]
    if L is None:
        return None
    acc, wt = [], []
    for x1, y1, x2, y2 in L.reshape(-1, 4):
        ln = math.hypot(x2 - x1, y2 - y1)
        if ln < 0.04 * w:
            continue
        a = math.degrees(math.atan2(y2 - y1, x2 - x1)); a = (a + 90) % 180 - 90
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ey = k * mx + c_rel * h  # erwartete Grenze bei mx (Steigung ist maßstabsfrei)
        if abs(my - ey) < 0.015 * h and abs(a - math.degrees(math.atan(k))) < 1.5:
            acc.append(a); wt.append(ln)
    if sum(wt) < 0.3 * w:
        return None
    return float(np.average(acc, weights=wt))


# ---------- Bildtyp ----------
def _flaeche(b, W, H):
    return (b[2] - b[0]) * (b[3] - b[1]) / (W * H)


def tiere_korrigieren(objs, hin) -> list:
    """NanoDet verwechselt Hund und Katze öfter; ImageNet kennt 118 Hunderassen. Ist das Bild dort
    eindeutig Hund oder Katze, bekommen erkannte Tiere diese Klasse."""
    gr = (hin or {}).get('gruppen', {})
    hund, katze = gr.get('hund', 0), gr.get('katze', 0)
    neu = 'hund' if hund >= 0.3 and hund > 2 * katze else 'katze' if katze >= 0.3 and katze > 2 * hund else None
    if not neu:
        return objs
    return [dict(o, klasse=neu) if o['klasse'] in ('hund', 'katze') else o for o in objs]


def hauptpersonen(objs, shape):
    """Personen-Boxen, die groß genug sind (keine Passanten): Höhe >= 25 % oder Fläche >= 4 %,
    und mindestens 45 % so hoch wie die größte Person."""
    H, W = shape[:2]
    ps = [o for o in objs if o['klasse'] == 'person' and o['sicherheit'] >= 0.4]
    ps = [o for o in ps if (o['box'][3] - o['box'][1]) >= 0.25 * H or _flaeche(o['box'], W, H) >= 0.04]
    if not ps:
        return []
    top = max(o['box'][3] - o['box'][1] for o in ps)
    return [o for o in ps if (o['box'][3] - o['box'][1]) >= 0.45 * top]


def haupttiere(objs, shape):
    H, W = shape[:2]
    ts = [o for o in objs if o['klasse'] in TIERE and o['sicherheit'] >= 0.4
          and ((o['box'][3] - o['box'][1]) >= 0.2 * H or _flaeche(o['box'], W, H) >= 0.03)]
    if not ts:
        return []
    top = max(_flaeche(o['box'], W, H) for o in ts)
    return [o for o in ts if _flaeche(o['box'], W, H) >= 0.3 * top]


def baum(ber):
    """Frei stehender Baum: eine große grüne Fläche, nicht über die ganze Breite, mit Himmel
    daneben. Liefert die Box als Anteile [x0, y0, x1, y1] oder None."""
    w, h = ber['groesse']; g = ber['gruen']; hi = ber['himmel']
    n, lbl, st, _ = cv2.connectedComponentsWithStats(g, 8)
    if n <= 1:
        return None
    ar = st[1:, cv2.CC_STAT_AREA]; i = int(ar.argmax()) + 1; a = ar.max() / (w * h)
    x, y, bw, bh = st[i, :4]
    andere = [j for j in range(1, n) if j != i and st[j, cv2.CC_STAT_AREA] >= 0.4 * ar.max()]
    if not (0.04 <= a <= 0.5) or bw > 0.65 * w or andere:
        return None
    band = slice(y, y + max(1, bh // 2))  # obere Hälfte der Krone
    links = hi[band, max(0, x - bw // 3):x]; rechts = hi[band, x + bw:min(w, x + bw + bw // 3)]
    frei = [float(z.mean()) for z in (links, rechts) if z.size]
    if not frei or max(frei) < 0.3:
        return None
    return [x / w, y / h, (x + bw) / w, (y + bh) / h]


def bildtyp(shape, gesichter: int, objs: list, ber: dict, hin: dict, senkrecht: float = 0.0) -> dict:
    """Bildtyp mit Begründung. gesichter = Zahl der Hauptgesichter, senkrecht = Gewicht der
    senkrechten Linien aus fotolib.tilt (Architektur)."""
    H, W = shape[:2]
    objs = tiere_korrigieren(objs, hin)
    ps = hauptpersonen(objs, shape); ts = haupttiere(objs, shape)
    gr = (hin or {}).get('gruppen', {}); an = ber['anteil']
    # ohne Gesicht nur deutlich große Personen zählen (sonst wird jede Straßenszene ein Porträt)
    gross = [o for o in ps if (o['box'][3] - o['box'][1]) >= 0.4 * H or _flaeche(o['box'], W, H) >= 0.08]
    n = max(gesichter, len(gross))
    essen = sum(_flaeche(o['box'], W, H) for o in objs if o['klasse'] in ESSEN)
    hz = ber.get('_horizont')

    def typ(t, *g):
        return dict(typ=t, begruendung=', '.join(x for x in g if x), personen=n,
                    tiere=[o['klasse'] for o in ts], anteile=an, gruppen=gr)

    if n >= 2:
        return typ('gruppe', f'{n} Hauptpersonen' + (f' ({gesichter} Gesichter)' if gesichter else ''))
    if n == 1:
        return typ('portraet', '1 Hauptperson' + (' (Gesicht)' if gesichter else ' (Körper erkannt)'),
                   f"mit {', '.join(o['klasse'] for o in ts)}" if ts else '')
    if ts:
        return typ('tier', f"{len(ts)}× {', '.join(sorted({o['klasse'] for o in ts}))}")
    if essen >= 0.12 or gr.get('essen', 0) >= 0.35:
        return typ('essen', f'Essen {essen:.0%} der Fläche' if essen >= 0.12 else '',
                   f"Szene Essen {gr.get('essen', 0):.0%}" if gr.get('essen', 0) >= 0.35 else '')
    if gr.get('architektur', 0) >= 0.4:
        return typ('architektur', f"Szene Architektur {gr['architektur']:.0%}")
    if (an['wasser'] >= 0.12 and an['himmel'] >= 0.05) or gr.get('wasser', 0) >= 0.35:
        return typ('meer', f"Wasser {an['wasser']:.0%}, Himmel {an['himmel']:.0%}" if an['wasser'] >= 0.12 else '',
                   f"Szene Wasser {gr.get('wasser', 0):.0%}" if gr.get('wasser', 0) >= 0.35 else '',
                   'Horizont gerade' if hz else '')
    if gr.get('architektur', 0) >= 0.2 or senkrecht >= 1.2:
        return typ('architektur', f"Szene Architektur {gr.get('architektur', 0):.0%}" if gr.get('architektur', 0) >= 0.2 else '',
                   f'viele senkrechte Kanten ({senkrecht:.1f})' if senkrecht >= 1.2 else '')
    rau = _grenze_rau(ber)
    if gr.get('berge', 0) >= 0.3 or (rau and an['himmel'] >= 0.1 and an['gruen'] < 0.5 and gr.get('berge', 0) >= 0.08):
        return typ('berge', f"Szene Berge {gr.get('berge', 0):.0%}", 'unruhige Himmelsgrenze' if rau else '')
    b = baum(ber)
    if b:
        d = typ('baum', f"frei stehende Grünfläche {(b[2] - b[0]) * (b[3] - b[1]):.0%} der Fläche, Himmel daneben")
        d['box'] = b
        return d
    if an['gruen'] >= 0.25 or an['himmel'] >= 0.2:
        return typ('landschaft', f"Grün {an['gruen']:.0%}, Himmel {an['himmel']:.0%}")
    return typ('sonstiges', 'kein eindeutiges Motiv (Detail, Schild, Innenraum)')


def _grenze_rau(ber) -> bool:
    w, h = ber['groesse']; g = ber['grenze']
    xs = np.flatnonzero((g > 0.04 * h) & (g < 0.9 * h))
    if len(xs) < 0.6 * w:
        return False
    ys = g[xs].astype(np.float64); k, c = np.polyfit(xs, ys, 1)
    return float(np.median(np.abs(ys - (k * xs + c)))) / h > 0.02


# ---------- Regeln je Bildtyp ----------
# look: Regler für fotolib-anpassen (-100..100), Unterschlüssel = Bereich. Bewusst dezent.
REGELN = {
    'portraet': dict(zuschnitt='motiv', look={'schatten': 10, 'waerme': 3, 'vignette': 10}, retusche=True),
    'gruppe': dict(zuschnitt='motiv', look={'schatten': 15, 'lichter': -10}, retusche=False),
    'tier': dict(zuschnitt='motiv', look={'struktur': 10, 'schatten': 5}, retusche=False),
    'baum': dict(zuschnitt='motiv', look={'struktur': 15, 'vignette': 15}, retusche=False),
    'landschaft': dict(zuschnitt='original', look={'atmosphaere': 15, 'struktur': 10, 'saettigung': 5},
                       retusche=False),
    'berge': dict(zuschnitt='original', look={'struktur': 20, 'atmosphaere': 10, 'himmel': {'helligkeit': -8}},
                  retusche=False),
    'meer': dict(zuschnitt='horizont', look={'waerme': 5, 'lichter': -15}, retusche=False),
    'architektur': dict(zuschnitt='original', look={'struktur': 15}, retusche=False),
    'essen': dict(zuschnitt='original', look={'waerme': 3, 'saettigung': 5}, retusche=False),
    'sonstiges': dict(zuschnitt='original', look={}, retusche=False),
}
TYPEN = tuple(REGELN)


# ---------- Masken für Personen und Motive ----------
def objekt_maske(rgb, boxen, breite: int | None = None) -> np.ndarray:
    """Maske (uint8 0/1, ca. 512 px) der Objekte in den Boxen [x0, y0, x1, y1]: GrabCut je Box, bei
    Misserfolg eine Ellipse in der Box. breite = Bildbreite, auf die sich die Boxen beziehen
    (Standard: rgb)."""
    k = _klein(rgb); h, w = k.shape[:2]; s = w / (breite or rgb.shape[1])
    bgr = cv2.cvtColor(k, cv2.COLOR_RGB2BGR); m = np.zeros((h, w), np.uint8)
    for b in boxen:
        x0, y0 = max(0, int(b[0] * s)), max(0, int(b[1] * s))
        x1, y1 = min(w - 1, int(math.ceil(b[2] * s))), min(h - 1, int(math.ceil(b[3] * s)))
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        ell = np.zeros((h, w), np.uint8)
        cv2.ellipse(ell, ((x0 + x1) // 2, (y0 + y1) // 2), ((x1 - x0) // 2, (y1 - y0) // 2), 0, 0, 360, 1, -1)
        teil = ell
        if (x1 - x0) * (y1 - y0) < 0.9 * h * w:
            gm = np.zeros((h, w), np.uint8)
            try:
                cv2.grabCut(bgr, gm, (x0, y0, x1 - x0, y1 - y0), np.zeros((1, 65)), np.zeros((1, 65)), 3,
                            cv2.GC_INIT_WITH_RECT)
                gc = np.isin(gm, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8)
                if 0.15 <= gc.sum() / max(1, (x1 - x0) * (y1 - y0)) <= 0.95:
                    teil = gc
            except cv2.error:
                pass
        m |= teil
    return m


def masken(rgb, ber: dict, personen: list, motive: list, breite: int | None = None) -> dict:
    """Bereichsmasken (klein, uint8) für fotolib.anpassen. personen/motive: Boxen in Pixeln eines
    Bildes der Breite breite (Standard: rgb)."""
    p = objekt_maske(rgb, personen, breite) if personen else None
    mo = objekt_maske(rgb, motive, breite) if motive else p
    out = {'himmel': ber['himmel'], 'gruen': ber['gruen'], 'wasser': ber['wasser']}
    w, h = ber['groesse']
    out['person'] = p if p is not None else np.zeros((h, w), np.uint8)
    out['motiv'] = mo if mo is not None else np.zeros((h, w), np.uint8)
    out['hintergrund'] = (1 - out['motiv']).astype(np.uint8) if out['motiv'].any() else np.zeros((h, w), np.uint8)
    return out
