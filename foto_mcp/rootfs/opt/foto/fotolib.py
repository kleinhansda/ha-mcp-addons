"""Bildfunktionen von Foto MCP: sichten, Schräglage, Gesichter, Tonwert, Zuschnitt, Effekte, Retusche.

Alles arbeitet auf RGB-Arrays (uint8 oder float32 0..1). Kein Weißabgleich (verfälscht Wiesen
und Kunstlicht). Originale werden nie überschrieben, das regelt server.py.
"""
from __future__ import annotations

import hashlib
import io
import math
import os
import threading

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

cv2.setNumThreads(max(1, (os.cpu_count() or 2)))

ASPECTS = {'3:2': 1.5, '4:3': 4 / 3, '5:4': 1.25, '1:1': 1.0, '4:5': 0.8, '3:4': 0.75,
           '2:3': 2 / 3, '16:9': 16 / 9, '9:16': 9 / 16}
EXIF_NAMES = {0x0110: 'kamera', 0x920A: 'brennweite', 0xA405: 'brennweite_kb', 0x829D: 'blende',
              0x829A: 'belichtung', 0x8827: 'iso', 0x9003: 'aufnahme', 0xA434: 'objektiv'}
MODEL = os.environ.get('FOTO_MODEL', '/opt/foto/face_landmarker.task')


# ---------- Laden / Speichern ----------
def load(path: str, max_side: int | None = None):
    """Liest ein Bild, dreht es nach EXIF. Liefert (rgb uint8, exif, icc)."""
    im = Image.open(path)
    exif = im.getexif(); icc = im.info.get('icc_profile')
    if max_side:
        im.draft('RGB', (max_side, max_side))
    im = ImageOps.exif_transpose(im).convert('RGB')
    if max_side and max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    if 0x0112 in exif:
        exif[0x0112] = 1
    return np.asarray(im), exif, icc


def iso_of(exif) -> int:
    v = exif.get_ifd(0x8769).get(0x8827, 100)
    if isinstance(v, (tuple, list)):
        v = v[0]
    try:
        return int(v)
    except (TypeError, ValueError):
        return 100


def exif_info(path: str) -> dict:
    im = Image.open(path); ex = im.getexif(); sub = ex.get_ifd(0x8769)
    out = {'pixel': list(im.size), 'ausrichtung': ex.get(0x0112, 1)}
    for tag, name in EXIF_NAMES.items():
        v = sub.get(tag, ex.get(tag))
        if v is None:
            continue
        if name == 'belichtung':
            f = float(v); v = f'1/{round(1 / f)}' if 0 < f < 1 else f'{f:g}'
        elif name in ('brennweite', 'blende'):
            v = round(float(v), 1)
        elif isinstance(v, bytes):
            v = v.decode(errors='ignore').strip('\x00 ')
        elif not isinstance(v, (int, float, str)):
            v = str(v)
        out[name] = v
    return out


def save_jpg(rgb, path: str, exif=None, icc=None, quality: int = 92):
    im = Image.fromarray(rgb if rgb.dtype == np.uint8 else to_u8(rgb))
    kw = dict(quality=quality, subsampling=0)
    if exif is not None:
        kw['exif'] = exif.tobytes()
    if icc:
        kw['icc_profile'] = icc
    tmp = path + '.tmp'
    im.save(tmp, format='JPEG', **kw)
    os.replace(tmp, path)


def jpeg_bytes(img, quality: int = 82) -> bytes:
    b = io.BytesIO(); Image.fromarray(img).save(b, format='JPEG', quality=quality); return b.getvalue()


