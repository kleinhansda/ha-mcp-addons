#!/usr/bin/env python3
"""Kopiert die gemeinsamen Dateien aus common/ in jedes Add-on.

Home Assistant baut jedes Add-on nur aus seinem eigenen Ordner, gemeinsame Dateien
müssen deshalb als Kopie darin liegen. Quelle ist immer common/.

  python3 .github/scripts/sync_common.py          Kopien aktualisieren
  python3 .github/scripts/sync_common.py --check  nur prüfen (Build), Fehler bei Abweichung
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = {
    "common/run.sh": "rootfs/run.sh",
    "common/mcp-selftest": "rootfs/usr/local/bin/mcp-selftest",
    "common/mcp_bridge.py": "rootfs/usr/local/lib/mcp/mcp_bridge.py",
}


def addons() -> list[Path]:
    # Nur MCP-Add-ons (erkennbar an services.sh) nutzen run.sh und mcp-selftest.
    # Andere Apps wie Open WebUI haben ein eigenes Startskript.
    return sorted(
        p.parent
        for p in ROOT.glob("*/config.yaml")
        if (p.parent / "rootfs/usr/local/lib/mcp/services.sh").exists()
    )


def main() -> int:
    check = "--check" in sys.argv
    bad = []
    for addon in addons():
        for src, rel in FILES.items():
            want = (ROOT / src).read_bytes()
            dst = addon / rel
            have = dst.read_bytes() if dst.exists() else None
            if have == want:
                continue
            if check:
                bad.append(str(dst.relative_to(ROOT)))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(want)
                dst.chmod(0o755)
                print(f"aktualisiert: {dst.relative_to(ROOT)}")
    if bad:
        print("Weicht von common/ ab (sync_common.py ausführen):\n  " + "\n  ".join(bad))
        return 1
    print("Gemeinsame Dateien sind in allen Add-ons gleich: " + ", ".join(a.name for a in addons()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
