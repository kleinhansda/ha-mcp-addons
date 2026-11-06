#!/usr/bin/env python3
"""Erzeugt icon.png und logo.png für alle Apps von didi's Apps im gemeinsamen Stil.

Stil: runder Badge in Dunkelblau, innen ein Ring und ein Symbol in Bernstein. Zwei Farben,
immer gleich, damit man die Apps im App-Store auf einen Blick erkennt. Die Symbole sind eigene,
schlichte Zeichnungen (keine Marken-Logos).

  python3 icons/make_icons.py      schreibt <app>/icon.png (256×256) und <app>/logo.png (500×200)

Braucht rsvg-convert (librsvg). Neue App: Eintrag in APPS ergänzen.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAVY = "#1B2B4B"
AMBER = "#F4B942"

# Symbole im Bereich 0–256, Mittelpunkt 128. Linien in Bernstein, Strichstärke über STROKE.
STROKE = 'fill="none" stroke="{c}" stroke-width="12" stroke-linecap="round" stroke-linejoin="round"'

GLYPHS = {
    # Ordner mit Dokument
    "files_mcp": """
      <path d="M66 98 V170 A10 10 0 0 0 76 180 H180 A10 10 0 0 0 190 170 V112 A10 10 0 0 0 180 102 H126 L112 86 H76 A10 10 0 0 0 66 96 Z" {s}/>
      <path d="M100 132 H156 M100 152 H140" {s}/>""",
    # Dokument mit Eselsohr und Lupe
    "paperless_mcp": """
      <path d="M82 70 H140 L170 100 V186 H82 Z M140 70 V100 H170" {s}/>
      <circle cx="124" cy="140" r="18" {s}/>
      <path d="M137 153 L156 172" {s}/>""",
    # Git-Verzweigung
    "github_mcp": """
      <path d="M104 92 V164 M160 116 C160 144 104 136 104 160" {s}/>
      <circle cx="104" cy="80" r="14" {s}/>
      <circle cx="104" cy="176" r="14" {s}/>
      <circle cx="160" cy="104" r="14" {s}/>""",
    # Wolke mit Pfeil nach oben (Veröffentlichen)
    "netlify_mcp": """
      <path d="M92 168 H84 A26 26 0 0 1 82 116 A36 36 0 0 1 150 100 A30 30 0 0 1 172 168 H164" {s}/>
      <path d="M128 182 V128 M106 148 L128 126 L150 148" {s}/>""",
    # Briefumschlag
    "mailbox_org_mcp": """
      <rect x="70" y="88" width="116" height="82" rx="10" {s}/>
      <path d="M76 96 L128 136 L180 96" {s}/>""",
    # Kamera
    "foto_mcp": """
      <path d="M78 104 H100 L110 88 H146 L156 104 H178 A10 10 0 0 1 188 114 V170 A10 10 0 0 1 178 180 H78 A10 10 0 0 1 68 170 V114 A10 10 0 0 1 78 104 Z" {s}/>
      <circle cx="128" cy="140" r="24" {s}/>""",
    # Zeichenfeder
    "artcraft_mcp": """
      <path d="M128 66 L166 120 L146 178 H110 L90 120 Z" {s}/>
      <path d="M128 66 V124" {s}/>
      <circle cx="128" cy="134" r="10" {s}/>
      <path d="M106 192 H150" {s}/>""",
    # Sprechblase mit drei Punkten
    "open_webui": """
      <path d="M84 86 H172 A14 14 0 0 1 186 100 V150 A14 14 0 0 1 172 164 H122 L96 186 V164 H84 A14 14 0 0 1 70 150 V100 A14 14 0 0 1 84 86 Z" {s}/>
      <circle cx="102" cy="125" r="7" fill="{c}"/>
      <circle cx="128" cy="125" r="7" fill="{c}"/>
      <circle cx="154" cy="125" r="7" fill="{c}"/>""",
    # Terminal
    "open_terminal": """
      <rect x="66" y="80" width="124" height="96" rx="12" {s}/>
      <path d="M94 112 L114 128 L94 144 M126 148 H160" {s}/>""",
}


def badge(glyph: str) -> str:
    g = glyph.replace("{s}", STROKE).replace("{c}", AMBER)
    return f"""<g>
    <circle cx="128" cy="128" r="124" fill="{NAVY}"/>
    <circle cx="128" cy="128" r="108" fill="none" stroke="{AMBER}" stroke-width="6"/>
    {g}
  </g>"""


def icon_svg(app: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">{badge(GLYPHS[app])}</svg>'


def logo_svg(app: str, name: str) -> str:
    # 500×200: Badge links, rechts Name und Absender. Transparenter Hintergrund, Text in
    # Dunkelblau mit Bernstein-Unterzeile, lesbar auf hellem und dunklem Theme durch die Pille.
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="500" height="200" viewBox="0 0 500 200">
  <rect x="4" y="4" width="492" height="192" rx="96" fill="{NAVY}"/>
  <g transform="translate(14 14) scale(0.671875)">{badge(GLYPHS[app])}</g>
  <text x="210" y="100" font-family="DejaVu Sans, sans-serif" font-size="{34 if len(name) <= 11 else 30 if len(name) <= 13 else 27}" font-weight="bold" fill="#FFFFFF">{name}</text>
  <text x="210" y="138" font-family="DejaVu Sans, sans-serif" font-size="22" fill="{AMBER}">didi's Apps</text>
</svg>"""


def render(svg: str, out: Path) -> None:
    subprocess.run(["rsvg-convert", "-o", str(out)], input=svg.encode(), check=True)


def main() -> int:
    import yaml  # nur hier nötig

    for app in GLYPHS:
        cfg = ROOT / app / "config.yaml"
        if not cfg.exists():
            print(f"übersprungen (fehlt): {app}", file=sys.stderr)
            continue
        name = yaml.safe_load(cfg.read_text())["name"]
        render(icon_svg(app), ROOT / app / "icon.png")
        render(logo_svg(app, name), ROOT / app / "logo.png")
        print(f"{app}: icon.png, logo.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
