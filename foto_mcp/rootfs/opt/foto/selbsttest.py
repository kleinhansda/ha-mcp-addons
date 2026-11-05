#!/usr/bin/env python3
"""Funktionstest für mcp-selftest: spricht den Server über stdio an, wie Claude es tut.

  selbsttest.py <arbeitsordner>

Prüft Schräglage (synthetisches, um 2° gedrehtes Gitter: Senkrechte; Meer mit Horizont: Horizont),
Gesichtsmodell (lädt, 0 Gesichter auf einer leeren Fläche), Objekt- und Szenenmodell, Sichtung mit
Kontaktbogen und Bildtyp, optimieren als Job mit Ergebnisdatei und Protokoll, anpassen mit Rezept,
Rezept nicht überschreiben, Pfadgrenze.
Rückgabewert 0 = alles in Ordnung.
"""
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np

import szene

root = sys.argv[1]
os.makedirs(os.path.join(root, 'test'), exist_ok=True)

# Gitter aus Linien, um +2° (gegen den Uhrzeigersinn) gekippt -> Messung muss etwa -2° ergeben
img = np.full((1600, 2400, 3), 200, np.uint8)
for x in range(200, 2400, 200):
    cv2.line(img, (x, 100), (x, 1500), (40, 40, 40), 6)
for y in range(200, 1600, 300):
    cv2.line(img, (100, y), (2300, y), (60, 60, 60), 4)
M = cv2.getRotationMatrix2D((1200, 800), 2.0, 1.0)
img = cv2.warpAffine(img, M, (2400, 1600), borderValue=(200, 200, 200))
cv2.imwrite(os.path.join(root, 'test', 'gitter.jpg'), img, [cv2.IMWRITE_JPEG_QUALITY, 92])

# Meer mit Horizont, um +2° gekippt -> Horizont, etwa -2°
rng = np.random.default_rng(3); H, W = 1600, 2400; hy = int(0.45 * H)
meer = np.zeros((H, W, 3), np.float32)
t = np.linspace(0, 1, hy)[:, None, None]
meer[:hy] = (1 - t) * np.array([225, 140, 90]) + t * np.array([235, 200, 170])  # BGR
meer[hy:] = np.array([115, 65, 25], np.float32) + rng.normal(0, 5, (H - hy, W, 1))
for y in range(hy + 20, H, 37):
    meer[y:y + 2] += 12
meer = cv2.warpAffine(np.clip(meer, 0, 255).astype(np.uint8), M, (W, H), flags=cv2.INTER_CUBIC,
                      borderMode=cv2.BORDER_REFLECT)
os.makedirs(os.path.join(root, 'meer'), exist_ok=True)
cv2.imwrite(os.path.join(root, 'meer', 'meer.jpg'), meer, [cv2.IMWRITE_JPEG_QUALITY, 92])

srv = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), 'server.py'), '--root', root],
                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
nid = 0


def call(method, params=None):
    global nid
    nid += 1
    srv.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': nid, 'method': method, 'params': params or {}}) + '\n')
    srv.stdin.flush()
    while True:
        msg = json.loads(srv.stdout.readline())
        if msg.get('id') == nid:
            return msg


def tool(name, args):
    r = call('tools/call', {'name': name, 'arguments': args})['result']
    return r, [c for c in r['content'] if c['type'] == 'text'], [c for c in r['content'] if c['type'] == 'image']


fails = []


def check(ok, msg):
    print(('ok    ' if ok else 'FEHLER ') + 'foto: ' + msg, flush=True)
    if not ok:
        fails.append(msg)


