# Vorlage: Teil mit build123d modellieren, als STEP und STL exportieren, Prüfansichten (SVG) und Prüfwerte.
# Liegt im Image unter /usr/local/share/vorlagen/3d/teil.py (nur lesen). In den Projektordner kopieren, Maße oben anpassen,
# ausführen; SVG mit rsvg-convert nach PNG, dann file_preview. AUS über die Umgebung VORLAGE_AUS änderbar.
import os
from pathlib import Path
from build123d import *
import trimesh

AUS = Path(os.environ.get("VORLAGE_AUS", "out")); AUS.mkdir(parents=True, exist_ok=True)
NAME = "halter"
# Maße in mm
L, B, H, WAND, LOCH = 60, 30, 20, 3, 5

with BuildPart() as p:
    Box(L, B, WAND, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations((L / 2 - WAND / 2, 0, 0)):
        Box(WAND, B, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations((-L / 4, 0, WAND)):
        Hole(LOCH / 2)
    fillet(p.edges().filter_by(Axis.Y).group_by(Axis.Z)[-1], radius=1)
teil = p.part

export_step(teil, str(AUS / f"{NAME}.step"))
export_stl(teil, str(AUS / f"{NAME}.stl"), tolerance=0.01, angular_tolerance=0.1)

# Prüfansichten als SVG (sichtbare und verdeckte Kanten)
ansichten = {"vorne": (0, -1, 0), "oben": (0, 0, 1), "rechts": (1, 0, 0), "iso": (1, -1, 0.8)}
for n, richtung in ansichten.items():
    sicht, verdeckt = teil.project_to_viewport(Vector(*richtung) * 500, viewport_up=(0, 0, 1) if n != "oben" else (0, 1, 0))
    gross = max(*Compound(children=sicht + verdeckt).bounding_box().size)
    svg = ExportSVG(scale=180 / gross, margin=5)
    svg.add_layer("sichtbar", line_weight=0.5)
    svg.add_layer("verdeckt", line_color=(140, 140, 140), line_type=LineType.ISO_DOT, line_weight=0.3)
    svg.add_shape(sicht, layer="sichtbar")
    svg.add_shape(verdeckt, layer="verdeckt")
    svg.write(str(AUS / f"{NAME}_{n}.svg"))

# Prüfwerte
bb = teil.bounding_box()
m = trimesh.load(AUS / f"{NAME}.stl")
print(f"Maße: {bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f} mm, Volumen {teil.volume/1000:.2f} cm³")
print(f"STL: {len(m.faces)} Dreiecke, geschlossen: {m.is_watertight}, Volumen {m.volume/1000:.2f} cm³")