def md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ---------- Schärfe ----------
def sharpness(rgb) -> tuple[float, float]:
    """(Laplace-Varianz gesamt, 98.-Perzentil der Block-Varianz) auf ca. 1200 px."""
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    lap = np.abs(cv2.Laplacian(g, cv2.CV_32F))
    b = 48; h, w = lap.shape
    v = lap[:h // b * b, :w // b * b].reshape(h // b, b, w // b, b).var(axis=(1, 3)).ravel()
    return round(float(lap.var()), 1), round(float(np.percentile(v, 98)), 1)


# ---------- Tonwert, Rauschen, Schärfe ----------
# Gegen Tonwertabrisse (Stufen im Himmel) und ausgefressene Lichter:
# - Entrauschen nur der Farbe (a/b), Helligkeit erst ab ISO 1600 und nur halb.
# - Weißpunkt aus dem hellsten Kanal, damit kein Kanal neu ausläuft.
# - Lichter über eine kantenerhaltende Basisebene etwas absenken, die Struktur darin bleibt.
# - Schärfen mit Schwelle, glatte Flächen bleiben glatt.
# - 8 Bit erst beim Speichern, mit Dreiecks-Dithering.
_W = np.array([0.299, 0.587, 0.114], np.float32)


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def base_layer(L, s: int = 4):
    h, w = L.shape
    small = cv2.resize(L, (max(1, w // s), max(1, h // s)), interpolation=cv2.INTER_AREA)
    b = cv2.bilateralFilter(small, 0, 0.08, max(h, w) / s * 0.01)
    return cv2.resize(b, (w, h), interpolation=cv2.INTER_LINEAR)


def auto_tone(f, lichter: float = 0.25):
    L = f @ _W
    lo = min(float(np.percentile(L, 0.2)), 0.06)
    hi = max(float(np.percentile(f.max(2), 99.95)), 0.92)
    g = np.clip((f - lo) / (hi - lo), 0, 1).astype(np.float32)
    if lichter <= 0:
        return g
    B = base_layer(g @ _W)
    # monoton: helle Basis gleichmäßig absenken, auch ausgefressene Flächen (keine Flecken)
    gain = (B - lichter * smoothstep(0.72, 1.0, B) * (B - 0.72)) / np.maximum(B, 1e-4)
    return np.clip(g * gain[..., None], 0, 1)


def denoise(f, iso: int):
    if iso < 400:
        return f
    hc = 4 if iso < 700 else 6 if iso < 1600 else 9
    lab = cv2.cvtColor(f.astype(np.float32), cv2.COLOR_RGB2LAB)
    for c in (1, 2):
        u8 = np.clip(lab[..., c] + 128, 0, 255).astype(np.uint8)
        lab[..., c] = cv2.fastNlMeansDenoising(u8, None, hc, 7, 21).astype(np.float32) - 128
    if iso >= 1600:
        L = lab[..., 0]
        d = cv2.fastNlMeansDenoising(np.clip(L * 2.55, 0, 255).astype(np.uint8), None, 3, 7, 21)
        lab[..., 0] = L + 0.5 * (d.astype(np.float32) / 2.55 - L)
    return np.clip(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB), 0, 1)


def usm(f, amount: float, radius: float = 1.2, thr: float = 0.006):
    L = f @ _W
    dL = L - cv2.GaussianBlur(L, (0, 0), radius)
    return np.clip(f + (amount * dL * smoothstep(thr, 2 * thr, np.abs(dL)))[..., None], 0, 1)


def to_u8(f, seed: int = 0):
    rng = np.random.default_rng(seed)
    n = rng.random(f.shape, np.float32) - rng.random(f.shape, np.float32)
    return np.clip(np.clip(f, 0, 1) * 255 + n + 0.5, 0, 255).astype(np.uint8)


# ---------- Schräglage ----------
def tilt(rgb, people=None) -> tuple[float, str | None, float]:
    """Schräglage aus Liniensegmenten. Senkrechte: Winkel gegen waagrechte Bildposition linear
    angepasst (stürzende Linien), Wert in der Bildmitte. Sonst Horizont.
    people: Rechtecke (x0, y0, x1, y1) in Bildpixeln, deren Linien nicht zählen (Kleidung, Körper).
    Liefert (Grad gegen den Uhrzeigersinn, Quelle, Gewicht)."""
    g = cv2.cvtColor(rgb if rgb.dtype == np.uint8 else (rgb * 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    s = 2000 / max(g.shape)
    if s < 1:
        g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    h, w = g.shape; L = cv2.createLineSegmentDetector().detect(g)[0]
    sc = w / rgb.shape[1]
    boxes = [tuple(v * sc for v in b) for b in (people or [])]
    H, V = [], []
    for x1, y1, x2, y2 in (L.reshape(-1, 4) if L is not None else []):
        ln = math.hypot(x2 - x1, y2 - y1)
        if ln < 0.05 * max(h, w):
            continue
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        if any(b[0] <= mx <= b[2] and b[1] <= my <= b[3] for b in boxes):
            continue
        a = (math.degrees(math.atan2(y2 - y1, x2 - x1)) + 90) % 180 - 90
        if abs(a) < 12:
            H.append((a, ln))
        elif abs(abs(a) - 90) < 12:
            V.append((a - 90 if a > 0 else a + 90, ln, (x1 + x2) / 2 / w - 0.5))
    vv = None
    if len(V) >= 4:
        a = np.array([v[0] for v in V]); wt = np.array([v[1] for v in V]); x = np.array([v[2] for v in V])
        m = np.ones(len(a), bool); c = k = 0.0
        for _ in range(3):
            if m.sum() < 4:
                break
            A = np.stack([np.ones(m.sum()), x[m]], 1); W = np.sqrt(wt[m])
            c, k = np.linalg.lstsq(A * W[:, None], a[m] * W, rcond=None)[0]
            m = np.abs(a - (c + k * x)) < 1.2
        if m.sum() >= 4 and abs(k) < 15:
            vv = (float(c), float(wt[m].sum() / max(h, w)), int(m.sum()))
    hv = None
    if len(H) >= 3:
        a = np.array([x for x, _ in H]); wt = np.array([ln for _, ln in H])
        hist, e = np.histogram(a, bins=np.arange(-12, 12.01, 0.25), weights=wt)
        i = np.convolve(hist, [1, 2, 3, 2, 1], 'same').argmax(); c = (e[i] + e[i + 1]) / 2
        mm = np.abs(a - c) < 0.75
        hv = (float(np.average(a[mm], weights=wt[mm])), float(wt[mm].sum() / max(h, w)))
    if vv and vv[1] >= 0.8 and vv[2] >= 5:
        return round(vv[0], 2), 'senkrecht', round(vv[1], 2)
    if hv and hv[1] >= 3.0 and abs(hv[0]) < 3:
        return round(hv[0], 2), 'waagrecht', round(hv[1], 2)
    return 0.0, None, 0.0


def rotate(f, deg: float):
    if not deg:
        return f
    h, w = f.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(f, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


def valid_rect(w, h, deg):
    if not deg:
        return 0, 0, w, h
    t = math.radians(abs(deg)); c, s = math.cos(t), math.sin(t)
    k = 1 / (c + s * max(w / h, h / w)); cw, ch = w * k, h * k
    return (w - cw) / 2, (h - ch) / 2, cw, ch


# ---------- Gesichter (MediaPipe) ----------
_LM = None
_LM_LOCK = threading.Lock()  # MediaPipe-Landmarker ist nicht für parallele Aufrufe gedacht


def _close_landmarker():
    global _LM
    if _LM is not None:
        try:
            _LM.close()
        except Exception:
            pass
        _LM = None


def _landmarker():
    global _LM
    if _LM is None:
        import atexit
        atexit.register(_close_landmarker)
        import mediapipe as mp  # noqa: F401
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        opts = vision.FaceLandmarkerOptions(base_options=mpt.BaseOptions(model_asset_path=MODEL),
                                            num_faces=6, min_face_detection_confidence=0.5)
        _LM = vision.FaceLandmarker.create_from_options(opts)
    return _LM


def _detect(img, ox=0.0, oy=0.0, scale=1.0):
    import mediapipe as mp
    h, w = img.shape[:2]
    with _LM_LOCK:
        res = _landmarker().detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img)))
    return [np.array([[ox + p.x * w / scale, oy + p.y * h / scale] for p in f], np.float32) for f in res.face_landmarks]


def faces(rgb, kacheln: bool = True) -> list[np.ndarray]:
    """Gesichter als Arrays mit 478 Punkten (x, y) in Bildpixeln, größtes zuerst.
    Zusätzlich Suche in 3x3 überlappenden Kacheln, damit auch kleine Gesichter
    (Ganzkörper, Gruppen) gefunden werden; Doppelte werden zusammengefasst."""
    H, W = rgb.shape[:2]
    s = min(1.0, 2000 / max(H, W))
    small = cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else rgb
    found = _detect(small, scale=s)
    if kacheln:
        th, tw = int(H * 0.4), int(W * 0.4)
        for fy in (0.0, 0.3, 0.6):
            for fx in (0.0, 0.3, 0.6):
                y0, x0 = int(H * fy), int(W * fx)
                tile = rgb[y0:y0 + th, x0:x0 + tw]
                ts = min(1.0, 1024 / max(tile.shape[:2]))
                t = cv2.resize(tile, None, fx=ts, fy=ts, interpolation=cv2.INTER_AREA) if ts < 1 else tile
                found += _detect(t, x0, y0, ts)
    out = []
    for p in sorted(found, key=lambda q: -np.ptp(q[:, 0])):
        c = p.mean(0); fw = np.ptp(p[:, 0])
        if all(np.hypot(*(c - o.mean(0))) > 0.5 * max(fw, np.ptp(o[:, 0])) for o in out):
            out.append(p)
    return out


def person_boxes(fs, shape):
    """Grobe Personenbereiche unter jedem Gesicht (für die Schräglage: Kleidung zählt nicht)."""
    H, W = shape[:2]; out = []
    for p in fs:
        x0, y0 = p.min(0); x1, y1 = p.max(0); fw = x1 - x0; cx = (x0 + x1) / 2
        out.append((max(0.0, cx - 2.2 * fw), max(0.0, y0 - 0.6 * (y1 - y0)), min(float(W), cx + 2.2 * fw), float(H)))
    return out


def face_boxes(fs):
    """(x, y, w, h) je Gesicht: Stirn bis Kinn, Ohr bis Ohr."""
    out = []
    for p in fs:
        x0, y0 = p.min(0); x1, y1 = p.max(0)
        out.append((float(x0), float(y0), float(x1 - x0), float(y1 - y0)))
    return out


def main_faces(fs):
    """Nur Gesichter, die mindestens 45 % so breit sind wie das größte (keine Passanten)."""
    if not fs:
        return []
    big = np.ptp(fs[0][:, 0])
    return [p for p in fs if np.ptp(p[:, 0]) >= 0.45 * big]


def subject_box(shape, fs):
    h, w = shape[:2]
    if not fs:
        return None
    bx = face_boxes(fs)
    x0 = min(b[0] + b[2] / 2 - 1.5 * b[2] for b in bx); x1 = max(b[0] + b[2] / 2 + 1.5 * b[2] for b in bx)
    y0 = min(b[1] - 0.35 * b[3] for b in bx)
    eyes = min(float(p[[33, 263], 1].mean()) for p in fs)
    fh = float(np.mean([b[3] for b in bx]))
    return dict(x0=max(0.0, x0), x1=min(float(w), x1), y0=max(0.0, y0), y1=float(h), cx=(x0 + x1) / 2,
                eyes=eyes, ganz=fh < 0.13 * h)


# ---------- Zuschnitt ----------
def best_crop(w, h, deg, subj, forced=None):
    vx, vy, vw, vh = valid_rect(w, h, deg)
    if subj is None or forced == 'original':
        r = w / h; cw = min(vw, vh * r); ch = cw / r
        return dict(format='original', x=w / 2 - cw / 2, y=h / 2 - ch / 2, w=cw, h=ch)
    cands = [forced] if forced else (['3:2', '4:3', '1:1', '4:5', '3:4'] if w > h else ['2:3', '3:4', '4:5', '1:1'])
    sw_abs = subj['x1'] - subj['x0']; best = None
    for a in cands:
        r = ASPECTS[a]; cmax = min(vw, vh * r)
        for k in (1.0, 0.92, 0.85, 0.78, 0.7, 0.62, 0.55):
            cw = cmax * k; ch = cw / r
            if cw < sw_abs * 1.15:
                break
            x = min(max(subj['cx'] - cw / 2, vx), vx + vw - cw)
            off = abs(x + cw / 2 - subj['cx']) / cw
            y = subj['eyes'] - 0.33 * ch
            y = min(y, subj['y0'] - 0.05 * ch)
            if subj['ganz']:
                y = max(y, vy + vh - ch)
            y = max(vy, min(y, vy + vh - ch))
            kopf = y <= subj['y0']
            unten = (not subj['ganz']) or y + ch >= vy + vh - 1
            sw = sw_abs / cw; ziel = 0.28 if subj['ganz'] else 0.5
            score = (cw * ch / (w * h)) ** 0.8
            score *= math.exp(-((sw - ziel) ** 2) / (2 * 0.2 ** 2))
            score *= math.exp(-max(0.0, off - 0.02) * 20)
            if not kopf:
                score *= 0.2
            if not unten:
                score *= 0.3
            if best is None or score > best['score']:
                best = dict(format=a, x=x, y=y, w=cw, h=ch, score=round(score, 3), motivanteil=round(sw, 2))
    return best or best_crop(w, h, deg, None)


# ---------- Effekte ----------
def vignette(f, s):
    h, w = f.shape[:2]; y, x = np.ogrid[-1:1:h * 1j, -1:1:w * 1j]
    return f * (1 - s * np.clip((x ** 2 + y ** 2) / 2, 0, 1) ** 1.5)[..., None]


def effect(f, kind: str):
    if kind == 'bw':
        lum = np.clip((f @ np.array([0.25, 0.65, 0.10], np.float32) - 0.03) / 0.95, 0, 1)
        lum = np.clip(0.5 + (lum - 0.5) * 1.18, 0, 1) ** 1.05
        grain = np.random.default_rng(1).normal(0, 0.012, lum.shape).astype(np.float32)
        return vignette(np.clip(np.repeat(lum[..., None], 3, 2) + grain[..., None], 0, 1), 0.3)
    if kind == 'film':
        out = 0.05 + 0.92 * f; lum = out.mean(2, keepdims=True)
        out = np.clip(out + (lum - 0.5) * np.array([0.06, 0, -0.06], np.float32), 0, 1)
        hsv = cv2.cvtColor(out.astype(np.float32), cv2.COLOR_RGB2HSV); hsv[..., 1] *= 0.85
        return vignette(np.clip(cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB), 0, 1), 0.2)
    if kind == 'glow':
        b = cv2.GaussianBlur(f, (0, 0), 12)
        return vignette(np.clip(0.65 * f + 0.35 * (1 - (1 - f) * (1 - b)), 0, 1), 0.25)
    if kind == 'clarity':
        # CLAHE auf 16-Bit-L, nur wo Struktur ist (Himmel und glatte Wände bleiben unverändert)
        lab = cv2.cvtColor(f.astype(np.float32), cv2.COLOR_RGB2LAB); L = lab[..., 0]
        L16 = np.clip(L / 100 * 65535, 0, 65535).astype(np.uint16)
        c = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8)).apply(L16).astype(np.float32) / 65535 * 100
        mu = cv2.GaussianBlur(L, (0, 0), 6)
        sd = np.sqrt(np.maximum(cv2.GaussianBlur(L * L, (0, 0), 6) - mu * mu, 0))
        lab[..., 0] = L + (c - L) * smoothstep(1.0, 4.0, sd)
        out = np.clip(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB), 0, 1)
        hsv = cv2.cvtColor(out, cv2.COLOR_RGB2HSV)
        s = hsv[..., 1]; hsv[..., 1] = np.clip(s + 0.25 * s * (1 - s), 0, 1)
        return np.clip(cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB), 0, 1)
    raise ValueError(f'unbekannter Effekt: {kind} (bw, film, glow, clarity)')


