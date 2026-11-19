#!/usr/bin/env python3
"""Schreibt die requirements.txt der Foto-Bildbearbeitung mit Prüfsummen für aarch64 und amd64.

Liest die festen Versionen aus foto_mcp/requirements.in und schreibt je Ziel eine requirements.txt:
foto_mcp (Debian Bookworm, Python 3.11) und Open Terminal (Befehl foto, Python 3.12). Für jedes
Paket werden die Wheels beider Architekturen (manylinux) von PyPI geladen und deren SHA-256
eingetragen. Im Image installiert pip dann mit --require-hashes --no-deps genau diese Dateien.

  python3 .github/scripts/foto_lock.py          requirements.txt neu schreiben
  python3 .github/scripts/foto_lock.py --check  nur prüfen, ob requirements.txt passt
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IN = ROOT / "foto_mcp/requirements.in"
OT = ROOT / "open_terminal/rootfs/usr/local/share/foto"
ZIELE = {  # Ausgabe: (Python-Version, zusätzliche requirements.in nur für dieses Ziel)
    ROOT / "foto_mcp/requirements.txt": ("3.11", None),
    OT / "requirements.txt": ("3.12", OT / "requirements-terminal.in"),  # etikett: zxing-cpp
}
PLATFORMS = {
    "aarch64": ["manylinux_2_28_aarch64", "manylinux_2_17_aarch64", "manylinux2014_aarch64"],
    "amd64": ["manylinux_2_28_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"],
}


def pins(extra: Path | None = None) -> list[str]:
    out = []
    zeilen = IN.read_text().splitlines() + (extra.read_text().splitlines() if extra else [])
    for line in zeilen:
        line = line.split("#", 1)[0].strip()
        if line:
            if not re.fullmatch(r"[A-Za-z0-9_.\-]+==[A-Za-z0-9_.\-+]+", line):
                sys.exit(f"Keine feste Version: {line}")
            out.append(line)
    return out


def hashes(pin: str, py: str) -> list[str]:
    found = set()
    for arch, plats in PLATFORMS.items():
        with tempfile.TemporaryDirectory() as d:
            cmd = [sys.executable, "-m", "pip", "download", "-q", "--no-deps", "--only-binary=:all:",
                   "--python-version", py, "--implementation", "cp", "--abi", "cp" + py.replace(".", ""), "--abi", "abi3",
                   "--abi", "none", "-d", d, pin]
            for p in plats:
                cmd += ["--platform", p]
            cmd += ["--platform", "any"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            files = list(Path(d).iterdir())
            if r.returncode or not files:
                sys.exit(f"{pin}: kein Wheel für {arch}\n{r.stderr}")
            for f in files:
                found.add(hashlib.sha256(f.read_bytes()).hexdigest())
    return sorted(found)


def render(py: str, extra: Path | None) -> str:
    lines = ["# Erzeugt von .github/scripts/foto_lock.py aus requirements.in. Nicht von Hand ändern.\n"]
    for pin in pins(extra):
        hs = hashes(pin, py)
        lines.append(pin + "".join(f" \\\n    --hash=sha256:{h}" for h in hs) + "\n")
        print(pin, len(hs), "Prüfsumme(n)")
    return "".join(lines)


def main() -> int:
    if "--check" in sys.argv:
        fehler = 0
        for out, (_, extra) in ZIELE.items():
            names = {p.split("==")[0].lower() for p in pins(extra)}
            text = out.read_text() if out.exists() else ""
            have = {m.group(1).lower() for m in re.finditer(r"^([A-Za-z0-9_.\-]+)==", text, re.M)}
            pinned = set(re.findall(r"^([A-Za-z0-9_.\-]+==\S+)", text, re.M))
            if names != have or pinned != set(pins(extra)):
                print(f"{out.relative_to(ROOT)} passt nicht zu requirements.in (foto_lock.py ausführen)")
                fehler = 1
            else:
                print(f"{out.relative_to(ROOT)} passt zu requirements.in")
        return fehler
    for out, (py, extra) in ZIELE.items():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(py, extra))
    return 0


if __name__ == "__main__":
    sys.exit(main())
