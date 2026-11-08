# Vorlagen für Modelle im Terminal

Bewährte, getestete Skripte als Ausgangspunkt. Nur lesen: in den Projektordner kopieren und dort
anpassen.

| Datei | Zweck | Paketgruppe |
|---|---|---|
| `3d/teil.py` | Teil mit build123d, Export STEP und STL, Prüfansichten als SVG, Prüfwerte | `3d` |

Neue Vorlagen gehören ins Repo unter `open_terminal/rootfs/usr/local/share/vorlagen/` und
bekommen einen Test in `.github/workflows/build.yml` (Job `vorlagen`).