# ---------- Retusche ----------
def _parts():
    from mediapipe.tasks.python.vision import FaceLandmarksConnections as C
    idx = lambda conns: sorted({c.start for c in conns} | {c.end for c in conns})  # noqa: E731
    adj = {}
    for c in C.FACE_LANDMARKS_FACE_OVAL:
        adj.setdefault(c.start, []).append(c.end); adj.setdefault(c.end, []).append(c.start)
    start = C.FACE_LANDMARKS_FACE_OVAL[0].start; seq = [start]; prev = None; cur = start
    while True:
        nxt = [n for n in adj[cur] if n != prev]
        if not nxt or nxt[0] == start or len(seq) > len(adj):
            break
        prev, cur = cur, nxt[0]; seq.append(cur)
    return dict(oval=seq, eyes=[idx(C.FACE_LANDMARKS_LEFT_EYE), idx(C.FACE_LANDMARKS_RIGHT_EYE)],
                brows=[idx(C.FACE_LANDMARKS_LEFT_EYEBROW), idx(C.FACE_LANDMARKS_RIGHT_EYEBROW)],
                lips=idx(C.FACE_LANDMARKS_LIPS))


def skin_mask(img, pts):
    P = _parts(); h, w = img.shape[:2]; fw = float(np.ptp(pts[:, 0]))
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [pts[P['oval']].astype(np.int32)], 255)

    def cut(ix, grow):
        hull = cv2.convexHull(pts[ix].astype(np.int32)).reshape(-1, 2).astype(np.float32)
        c = hull.mean(0); cv2.fillPoly(m, [((hull - c) * grow + c).astype(np.int32)], 0)
    for ix in P['eyes']:
        cut(ix, 1.6)
    for ix in P['brows']:
        cut(ix, 1.35)
    cut(P['lips'], 1.15)
    for i in (98, 327):
        cv2.circle(m, tuple(int(v) for v in pts[i]), int(fw * 0.035), 0, -1)
    ycc = cv2.cvtColor(img, cv2.COLOR_RGB2YCrCb)
    skin = ((ycc[..., 1] > 133) & (ycc[..., 1] < 180) & (ycc[..., 2] > 77) & (ycc[..., 2] < 135)).astype(np.uint8) * 255
    m = cv2.bitwise_and(m, cv2.morphologyEx(skin, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)))
    # Bart, Stoppeln, Haarsträhnen: deutlich mehr Feinstruktur als glatte Haut
    L = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)
    hp = L - cv2.GaussianBlur(L, (0, 0), max(1.0, fw * 0.003))
    tex = cv2.GaussianBlur(hp * hp, (0, 0), fw * 0.012)
    if (m > 0).any():
        ref = np.percentile(tex[m > 0], 40)
        beard = (tex > 3.0 * ref).astype(np.uint8) * 255
        beard = cv2.morphologyEx(beard, cv2.MORPH_CLOSE, np.ones((int(fw * 0.03) | 1,) * 2, np.uint8))
        beard = cv2.dilate(beard, np.ones((int(fw * 0.02) | 1,) * 2, np.uint8))
        m = cv2.bitwise_and(m, cv2.bitwise_not(beard))
    k = max(3, int(fw * 0.01) | 1)
    m = cv2.erode(m, np.ones((k, k), np.uint8))
    soft = cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), fw * 0.012)
    return m, soft, fw


