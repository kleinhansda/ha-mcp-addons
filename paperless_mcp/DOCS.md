# Paperless MCP

Macht dein [Paperless-ngx](https://docs.paperless-ngx.com)-Archiv für LLM-Clients wie Open WebUI
nutzbar: Dokumente per Volltext und Filter suchen, den OCR-Text lesen, die erste Seite als Bild
ansehen, ähnliche Dokumente finden und, wenn erlaubt, Tags, Titel und Notizen pflegen oder neue
Dateien hochladen. Öffentlich hinter [mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy)
mit Login über deinen OIDC-Anbieter (z. B. Pocket ID), intern optional ohne Login.

Warum ein Werkzeug und keine „Externe Wissensquelle“ in Open WebUI: Diese bindet nur
Vektor-Datenbanken (Qdrant, Milvus, pgvector) an, Paperless hat eine eigene Volltextsuche. Das
Modell sucht hier selbst, mit Filtern nach Korrespondent, Typ, Tag und Datum, und liest dann
gezielt die passenden Dokumente. Kein zweiter Datenbestand, neue Dokumente sind sofort auffindbar.

## Werkzeuge

| Werkzeug | Zweck |
|---|---|
| `paperless_search` | Volltext (Wörter, „Phrasen“, `rechn*`, `AND/OR/NOT`, `correspondent:…`) plus Filter: Tags, ohne Tags, Korrespondent, Dokumenttyp, Datum von/bis (auch nur Jahr), hinzugefügt ab, Titel, ASN. Treffer mit ID, Titel, Datum, Namen statt IDs, Textauszug und Link |
| `paperless_get_document` | Metadaten, benutzerdefinierte Felder, Notizen und OCR-Text, lange Texte in Teilen |
| `paperless_preview` | erste Seite als Bild, z. B. für Scans ohne Text oder für Vision-Modelle |
| `paperless_similar` | inhaltlich ähnliche Dokumente |
| `paperless_list` | Tags, Korrespondenten, Dokumenttypen, Speicherpfade, Felder mit Anzahl Dokumenten |
| `paperless_update_document` | Titel, Datum, Korrespondent, Typ, ASN, Tags hinzufügen/entfernen (optional neu anlegen) |
| `paperless_add_note` | Notiz anhängen („bezahlt am …“) |
| `paperless_upload` | Datei aus `/share` oder base64 ablegen, Paperless macht OCR und Zuordnung |

Die letzten drei gibt es nur mit **Nur lesen: aus**. Datei und OCR-Text eines Dokuments ändert
der Server nie, gelöscht wird nichts. `/share` ist nur lesend eingebunden und dient allein als
Quelle für `paperless_upload`.

Filter nehmen Namen (ohne Groß-/Kleinschreibung, auch Teilnamen, solange eindeutig) oder IDs.

## Voraussetzungen

- Paperless-ngx, z. B. das Add-on von BenoitAnastay (Hostname `ca5234a0-paperless-ngx`, Port 80).
- Ein **API-Token**: in Paperless oben rechts Profil → API-Token erzeugen. Der Server hat genau
  die Rechte dieses Nutzers. Für reines Nachschlagen am besten einen eigenen Nutzer mit
  Leserechten anlegen (Einstellungen → Benutzer & Gruppen), Token dann für diesen Nutzer.
- Für den öffentlichen Zugang: ein OIDC-Client beim Anbieter, Callback
  `https://<hostname>/.auth/oidc/callback`, und ein HTTPS-Hostname, z. B. über Cloudflared.
  Für Open WebUI auf demselben Gerät reicht `internal_access`.

## Installation

1. **Paperless MCP** aus „didi's Apps“ installieren.
2. API-Token eintragen, `internal_access` einschalten, starten.
3. Im Log prüfen: `Paperless http://ca5234a0-paperless-ngx erreichbar, Token gültig` und
   `paperless: intern ohne Login unter http://<hostname>:9080/mcp`.
4. **Open WebUI:** Admin → Einstellungen → Integrationen → `+`, Typ **MCP (Streamable HTTP)**,
   URL `http://be60cb4b-paperless-mcp:9080/mcp`, Authentifizierung **Keine**.

> **Achtung bei `internal_access`:** Jede App im internen Docker-Netz kann dann ohne Login in
> deinem Archiv suchen und Dokumente lesen (Verträge, Bescheide, Kontoauszüge). Mit
> „Nur lesen: aus“ auch Metadaten ändern und hochladen. Ein Token mit reinen Leserechten begrenzt
> das unabhängig von der Einstellung.

## Konfiguration

| Option | Bedeutung |
|---|---|
| `internal_access` | Zusätzlich intern ohne Login unter Port 9080 |
| `paperless_url` | Interne Adresse von Paperless (Standard `http://ca5234a0-paperless-ngx`) |
| `paperless_token` | API-Token |
| `public_ui_url` | Optional, Adresse der Weboberfläche für Links in Treffern |
| `read_only` | Standard an: nur suchen, lesen, ansehen |
| `public` | Öffentliche URL und OIDC-Felder, wie bei den anderen MCP-Apps |

## Tipps für das Modell

Im System-Prompt oder Skill hilft ein Satz wie: „Fragen zu Verträgen, Rechnungen, Bescheiden
und Briefen beantwortest du mit dem Paperless-Archiv: erst `paperless_search` (bei Bedarf mit
`paperless_list` die richtigen Namen holen), dann `paperless_get_document`, und du nennst
Titel, Datum und Link des Dokuments als Beleg.“
