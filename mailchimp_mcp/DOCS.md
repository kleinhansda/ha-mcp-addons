# Mailchimp MCP

Macht dein Mailchimp-Konto für LLM-Clients wie Open WebUI nutzbar: Zielgruppen und Kontakte
nachschlagen, Kampagnen und ihre Berichte (Öffnungen, Klicks) auswerten und, wenn erlaubt,
Kampagnen-Entwürfe anlegen und Testmails schicken. Server ist
[mailchimp-mcp](https://github.com/damientilman/mailchimp-mcp-server) (MIT) von Damien Tilman.
Öffentlich hinter [mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy) mit Login über
deinen OIDC-Anbieter, intern optional ohne Login.

Warum nicht der offizielle Server von Mailchimp (`https://ai-inc.mailchimp.com/claude/mcp/v2`):
Dessen OAuth-Anmeldung leitet nach dem Login zu ChatGPT bzw. Claude weiter und lässt Open WebUI
nicht zu.

## Umfang

| Umfang | Werkzeuge | Schreiben |
|---|---|---|
| `lesen` (Standard) | Konto, Zielgruppen, Kontakte suchen, Segmente, Kampagnen suchen/lesen, Berichte, Klicks, Öffnungen, Versand-Checkliste, Vorlagen (20) | gesperrt |
| `entwuerfe` | wie `lesen` plus `create_campaign`, `update_campaign`, `set_campaign_content`, `replicate_campaign`, `send_test_email` | nur Entwürfe und Testmails, **kein Versand** |
| `alle` | alle rund 230 Werkzeuge, auch `send_campaign`, `schedule_campaign`, Kontakte und Zielgruppen löschen | alles |

`alle` ist für kleine Modelle zu viel: Jede Werkzeugbeschreibung kostet bei jeder Anfrage Tokens.
Besser `entwuerfe` und einzelne Werkzeuge unter **Weitere Werkzeuge** ergänzen, z. B.
`schedule_campaign` oder `tag_member`. Die Namen zeigt das Werkzeug `describe_tools` bei Umfang
`alle` oder die [Projektseite](https://github.com/damientilman/mailchimp-mcp-server).

**Probelauf:** Schreibende Werkzeuge liefern nur eine Vorschau dessen, was sie tun würden.

## Voraussetzungen

- Ein **API-Schlüssel**: Mailchimp → Profil → Extras → API-Schlüssel → Schlüssel erstellen.
  Er gibt vollen Zugriff auf das Konto; die Einschränkung macht allein der Umfang dieser App.
- Für den öffentlichen Zugang: ein OIDC-Client beim Anbieter, Callback
  `https://<hostname>/.auth/oidc/callback`, und ein HTTPS-Hostname, z. B. über Cloudflared.
  Für Open WebUI auf demselben Gerät reicht `internal_access`.

## Installation

1. **Mailchimp MCP** aus „didi's Apps“ installieren.
2. API-Schlüssel eintragen, `internal_access` einschalten, ein `internal_token` setzen, starten.
3. Im Log prüfen: `Mailchimp erreichbar, API-Schlüssel gültig` und
   `mailchimp: intern … unter http://<hostname>:9080/mcp`.
4. **Open WebUI:** Admin → Einstellungen → Integrationen → `+`, Typ **MCP (Streamable HTTP)**,
   URL `http://be60cb4b-mailchimp-mcp:9080/mcp`, Authentifizierung **Bearer** mit dem
   `internal_token`.

> **Achtung bei `internal_access`:** Jede App im internen Docker-Netz, die das Token kennt, kann
> Kontakte (personenbezogene Daten) und Kampagnen lesen, je nach Umfang auch Entwürfe anlegen oder
> versenden.

## Konfiguration

| Option | Bedeutung |
|---|---|
| `api_key` | Mailchimp-API-Schlüssel `<schlüssel>-<rechenzentrum>` |
| `scope` | `lesen`, `entwuerfe` oder `alle`, siehe oben |
| `extra_tools` | weitere Werkzeugnamen, kommagetrennt |
| `dry_run` | Probelauf für schreibende Werkzeuge |
| `internal_access`, `internal_token` | interner Zugang ohne Login, mit Token |
| `public` | öffentliche URL und OIDC für mcp-auth-proxy |