def blemishes(lab, m, fw):
    L, a = lab[..., 0].astype(np.float32), lab[..., 1].astype(np.float32)
    r = int(fw * 0.045) | 1
    Lb = cv2.medianBlur(lab[..., 0], r).astype(np.float32); ab = cv2.medianBlur(lab[..., 1], r).astype(np.float32)
    cand = ((a - ab > 7) & (Lb - L > 3)) | (Lb - L > 18) | (a - ab > 12)
    cand = (cand & (m > 0)).astype(np.uint8)
    n, lbl, st, _ = cv2.connectedComponentsWithStats(cand, 8)
    out = np.zeros_like(cand); amin, amax = (fw * 0.004) ** 2, (fw * 0.045) ** 2; cnt = 0
    for i in range(1, n):
        _, _, bw, bh, ar = st[i]
        if amin <= ar <= amax and max(bw, bh) <= 2.5 * min(bw, bh) + 2 and ar >= 0.45 * bw * bh:
            out[lbl == i] = 1; cnt += 1
    d = max(3, int(fw * 0.008) | 1)
    return cv2.dilate(out, np.ones((d, d), np.uint8)), cnt


def retouch(img, fs, staerke: float = 1.0):
    """Dezente Hautretusche je Gesicht: Flecken entfernen, Rötung -40 %, minimal weichzeichnen."""
    out = img.astype(np.float32); info = []
    for pts in fs:
        m, soft, fw = skin_mask(img, pts)
        if m.sum() == 0:
            continue
        x0, y0 = np.maximum(pts.min(0) - fw * 0.2, 0).astype(int)
        x1, y1 = np.minimum(pts.max(0) + fw * 0.2, img.shape[1::-1]).astype(int)
        sl = (slice(y0, y1), slice(x0, x1))
        roi = np.clip(out[sl], 0, 255).astype(np.uint8); mr, sr = m[sl], soft[sl][..., None]
        lab = cv2.cvtColor(roi, cv2.COLOR_RGB2LAB)
        bm, cnt = blemishes(lab, mr, fw)
        healed = roi
        if cnt:
            healed = cv2.inpaint(roi, bm * 255, max(3, int(fw * 0.01)), cv2.INPAINT_TELEA)
            hp = roi.astype(np.float32) - cv2.GaussianBlur(roi.astype(np.float32), (0, 0), 1.2)
            noise = np.random.default_rng(0).normal(0, float(hp.std()) * 0.6, hp.shape).astype(np.float32)
            bmf = cv2.GaussianBlur(bm.astype(np.float32), (0, 0), 1.5)[..., None]
            healed = np.clip(healed.astype(np.float32) + noise * bmf, 0, 255).astype(np.uint8)
        lab = cv2.cvtColor(healed, cv2.COLOR_RGB2LAB).astype(np.float32)
        aref = np.median(lab[..., 1][mr > 0])
        lab[..., 1] -= 0.4 * staerke * np.maximum(0, lab[..., 1] - aref - 2) * sr[..., 0]
        Lc = lab[..., 0]
        low = cv2.bilateralFilter(Lc, 0, 6, fw * 0.012)
        fine = Lc - cv2.GaussianBlur(Lc, (0, 0), 1.0)
        smooth = cv2.GaussianBlur(low, (0, 0), 1.0) + 0.75 * fine
        lab[..., 0] = Lc + 0.35 * staerke * (smooth - Lc) * sr[..., 0]
        res = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32)
        wgt = sr
        if cnt:
            wgt = np.maximum(sr, cv2.GaussianBlur(bm.astype(np.float32), (0, 0), 1.5)[..., None])
        out[sl] = out[sl] * (1 - wgt) + res * wgt
        info.append(dict(gesichtsbreite=int(fw), flecken=int(cnt)))
    return np.clip(out, 0, 255).astype(np.uint8), info


