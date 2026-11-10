#!/usr/bin/env python3
"""mailchimp-mcp plus drei Werkzeuge für große Newsletter.

Kampagnen-HTML ist schnell 100 KB groß. Ein Modell kann das weder vollständig lesen noch als
Werkzeug-Argument zurückschicken (Ausgabelimit, ungültiges JSON). Diese Werkzeuge arbeiten
deshalb serverseitig:

- find_in_campaign_content: Fundstellen mit Umgebung, damit das Modell exakte Textstücke kennt.
- replace_in_campaign_content: gezielte Ersetzungen im HTML, alles oder nichts, dann speichern.
- upload_file_from_share: Bild aus /share in den Mailchimp File Manager laden (statt Base64).

Die Werkzeuge nutzen Anfragen, Lese- und Probelauf-Schutz und Konten von mailchimp-mcp.
Schreibende Werkzeuge gibt es nur, wenn der Server nicht schreibgeschützt ist.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path

from mailchimp_mcp_server import server as s

try:
    from mcp.types import ToolAnnotations
except ImportError:  # pragma: no cover
    ToolAnnotations = None

SHARE = Path(os.environ.get("MAILCHIMP_SHARE", "/share"))
MAX_BILD = 10 * 1024 * 1024
PRUEF_PAUSE = float(os.environ.get("MAILCHIMP_VERIFY_DELAY", "6"))
BILDTYPEN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}


def ersetzen(html: str, ersetzungen: list[dict]) -> tuple[str, list[dict]]:
    """Wendet Ersetzungen der Reihe nach an. Jede muss genau einmal passen, außer all=true.

    Mit regex=true ist 'old' ein regulärer Ausdruck (Python re), z. B. für lange IDs:
    'tmeid=[A-Za-z0-9%=_-]+'. Gibt (neues_html, Protokoll) zurück oder wirft ValueError mit
    allen Problemen, ohne etwas zu ändern (alles oder nichts)."""
    probleme, protokoll = [], []
    for i, e in enumerate(ersetzungen, 1):
        alt, neu, alle = e.get("old", ""), e.get("new", ""), bool(e.get("all", False))
        if not alt:
            probleme.append(f"#{i}: 'old' ist leer")
            continue
        if e.get("regex"):
            try:
                muster = re.compile(alt, re.S)
            except re.error as x:
                probleme.append(f"#{i}: ungültiger regulärer Ausdruck ({x}): {alt[:80]!r}")
                continue
            treffer = [m.group(0) for m in muster.finditer(html)]
            n = len(treffer)
        else:
            n = html.count(alt)
        if n == 0:
            probleme.append(f"#{i}: nicht gefunden: {alt[:80]!r}")
            continue
        if n > 1 and not alle:
            beispiele = f", Treffer z. B. {[x[:60] for x in treffer[:3]]}" if e.get("regex") else ""
            probleme.append(f"#{i}: {n} Treffer, genauer fassen oder all=true setzen: {alt[:80]!r}{beispiele}")
            continue
        if e.get("regex"):
            html = muster.sub(lambda m: neu, html)
        else:
            html = html.replace(alt, neu)
        protokoll.append({"nr": i, "treffer": n})
    if probleme:
        raise ValueError("; ".join(probleme))
    return html, protokoll


def pruefen(html: str, ersetzungen: list[dict]) -> list[dict]:
    """Prüft nach dem Speichern, ob jedes 'new' im gespeicherten HTML steht."""
    fehlt = []
    for i, e in enumerate(ersetzungen, 1):
        neu = e.get("new", "")
        if neu and neu not in html:
            fehlt.append({"nr": i, "new": neu[:80]})
    return fehlt


def fundstellen(text: str, suche: str, umgebung: int, maximal: int = 20) -> list[dict]:
    treffer, start = [], 0
    while len(treffer) < maximal:
        p = text.find(suche, start)
        if p < 0:
            break
        a, b = max(0, p - umgebung), min(len(text), p + len(suche) + umgebung)
        treffer.append({"position": p, "ausschnitt": text[a:b]})
        start = p + max(1, len(suche))
    return treffer


def _registrieren(fn, risiko: str):
    s.mcp.tool()(fn)
    s.TOOL_RISK[fn.__name__] = risiko
    if ToolAnnotations is not None:
        for t in s.mcp._tool_manager.list_tools():
            if t.name == fn.__name__:
                t.annotations = ToolAnnotations(readOnlyHint=risiko == "read",
                                                destructiveHint=False, idempotentHint=False)


def _html(campaign_id: str, account: str | None):
    data = s.mc_request(f"/campaigns/{campaign_id}/content", account=account)
    if isinstance(data, dict) and "error" in data:
        return None, data
    return data.get("html") or "", None


def find_in_campaign_content(campaign_id: str, text: str, context: int = 150, account: str | None = None) -> str:
    """Find text in a campaign's full HTML (not truncated) and return each match with surrounding HTML.

    Use before replace_in_campaign_content to copy exact 'old' snippets (dates, names, links,
    image URLs) instead of reading the whole HTML via get_campaign_content.

    Args:
        campaign_id: Campaign ID (e.g. from replicate_campaign).
        text: Exact text to search for (case-sensitive), e.g. '18.09.' or 'Rico Bravo' or 'mcusercontent.com'.
        context: Characters of HTML shown before and after each match (default 150, max 1000).

    Returns:
        JSON with html_length, count and up to 20 matches {position, ausschnitt}.
    """
    html, fehler = _html(campaign_id, account)
    if fehler:
        return json.dumps(fehler, indent=2)
    t = fundstellen(html, text, max(0, min(int(context), 1000)))
    info = s.mc_request(f"/campaigns/{campaign_id}", params={"fields": "status,content_type"}, account=account)
    return json.dumps({"campaign_id": campaign_id, "html_length": len(html),
                       "content_type": info.get("content_type") if isinstance(info, dict) else None,
                       "count": html.count(text), "matches": t}, indent=2, ensure_ascii=False)


def replace_in_campaign_content(campaign_id: str, replacements: list[dict], account: str | None = None) -> str:
    """Replace text snippets in a campaign draft's HTML on the server and save it (all or nothing).

    Use instead of set_campaign_content for large newsletters: only the changed snippets are sent.
    Find exact snippets first with find_in_campaign_content. Layout, styles and merge tags stay
    untouched. The campaign must be a draft ('save'). Send a test email afterwards.

    Args:
        campaign_id: Campaign ID of the draft.
        replacements: List of {"old": ..., "new": ..., "all": false, "regex": false}. Each 'old'
            must match exactly once unless "all": true. With "regex": true, 'old' is a Python
            regular expression - use it for long IDs or URLs you cannot copy exactly, e.g.
            {"old": "tmeid=[A-Za-z0-9%=_-]+", "new": "tmeid=NEW", "regex": true}. Applied in order.
            If any entry fails, nothing is saved and all problems are reported.

    Returns:
        JSON with status, per-entry match counts and HTML length. After saving, the content is
        read back: status "content_updated" only if every 'new' is present; otherwise
        "not_applied" with the entries Mailchimp did not keep (e.g. campaigns from the new
        email builder can ignore API HTML) - then do not send a test email, report it.
    """
    if not isinstance(replacements, list) or not replacements:
        return json.dumps({"error": "replacements muss eine nicht leere Liste sein"}, indent=2)
    html, fehler = _html(campaign_id, account)
    if fehler:
        return json.dumps(fehler, indent=2)
    try:
        neu, protokoll = ersetzen(html, replacements)
    except ValueError as e:
        return json.dumps({"error": f"Nichts gespeichert: {e}"}, indent=2, ensure_ascii=False)
    if (guard := s._guard_write(action="replace in campaign content", campaign_id=campaign_id,
                                replacements=len(replacements), account=account)):
        return guard
    r = s.mc_request(f"/campaigns/{campaign_id}/content", body={"html": neu}, method="PUT", account=account)
    if isinstance(r, dict) and "error" in r:
        return json.dumps(r, indent=2)
    # Zweimal zurücklesen: sofort und nach einer Pause. Kampagnen aus dem neuen E-Mail-Builder
    # zeigen das gesendete HTML kurz an und stellen danach den Builder-Inhalt wieder her.
    sofort, fehler = _html(campaign_id, account)
    if not fehler and PRUEF_PAUSE > 0:
        time.sleep(PRUEF_PAUSE)
        spaeter, fehler = _html(campaign_id, account)
    else:
        spaeter = sofort
    if fehler:
        return json.dumps({"status": "saved_unverified", "campaign_id": campaign_id, "read_back_error": fehler},
                          indent=2, ensure_ascii=False)
    fehlt = pruefen(spaeter, replacements)
    info = s.mc_request(f"/campaigns/{campaign_id}", params={"fields": "status,content_type"}, account=account)
    ctype = info.get("content_type") if isinstance(info, dict) else None
    ergebnis = {"status": "not_applied" if fehlt else "content_updated", "campaign_id": campaign_id,
                "replacements": protokoll, "missing_after_save": fehlt, "content_type": ctype,
                "html_length_before": len(html), "html_length_sent": len(neu),
                "html_length_read_back": len(sofort), "html_length_after_pause": len(spaeter)}
    if fehlt:
        ergebnis["hint"] = ("Mailchimp hat die Änderung nicht dauerhaft übernommen"
                            + (" (sofort sichtbar, nach der Pause zurückgesetzt)" if not pruefen(sofort, replacements) else "")
                            + ". Typisch für Kampagnen aus dem neuen E-Mail-Builder: Inhalt dort im Mailchimp-Editor ändern "
                              "oder als Vorlage eine Kampagne im klassischen Editor/Code-Editor verwenden. Nicht wiederholen, "
                              "keine Testmail.")
    return json.dumps(ergebnis, indent=2, ensure_ascii=False)


def upload_file_from_share(path: str, name: str | None = None, folder_id: str | None = None,
                           account: str | None = None) -> str:
    """Upload an image (or PDF) from the shared folder /share to the Mailchimp File Manager.

    Use instead of upload_file: no base64 needed. Then put the returned full_size_url into the
    campaign HTML with replace_in_campaign_content.

    Args:
        path: Absolute path under /share (e.g. '/share/hannesbraeu/poster/2026-11-27_band/newsletter.jpg')
            or relative to /share. png, jpg, gif, webp or pdf, max 10 MB.
        name: File name shown in Mailchimp (default: the file's name).
        folder_id: Optional folder ID from list_file_folders.

    Returns:
        JSON with id, name, full_size_url, width, height, size.
    """
    p = Path(path)
    p = (p if p.is_absolute() else SHARE / p).resolve()
    if SHARE.resolve() not in p.parents:
        return json.dumps({"error": f"Nur Dateien unter {SHARE} erlaubt: {path}"}, indent=2)
    if not p.is_file():
        return json.dumps({"error": f"Datei nicht gefunden: {p}"}, indent=2)
    if p.suffix.lower() not in BILDTYPEN:
        return json.dumps({"error": f"Dateityp {p.suffix} nicht erlaubt ({', '.join(sorted(BILDTYPEN))})"}, indent=2)
    if p.stat().st_size > MAX_BILD:
        return json.dumps({"error": f"Datei größer als 10 MB ({p.stat().st_size} Bytes)"}, indent=2)
    name = name or p.name
    if (guard := s._guard_write(action="upload file from share", name=name, path=str(p),
                                folder_id=folder_id, account=account)):
        return guard
    body = {"name": name, "file_data": base64.b64encode(p.read_bytes()).decode()}
    if folder_id:
        body["folder_id"] = int(folder_id)
    d = s.mc_request("/file-manager/files", body=body, method="POST", account=account)
    if isinstance(d, dict) and "error" in d:
        return json.dumps(d, indent=2)
    return json.dumps({k: d.get(k) for k in ("id", "name", "full_size_url", "width", "height", "size")}, indent=2)


_registrieren(find_in_campaign_content, "read")
if not s.READ_ONLY:
    _registrieren(replace_in_campaign_content, "write")
    _registrieren(upload_file_from_share, "write")


def main():
    s.mcp.run()


if __name__ == "__main__":
    main()
