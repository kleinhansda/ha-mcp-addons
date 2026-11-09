#!/usr/bin/env python3
"""Prüft die neuesten Releases aller MCP-Server, von mcp-auth-proxy, Open WebUI und Open Terminal.

Quellen und wo ihre Version steht:
  storytold/vectorcraft, photocraft, pdfcraft,  artcraft_mcp/Dockerfile (ARG …_VERSION)
    cadcraft, wordcraft, deckcraft, gridcraft,
    figcraft, craft-anything
  github/github-mcp-server                     github_mcp/Dockerfile (ARG GITHUB_MCP_VERSION)
  @netlify/mcp (npm)                           netlify_mcp/package.json + package-lock.json
  sigbit/mcp-auth-proxy                        jedes Dockerfile (ARG PROXY_VERSION, PROXY_SHA256_*)
  open-webui/open-webui                        open_webui/Dockerfile (ARG OPEN_WEBUI_VERSION)
  open-webui/open-terminal                     open_terminal/Dockerfile (ARG OPEN_TERMINAL_VERSION)

Für jedes betroffene Add-on wird die Version in config.yaml erhöht und ein Eintrag in
CHANGELOG.md ergänzt. Ein Release wird nur übernommen, wenn es Linux-Dateien für arm64 und
x86_64 enthält.

Open WebUI und Open Terminal kommen als fertiges Image (ghcr.io). Ihre Add-on-Version folgt der
Version des Images (z. B. 0.13.0, eigene Änderungen danach 0.13.0-1). Ob das Image für beide
Architekturen existiert, zeigt erst der Build im Workflow.

Schreibt changed, addons, mcp_addons, image_addons und summary nach $GITHUB_OUTPUT (falls gesetzt).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

STORYTOLD = [
    # (Repo, ARG-Name, Paketname, Anzeigename)
    ("storytold/vectorcraft", "VECTORCRAFT_VERSION", "vectorcraft", "VectorCraft"),
    ("storytold/photocraft", "PHOTOCRAFT_VERSION", "photocraft", "PhotoCraft"),
    ("storytold/pdfcraft", "PDFCRAFT_VERSION", "pdfcraft-cli", "PdfCraft"),
    ("storytold/cadcraft", "CADCRAFT_VERSION", "cadcraft", "CADCraft"),
    ("storytold/wordcraft", "WORDCRAFT_VERSION", "wordcraft", "WordCraft"),
    ("storytold/deckcraft", "DECKCRAFT_VERSION", "deckcraft", "DeckCraft"),
    ("storytold/gridcraft", "GRIDCRAFT_VERSION", "gridcraft", "GridCraft"),
    ("storytold/figcraft", "FIGCRAFT_VERSION", "figcraft", "FigCraft"),
    ("storytold/craft-anything", "CRAFT_ANYTHING_VERSION", "craft-anything", "Craft Anything"),
]
# Add-ons, deren Version der Version eines fertigen Images folgt:
# (Add-on, Repo, ARG-Name, Anzeigename)
UPSTREAM_IMAGES = [
    ("open_webui", "open-webui/open-webui", "OPEN_WEBUI_VERSION", "Open WebUI"),
    ("open_terminal", "open-webui/open-terminal", "OPEN_TERMINAL_VERSION", "Open Terminal"),
]
PROXY_ARCHES = {"PROXY_SHA256_ARM64": "linux-arm64", "PROXY_SHA256_AMD64": "linux-amd64"}


def http_get(url: str, api: bool = False) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ha-addons-update"})
    if api:
        req.add_header("Accept", "application/vnd.github+json")
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def latest_release(repo: str) -> dict:
    return json.loads(http_get(f"https://api.github.com/repos/{repo}/releases/latest", api=True))


def npm_latest(pkg: str) -> str:
    return json.loads(http_get(f"https://registry.npmjs.org/{pkg}/latest"))["version"]


def read_arg(text: str, name: str) -> str:
    m = re.search(rf"^ARG {name}=(\S+)$", text, re.M)
    if not m:
        sys.exit(f"ARG {name} nicht gefunden")
    return m.group(1)


def set_arg(text: str, name: str, value: str) -> str:
    return re.sub(rf"^ARG {name}=\S+$", f"ARG {name}={value}", text, count=1, flags=re.M)


class Repo:
    """Hält geänderte Dateien im Speicher, bis alles geprüft ist."""

    def __init__(self) -> None:
        self.files: dict[Path, str] = {}
        self.changes: dict[str, list[str]] = defaultdict(list)
        self.upstream: dict[str, str] = {}   # Add-on → neue Image-Version

    def read(self, rel: str) -> str:
        p = ROOT / rel
        return self.files.get(p, p.read_text())

    def write(self, rel: str, text: str) -> None:
        self.files[ROOT / rel] = text

    def note(self, addon: str, msg: str) -> None:
        self.changes[addon].append(msg)


def check_storytold(r: Repo) -> None:
    rel = "artcraft_mcp/Dockerfile"
    docker = r.read(rel)
    for repo, arg, pkg, label in STORYTOLD:
        new = latest_release(repo)["tag_name"].lstrip("v")
        old = read_arg(docker, arg)
        if new == old:
            continue
        sums = http_get(f"https://github.com/{repo}/releases/download/v{new}/SHA256SUMS.txt").decode()
        missing = [a for a in ("aarch64", "x86_64") if f"  {pkg}-{new}-linux-{a}.tar.gz" not in sums]
        if missing:
            print(f"{label} {new}: Pakete fehlen für {', '.join(missing)}, bleibt bei {old}")
            continue
        docker = set_arg(docker, arg, new)
        r.note("artcraft_mcp", f"{label} {old} → {new}")
    r.write(rel, docker)


def check_github_mcp(r: Repo) -> None:
    rel = "github_mcp/Dockerfile"
    docker = r.read(rel)
    new = latest_release("github/github-mcp-server")["tag_name"].lstrip("v")
    old = read_arg(docker, "GITHUB_MCP_VERSION")
    if new == old:
        return
    base = f"https://github.com/github/github-mcp-server/releases/download/v{new}"
    sums = http_get(f"{base}/github-mcp-server_{new}_checksums.txt").decode()
    missing = [a for a in ("arm64", "x86_64") if f"  github-mcp-server_Linux_{a}.tar.gz" not in sums]
    if missing:
        print(f"github-mcp-server {new}: Dateien fehlen für {', '.join(missing)}, bleibt bei {old}")
        return
    r.write(rel, set_arg(docker, "GITHUB_MCP_VERSION", new))
    r.note("github_mcp", f"github-mcp-server {old} → {new}")


def check_netlify(r: Repo) -> None:
    rel = "netlify_mcp/package.json"
    pkg = json.loads(r.read(rel))
    old = pkg["dependencies"]["@netlify/mcp"]
    new = npm_latest("@netlify/mcp")
    if new == old:
        return
    pkg["dependencies"]["@netlify/mcp"] = new
    r.write(rel, json.dumps(pkg, indent=2, ensure_ascii=False) + "\n")
    r.note("netlify_mcp", f"@netlify/mcp {old} → {new}")


def semver(v: str) -> tuple[int, int, int] | None:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v)
    return tuple(map(int, m.groups())) if m else None


def check_upstream_images(r: Repo) -> None:
    for addon, repo, arg, label in UPSTREAM_IMAGES:
        rel = f"{addon}/Dockerfile"
        docker = r.read(rel)
        old = read_arg(docker, arg)
        release = latest_release(repo)
        new = release["tag_name"].lstrip("v")
        if semver(new) is None or semver(old) is None:
            print(f"{label}: Version {new!r} bzw. {old!r} nicht im Format x.y.z, übersprungen")
            continue
        if semver(new) <= semver(old):
            continue
        r.write(rel, set_arg(docker, arg, new))
        r.note(addon, f"{label} {old} → {new}, [Release-Notes]({release['html_url']})")
        if addon == "open_webui":
            r.note(addon, "Vor dem Update ein Backup anlegen lassen: Datenbank-Migrationen lassen "
                          "sich nicht rückgängig machen")
        r.upstream[addon] = new


def check_proxy(r: Repo) -> None:
    rel_new = latest_release("sigbit/mcp-auth-proxy")
    new = rel_new["tag_name"].lstrip("v")
    assets = {a["name"]: a for a in rel_new.get("assets", [])}
    digests: dict[str, str] | None = None
    for dockerfile in sorted(ROOT.glob("*/Dockerfile")):
        rel = str(dockerfile.relative_to(ROOT))
        docker = r.read(rel)
        if "ARG PROXY_VERSION=" not in docker:
            continue
        old = read_arg(docker, "PROXY_VERSION")
        if new == old:
            continue
        if digests is None:
            digests = {}
            for arg, suffix in PROXY_ARCHES.items():
                asset = assets.get(f"mcp-auth-proxy-{suffix}")
                if not asset:
                    print(f"mcp-auth-proxy {new}: Datei für {suffix} fehlt, bleibt bei {old}")
                    return
                digest = (asset.get("digest") or "").removeprefix("sha256:")
                if not re.fullmatch(r"[0-9a-f]{64}", digest):
                    digest = hashlib.sha256(http_get(asset["browser_download_url"])).hexdigest()
                digests[arg] = digest
        docker = set_arg(docker, "PROXY_VERSION", new)
        for arg, digest in digests.items():
            docker = set_arg(docker, arg, digest)
        r.write(rel, docker)
        r.note(dockerfile.parent.name, f"mcp-auth-proxy {old} → {new}")


def zahlen(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def bump(r: Repo, addon: str, changes: list[str]) -> str:
    rel = f"{addon}/config.yaml"
    config = r.read(rel)
    if addon in r.upstream:
        # Version folgt dem Image; eigene Änderungen zählen mit einer vierten Stelle (.1, .2 …).
        # Keine Endung -N: Home Assistant hält 0.17.3-1 für eine Vorabversion, also für älter als 0.17.3.
        m = re.search(r'^version: "([^"]+)"$', config, re.M)
        version = r.upstream[addon]
        if m and zahlen(version) <= zahlen(m.group(1)):
            sys.exit(f"{addon}: neue Upstream-Version {version} ist nicht größer als {m.group(1)}, bitte von Hand setzen")
    else:
        m = re.search(r'^version: "(\d+)\.(\d+)\.(\d+)"$', config, re.M)
        if m:
            major, minor, patch = map(int, m.groups())
            version = f"{major}.{minor}.{patch + 1}"
    if not m:
        sys.exit(f"version in {rel} nicht gefunden")
    r.write(rel, config.replace(m.group(0), f'version: "{version}"', 1))

    rel = f"{addon}/CHANGELOG.md"
    log = r.read(rel)
    entry = f"## {version} ({dt.date.today().isoformat()})\n\n" + "".join(f"- {c}\n" for c in changes) + "\n"
    head, sep, rest = log.partition("\n## ")
    r.write(rel, f"{head.rstrip()}\n\n{entry}" + (f"## {rest}" if sep else ""))
    return version


def main() -> int:
    r = Repo()
    check_storytold(r)
    check_github_mcp(r)
    check_netlify(r)
    check_proxy(r)
    check_upstream_images(r)

    out = os.environ.get("GITHUB_OUTPUT")
    if not r.changes:
        print("Keine neuen Versionen.")
        if out:
            with open(out, "a") as f:
                f.write("changed=false\n")
        return 0

    parts = []
    for addon in sorted(r.changes):
        version = bump(r, addon, r.changes[addon])
        parts.append(f"{addon} {version} ({', '.join(r.changes[addon])})")

    for path, text in r.files.items():
        if path.read_text() != text:
            path.write_text(text)

    if "netlify_mcp" in r.changes and any("@netlify/mcp" in c for c in r.changes["netlify_mcp"]):
        subprocess.run(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
                       cwd=ROOT / "netlify_mcp", check=True)

    summary = "Neue Versionen: " + "; ".join(parts)
    print(summary)
    images = {a for a, *_ in UPSTREAM_IMAGES}
    mcp = sorted(a for a in r.changes if a not in images)
    img = sorted(a for a in r.changes if a in images)
    if out:
        with open(out, "a") as f:
            f.write(f"changed=true\naddons={' '.join(sorted(r.changes))}\n"
                    f"mcp_addons={' '.join(mcp)}\nimage_addons={' '.join(img)}\nsummary={summary}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
