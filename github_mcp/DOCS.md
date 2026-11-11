# GitHub MCP

Der offizielle [github-mcp-server](https://github.com/github/github-mcp-server) als
Remote-Connector für Claude, auch für die Smartphone-App. Davor sitzt
[mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy) als OAuth-Server mit Login über
deinen OIDC-Anbieter (z. B. Pocket ID). Der Server arbeitet mit deinem eigenen Token, also mit
genau den Rechten, die du ihm gibst.

Hintergrund (warum nicht der gehostete Server, Token-Rechte, Risiken):
[docs/GITHUB.md](https://github.com/kleinhansda/ha-mcp-addons/blob/main/docs/GITHUB.md).
Gemeinsames Muster aller Add-ons:
[docs/ARCHITEKTUR.md](https://github.com/kleinhansda/ha-mcp-addons/blob/main/docs/ARCHITEKTUR.md).

## Voraussetzungen

- Ein OIDC-Client beim Anbieter, Callback `https://<hostname>/.auth/oidc/callback`, Public client aus.
- Ein öffentlicher HTTPS-Hostname, z. B. über das Cloudflared-Add-on.
- Ein Fine-grained Personal Access Token (Rechte siehe docs/GITHUB.md).
- **Branch-Schutz** (Ruleset mit Pull-Request-Pflicht) in jedem Repo, in dem Claude schreiben darf.

## Installation

1. Einstellungen → Apps (Add-ons) → App Store → ⋮ → Repositories:
   `https://github.com/kleinhansda/ha-mcp-addons`
2. **GitHub MCP** installieren, Konfiguration ausfüllen, starten.
3. Im Log prüfen: Versionen, `Toolsets: …`, `github: öffentlich auf Port 8080 für …` bzw. `github: intern ohne Login unter …` und
   `GitHub MCP Server running on stdio`.

## Konfiguration

URL und OIDC-Felder (`external_url`, `oidc_*`) stehen im aufklappbaren Abschnitt
„Öffentlicher Zugang (Claude-App)“ (`public`). Für rein internen Zugriff bleibt er leer.

| Option | Bedeutung |
|---|---|
| `oidc_configuration_url` | Discovery-URL, z. B. `https://id.example.com/.well-known/openid-configuration`. OIDC ist nur mit `external_url` nötig |
| `oidc_provider_name` | Name auf der Anmeldeseite |
| `oidc_client_id`, `oidc_client_secret` | OIDC-Client |
| `oidc_allowed_users` | Optional, kommagetrennt (Standard: E-Mail-Adresse) |
| `external_url` | Öffentliche Adresse ohne Pfad, z. B. `https://github-mcp.example.com`. Leer = kein öffentlicher Zugang |
| `internal_access` | Zusätzlich intern ohne Login erreichbar, siehe [Interner Zugriff](#interner-zugriff-ohne-login-z-b-open-webui) |
| `github_token` | Fine-grained Personal Access Token |
| `toolsets` | z. B. `default`, `all` oder `default,actions,gists`. Leer = Standard des Servers |
| `read_only` | `true` schaltet alle schreibenden Tools ab |
| `gh_host` | Nur für GitHub Enterprise |
| `legacy_auth_dir` | Nur beim Umzug von einem Docker-Stack: Ordner mit den alten Proxy-Daten, wird einmalig übernommen |

## Tunnel

Hostname wie in `external_url`, Pfad leer, Dienst-URL `http://<add-on-hostname>:8080`. Den
Add-on-Hostnamen zeigt Home Assistant auf der Info-Seite der App. Keine Access-App davor.

## Claude verbinden

Claude → Einstellungen → Connectors → Add custom connector, URL `https://<hostname>/mcp`,
keine Client-ID. Beim Verbinden öffnet sich die Anmeldung des OIDC-Anbieters.

Den gehosteten GitHub-Connector in Claude danach entfernen, sonst gibt es die Tools doppelt.

## Interner Zugriff ohne Login (z. B. Open WebUI)

Mit `internal_access: true` ist der Server zusätzlich **ohne Anmeldung** im internen Docker-Netz
von Home Assistant erreichbar, für Clients auf demselben Gerät wie Open WebUI. Die öffentliche
URL mit Login kann daneben weiterlaufen oder leer bleiben; ohne sie ist kein OIDC nötig.

- Adresse: `http://<repo-hash>-github-mcp:9080/mcp`, z. B. `http://be60cb4b-github-mcp:9080/mcp`. Das Log
  zeigt sie beim Start (`… intern ohne Login unter …`).
- Port 9080 (öffentlicher Port + 1000) steht nicht unter **Netzwerk** und wird nie auf den Host
  gelegt, ist also aus dem Heimnetz nicht erreichbar.
- In Open WebUI: Admin-Bereich → Einstellungen → Integrationen → **+**, Typ *MCP Streamable
  HTTP*, URL wie oben, Authentifizierung *Keine*.
- Läuft beides, sind es zwei getrennte Prozesse des Servers.

**Sicherheit:** Jede App im internen Netz (alle Apps, Home Assistant selbst, Apps mit
Host-Netzwerk) kann den Server dann ohne Login nutzen. Wer intern zugreift, arbeitet mit **deinem GitHub-Token** und dessen Rechten. Für den internen Zugang ein eigenes, eng begrenztes Token (nur die nötigen Repos, kurze Laufzeit) und `read_only: true` erwägen. Anfragen aus dem Browser (mit
`Origin`-Header) werden abgelehnt.

## Fehlerbehebung

| Symptom | Ursache | Lösung |
|---|---|---|
| `403 Resource not accessible by personal access token` | Token-Recht fehlt oder Repo nicht freigegeben | Token-Rechte und Repository access prüfen |
| 401 bei jedem Aufruf | Token abgelaufen oder widerrufen | Neuen Token eintragen, App neu starten |
| Tool fehlt in Claude | Toolset nicht aktiviert | `toolsets` erweitern, z. B. `default,actions` |
| Schreiben geht nicht, Lesen schon | `read_only` ist an | Option prüfen |

Fehlerbilder des Proxys (Login, Tunnel): docs/ARCHITEKTUR.md.
