#!/usr/bin/env python3
"""Schreibt foto_mcp/requirements.txt mit Prüfsummen für aarch64 und amd64.

Liest die festen Versionen aus foto_mcp/requirements.in, lädt für jedes Paket die Wheels
beider Architekturen (Python 3.11, manylinux) von PyPI und trägt deren SHA-256 ein.
Im Image installiert pip dann mit --require-hashes --no-deps genau diese Dateien.

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
OUT = ROOT / "foto_mcp/requirements.txt"
PLATFORMS = {
    "aarch64": ["manylinux_2_28_aarch64", "manylinux_2_17_aarch64", "manylinux2014_aarch64"],
    "amd64": ["manylinux_2_28_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"],
}


def pins() -> list[str]:
    out = []
    for line in IN.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            if not re.fullmatch(r"[A-Za-z0-9_.\-]+==[A-Za-z0-9_.\-+]+", line):
                sys.exit(f"Keine feste Version: {line}")
            out.append(line)
    return out


def hashes(pin: str) -> list[str]:
    found = set()
    for arch, plats in PLATFORMS.items():
        with tempfile.TemporaryDirectory() as d:
            cmd = [sys.executable, "-m", "pip", "download", "-q", "--no-deps", "--only-binary=:all:",
                   "--python-version", "3.11", "--implementation", "cp", "--abi", "cp311", "--abi", "abi3",
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


def render() -> str:
    lines = ["# Erzeugt von .github/scripts/foto_lock.py aus requirements.in. Nicht von Hand ändern.\n"]
    for pin in pins():
        hs = hashes(pin)
        lines.append(pin + "".join(f" \\\n    --hash=sha256:{h}" for h in hs) + "\n")
        print(pin, len(hs), "Prüfsumme(n)")
    return "".join(lines)


def main() -> int:
    if "--check" in sys.argv:
        names = {p.split("==")[0].lower() for p in pins()}
        have = {m.group(1).lower() for m in re.finditer(r"^([A-Za-z0-9_.\-]+)==", OUT.read_text(), re.M)}
        pinned = set(re.findall(r"^([A-Za-z0-9_.\-]+==\S+)", OUT.read_text(), re.M))
        if names != have or pinned != set(pins()):
            print("requirements.txt passt nicht zu requirements.in (foto_lock.py ausführen)")
            return 1
        print("requirements.txt passt zu requirements.in")
        return 0
    OUT.write_text(render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