# ---------- Vorschauen ----------
def grid_preview(rgb, deg=0.0, crop=None, lines=12, max_side=1000, label=''):
    """Bild (optional gedreht), Ausschnitt hell, Rest abgedunkelt, Hilfslinien."""
    s = max_side / max(rgb.shape[:2])
    p = cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else rgb.copy()
    s = min(s, 1.0)
    if deg:
        p = rotate(p, deg)
    p = np.ascontiguousarray(p)
    h, w = p.shape[:2]
    if crop:
        x, y, cw, ch = (int(v * s) for v in (crop['x'], crop['y'], crop['w'], crop['h']))
        d = (p * 0.35).astype(np.uint8); d[y:y + ch, x:x + cw] = p[y:y + ch, x:x + cw]; p = d
        for i in (1, 2):
            cv2.line(p, (x + i * cw // 3, y), (x + i * cw // 3, y + ch), (255, 255, 0), 1)
            cv2.line(p, (x, y + i * ch // 3), (x + cw, y + i * ch // 3), (255, 255, 0), 1)
        cv2.line(p, (x + cw // 2, y), (x + cw // 2, y + ch), (255, 0, 0), 1)
    if lines:
        for i in range(1, lines):
            cv2.line(p, (i * w // lines, 0), (i * w // lines, h), (0, 255, 255), 1)
        for i in range(1, max(2, lines * h // max(w, 1))):
            yy = i * w // lines
            if yy < h:
                cv2.line(p, (0, yy), (w, yy), (255, 0, 255), 1)
    if label:
        cv2.rectangle(p, (0, 0), (min(w, 12 + 9 * len(label)), 22), (0, 0, 0), -1)
        cv2.putText(p, label, (5, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return p


def contact_sheet(items, cols=6, cell=300):
    """items: [(name, rgb)] -> RGB-Bogen mit Dateinamen."""
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (cell + 8), rows * (cell + 24)), 'white'); d = ImageDraw.Draw(sheet)
    for i, (name, img) in enumerate(items):
        t = Image.fromarray(img); t.thumbnail((cell, cell))
        x = (i % cols) * (cell + 8); y = (i // cols) * (cell + 24)
        sheet.paste(t, (x + 4, y + 2)); d.text((x + 6, y + cell + 6), name, fill='black')
    return np.asarray(sheet)


def side_by_side(imgs, height=600):
    ts = [Image.fromarray(i) for i in imgs]
    ts = [t.resize((max(1, int(t.width * height / t.height)), height)) for t in ts]
    W = sum(t.width for t in ts) + 8 * (len(ts) - 1); s = Image.new('RGB', (W, height), 'white'); x = 0
    for t in ts:
        s.paste(t, (x, 0)); x += t.width + 8
    return np.asarray(s)
