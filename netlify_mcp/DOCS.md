# Netlify MCP

Der offizielle Netlify-MCP-Server [@netlify/mcp](https://www.npmjs.com/package/@netlify/mcp)
als Remote-Connector für Claude, auch für die Smartphone-App. Davor sitzt
[mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy) als OAuth-Server mit Login über
deinen OIDC-Anbieter (z. B. Pocket ID).

Damit kann Claude Sites, Deploys und Deploy Previews sehen, Build-Logs lesen und
Umgebungsvariablen setzen. Zusammen mit GitHub MCP ergibt das einen Ablauf zur Pflege
statischer Websites über Pull Requests:
[docs/WEBSITE-PFLEGE.md](https://github.com/kleinhansda/ha-mcp-addons/blob/main/docs/WEBSITE-PFLEGE.md).

Hintergrund (Node-Version, Token):
[docs/NETLIFY.md](https://github.com/kleinhansda/ha-mcp-addons/blob/main/docs/NETLIFY.md).

## Voraussetzungen

- Ein OIDC-Client beim Anbieter, Callback `https://<hostname>/.auth/oidc/callback`, Public client aus.
- Ein öffentlicher HTTPS-Hostname, z. B. über das Cloudflared-Add-on.
- Ein Netlify Personal Access Token mit Ablaufdatum. Er gilt für alle Sites des Accounts.

## Installation

1. Einstellungen → Apps (Add-ons) → App Store → ⋮ → Repositories:
   `https://github.com/kleinhansda/ha-mcp-addons`
2. **Netlify MCP** installieren, Konfiguration ausfüllen, starten.
3. Im Log prüfen: Versionen (`@netlify/mcp`, `node`, `mcp-auth-proxy`) und
   `netlify: Start auf Port 8080 für …`.

## Konfiguration

| Option | Bedeutung |
|---|---|
| `oidc_configuration_url` | Discovery-URL, z. B. `https://id.example.com/.well-known/openid-configuration` |
| `oidc_provider_name` | Name auf der Anmeldeseite |
| `oidc_client_id`, `oidc_client_secret` | OIDC-Client |
| `oidc_allowed_users` | Optional, kommagetrennt (Standard: E-Mail-Adresse) |
| `external_url` | Öffentliche Adresse ohne Pfad, z. B. `https://netlify-mcp.example.com` |
| `netlify_token` | Personal Access Token |
| `legacy_auth_dir` | Nur beim Umzug von einem Docker-Stack: Ordner mit den alten Proxy-Daten, wird einmalig übernommen |

## Tunnel

Hostname wie in `external_url`, Pfad leer, Dienst-URL `http://<add-on-hostname>:8080`. Den
Add-on-Hostnamen zeigt Home Assistant auf der Info-Seite der App. Keine Access-App davor.

## Claude verbinden

Claude → Einstellungen → Connectors → Add custom connector, URL `https://<hostname>/mcp`,
keine Client-ID. Test: Claude nach den Sites des Accounts fragen (Tool `get-projects`).

## Fehlerbehebung

| Symptom | Ursache | Lösung |
|---|---|---|
| Tool-Aufrufe scheitern mit Auth-Fehler | Token abgelaufen oder widerrufen | Neuen Token eintragen, App neu starten |
| Tool `netlify-coding-rules` fehlt | Themenliste beim Start nicht aus dem Internet geladen | App neu starten |
| Log: `EBADENGINE`-Warnungen | Hinweise von npm zu Abhängigkeiten | Harmlos, solange der Server startet |

Fehlerbilder des Proxys (Login, Tunnel): docs/ARCHITEKTUR.md.
