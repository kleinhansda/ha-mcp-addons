#!/usr/bin/env python3
"""Funktionstest für mcp-selftest: spricht den Server über stdio an, wie Claude es tut.

  selbsttest.py <arbeitsordner>

Prüft Schräglage (synthetisches, um 2° gedrehtes Gitter), Gesichtsmodell (lädt, 0 Gesichter auf
einer leeren Fläche), Sichtung mit Kontaktbogen, optimieren als Job mit Ergebnisdatei, Pfadgrenze.
Rückgabewert 0 = alles in Ordnung.
"""
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np

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

r, t, im = tool('ordner_sichten', {'ordner': 'test'})
check(not r['isError'] and len(im) == 1 and json.loads(t[0]['text'])['bilder'] == 1, 'Sichtung mit Kontaktbogen')

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

r, t, _ = tool('vorschau', {'bilder': [{'datei': '../../etc/passwd'}]})
check(r['isError'] and 'außerhalb' in t[0]['text'], 'Zugriff außerhalb des Arbeitsordners abgelehnt')

srv.stdin.close(); srv.wait(timeout=10)
sys.exit(1 if fails else 0)
