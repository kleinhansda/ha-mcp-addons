# Änderungen

Neue Versionen von mcp-auth-proxy trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist. mailchimp-mcp und seine
Abhängigkeiten sind in `requirements.txt` fest eingetragen und werden von Hand aktualisiert.

## 1.2.0 (2026-11-10)

- Eigene Newsletter-Vorlagen statt Kampagnen aus dem neuen E-Mail-Builder (die per API nicht
  dauerhaft änderbar sind): `save_template_from_share` legt eine klassische Vorlage aus einer
  HTML-Datei in `/share` an oder aktualisiert sie und nennt die `mc:edit`-Bereiche;
  `set_campaign_template_content` füllt eine Kampagne aus Vorlage plus kleinen HTML-Stücken je
  Bereich und prüft das Ergebnis nach einer Pause.

## 1.1.2 (2026-11-10)

- `replace_in_campaign_content` liest zusätzlich nach einer Pause (`MAILCHIMP_VERIFY_DELAY`, Standard
  6 s) zurück. Kampagnen aus dem neuen E-Mail-Builder zeigen gesendetes HTML kurz an und stellen
  danach ihren Builder-Inhalt wieder her; 1.1.1 meldete das noch als `content_updated`. Jetzt
  `not_applied` mit Hinweis. `find_in_campaign_content` nennt den `content_type`.

## 1.1.1 (2026-11-10)

- `replace_in_campaign_content`: liest nach dem Speichern zurück und meldet `content_updated` nur,
  wenn jede Ersetzung im gespeicherten HTML steht, sonst `not_applied` mit den fehlenden Einträgen
  und dem `content_type` der Kampagne. Bisher wurde ein ignoriertes Speichern als Erfolg gemeldet.
- Ersetzungen mit `regex: true` für lange IDs und URLs, die ein Modell nicht exakt abschreiben kann
  (z. B. `tmeid=` in Google-Kalender-Links).

## 1.1.0 (2026-11-10)

- Neue Werkzeuge für große Newsletter (HTML um 100 KB, zu groß für `set_campaign_content` aus
  einem Modell): `find_in_campaign_content` (Fundstellen im vollständigen HTML),
  `replace_in_campaign_content` (gezielte Ersetzungen, alles oder nichts) und
  `upload_file_from_share` (Bild aus `/share` statt Base64). Schreibende nur ab Umfang `entwuerfe`.
- `/share` wird nur lesend eingebunden.

## 1.0.0 (2026-11-09)

- Erste Version: [mailchimp-mcp](https://github.com/damientilman/mailchimp-mcp-server) 1.2.0
  (MCP-SDK 1.30) mit drei Umfängen: **lesen** (Standard, ca. 20 Werkzeuge, Schreiben gesperrt),
  **entwuerfe** (zusätzlich Kampagnen-Entwürfe und Testmails, kein Versand) und **alle**.
- Probelauf, weitere Werkzeuge per Name, interner Zugriff mit Token über die Brücke, öffentlicher
  Zugang mit OIDC über mcp-auth-proxy.