call('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'selbsttest', 'version': '1'}})

r, t, _ = tool('neigung_messen', {'dateien': ['test/gitter.jpg']})
res = json.loads(t[0]['text'])[0]
check(abs(res['winkel'] + 2.0) < 0.3 and res['quelle'], f"Schräglage {res['winkel']}° ({res['quelle']}), erwartet etwa -2°")
check(res['gesichter'] == 0, f"Gesichtsmodell geladen, {res['gesichter']} Gesichter auf dem Gitter")

m = szene.modelle()
check(m['objekte'] and m['szene'], f'Objekt- und Szenenmodell geladen ({m})')

r, t, _ = tool('neigung_messen', {'dateien': ['meer/meer.jpg']})
res = json.loads(t[0]['text'])[0]
check(res['quelle'] == 'horizont' and abs(res['winkel'] + 2.0) < 0.3,
      f"Horizont {res['winkel']}° ({res['quelle']}), erwartet etwa -2° aus dem Horizont")
check(res.get('bildtyp') in szene.TYPEN, f"Bildtyp {res.get('bildtyp')} ({res.get('begruendung')})")

r, t, im = tool('ordner_sichten', {'ordner': 'test'})
sicht = json.loads(t[0]['text'])
check(not r['isError'] and len(im) == 1 and sicht['bilder'] == 1 and 'typ' in sicht['details'][0],
      'Sichtung mit Kontaktbogen und Bildtyp')

r, t, _ = tool('vorschau', {'bilder': [{'datei': 'test/gitter.jpg', 'winkel': -2}]})
check(not r['isError'], 'Vorschau mit Hilfslinien')

r, t, _ = tool('optimieren', {'dateien': ['test/gitter.jpg'], 'effekte': {'gitter': ['bw']}})
jid = json.loads(t[0]['text'])['job_id']
for _ in range(600):
    r, t, im = tool('job_status', {'job_id': jid})
    st = json.loads(t[0]['text'])
    if st['status'] == 'fertig':
        break
    time.sleep(0.5)
erg = (st.get('ergebnisse') or [{}])[0]
check(st['status'] == 'fertig' and not st['fehler'] and abs(erg.get('winkel', 9) + 2.0) < 0.3,
      f"Job optimieren: {st['status']}, Winkel {erg.get('winkel')}, Fehler {st['fehler']}")
check(os.path.isfile(os.path.join(root, 'test', 'final', 'gitter_final.jpg'))
      and os.path.isfile(os.path.join(root, 'test', 'final', 'gitter_bw.jpg')), 'Ergebnisdateien in test/final')
check(os.path.isfile(os.path.join(root, 'test', 'gitter.jpg')), 'Original unverändert vorhanden')
check(erg.get('typ') in szene.TYPEN and len(st.get('protokoll_dateien') or []) == 1
      and os.path.isfile(os.path.join(root, st['protokoll_dateien'][0])) and len(t) >= 2 and '## ' in t[1]['text'],
      f"Protokoll geschrieben ({st.get('protokoll_dateien')}), Bildtyp {erg.get('typ')}")

r, t, _ = tool('rezept_speichern', {'name': 'test', 'rezept': {'anpassen': {'struktur': 20, 'himmel': {'helligkeit': -10}},
                                                               'effekte': ['tonal']}})
check(not r['isError'], 'Rezept gespeichert')
r, t, _ = tool('rezept_speichern', {'name': 'test', 'rezept': {'anpassen': {'waerme': 5}}})
check(r['isError'] and 'schon' in t[0]['text'], 'Vorhandenes Rezept wird ohne ueberschreiben nicht ersetzt')
r, t, _ = tool('anpassen', {'dateien': ['meer/meer.jpg'], 'rezept': 'test', 'anpassen': {'kontrast': 10}})
jid = json.loads(t[0]['text'])['job_id']
for _ in range(600):
    r, t, im = tool('job_status', {'job_id': jid})
    st = json.loads(t[0]['text'])
    if st['status'] == 'fertig':
        break
    time.sleep(0.5)
check(st['status'] == 'fertig' and not st['fehler']
      and os.path.isfile(os.path.join(root, 'meer', 'meer_angepasst.jpg'))
      and os.path.isfile(os.path.join(root, 'meer', 'meer_tonal.jpg')),
      f"Job anpassen mit Rezept und Bereich Himmel: {st['status']}, Fehler {st['fehler']}")
r, t, _ = tool('anpassen', {'dateien': ['meer/meer.jpg'], 'anpassen': {'struktuur': 5}})
check(r['isError'] and 'struktuur' in t[0]['text'], 'Unbekannter Regler wird abgelehnt')

r, t, _ = tool('vorschau', {'bilder': [{'datei': '../../etc/passwd'}]})
check(r['isError'] and 'außerhalb' in t[0]['text'], 'Zugriff außerhalb des Arbeitsordners abgelehnt')

srv.stdin.close(); srv.wait(timeout=10)
sys.exit(1 if fails else 0)
