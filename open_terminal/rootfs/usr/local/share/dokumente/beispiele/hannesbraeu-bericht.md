---
stil: hannesbraeu
art: bericht
title: Kesselfest 2027
untertitel: Planung, Ablauf und Aufgaben
autor: David
inhaltsverzeichnis: false
---

# Ausgangslage

Bis November liefen Whisper, Piper und openWakeWord auf dem Unraid-Server. Der Assistent **Hal** hing damit an einem Gerät, das nachts schläft.

## Ziel

Spracherkennung und Sprachausgabe laufen lokal auf Home Assistant; nur die Konversation geht an Scaleway.

| Baustein | vorher | nachher |
|---|---|---|
| Spracherkennung | Unraid, GPU | M920q, CPU |
| Sprachausgabe | Unraid | M920q |
| Weckwort | openWakeWord | auf dem Satelliten |

> Lokale Erkennung heißt: einfache Befehle funktionieren auch ohne Internet.

# Ergebnis

1. Apps installiert und konfiguriert
2. Assistenten umgestellt
3. Alte Einträge entfernt

```bash
docker compose config -q
```
