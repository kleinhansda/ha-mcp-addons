# ArtCraft MCP

Macht VectorCraft, PhotoCraft und PdfCraft ([storytold](https://github.com/storytold)) als
Remote-MCP-Server für Claude erreichbar, auch für die Smartphone-App. Vor jeder App sitzt ein
[mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy). Er ist gegenüber Claude der
OAuth-Server (mit Dynamic Client Registration) und lässt nur Nutzer durch, die sich bei deinem
OIDC-Anbieter (z. B. Pocket ID) anmelden.

| App | Zweck | Port | Tools |
|---|---|---|---|
| VectorCraft | Vektorgrafik, Etiketten, SVG/PDF-Export | 8081 | 32 |
| PhotoCraft | Bildbearbeitung, PSD | 8082 | 25 |
| PdfCraft | PDFs bearbeiten, prüfen, zusammenführen | 8083 | 17 (kompakt) |

Hintergrund, Testergebnisse und Entscheidungen stehen in
[docs/ARTCRAFT.md](https://github.com/kleinhansda/ha-mcp-addons/blob/main/docs/ARTCRAFT.md), das gemeinsame Muster aller Add-ons in [docs/ARCHITEKTUR.md](https://github.com/kleinhansda/ha-mcp-addons/blob/main/docs/ARCHITEKTUR.md).

## Voraussetzungen

- Ein OIDC-Anbieter mit **einem** Client für alle Apps (vertraulicher Client mit Secret).
- Je App ein öffentlicher HTTPS-Hostname, z. B. über das Cloudflared-Add-on.
  Ein gemeinsamer Hostname mit Pfaden (`/vectorcraft`, `/pdfcraft`) geht nicht: Der Proxy braucht
  `/.well-known`, `/.idp` und `/.auth` an der Wurzel.

## Installation

1. Einstellungen → Apps (Add-ons) → App Store → Menü ⋮ → Repositories, eintragen:
   `https://github.com/kleinhansda/ha-mcp-addons`
2. **ArtCraft MCP** installieren. Home Assistant baut das Image dabei auf dem Gerät und lädt die
   Release-Dateien von GitHub. Das dauert einige Minuten.
3. Konfiguration ausfüllen (siehe unten), speichern, starten.
4. Im Log prüfen: Die Versionen stehen oben, je App folgt `Start auf Port …`, bei VectorCraft
   zusätzlich `files confined: read root …, write root …`.

## Konfiguration

| Option | Bedeutung |
|---|---|
| `oidc_configuration_url` | Discovery-URL, z. B. `https://id.example.com/.well-known/openid-configuration` |
| `oidc_provider_name` | Name auf der Anmeldeseite, z. B. `Pocket ID` |
| `oidc_client_id`, `oidc_client_secret` | Ein Client für alle Apps |
| `oidc_allowed_users` | Optional, kommagetrennt (Standard: E-Mail-Adresse). Zusätzlich zur Gruppenbeschränkung beim Anbieter |
| `vectorcraft_url`, `photocraft_url`, `pdfcraft_url` | Öffentliche Adresse ohne Pfad, z. B. `https://vectorcraft.example.com`. Leer = App wird nicht gestartet |
| `pdfcraft_compact` | `true`: Kern-Tools plus `tool_search` und `tool_call` statt über 160 Tools |
| `work_dir` | Gemeinsamer Arbeitsordner unter `/share`, Standard `/share/artcraft/work` |
| `legacy_auth_dir` | Nur beim Umzug von einem Docker-Stack, siehe unten |

### OIDC-Client

Ein Client, je App eine Callback-URL:

```
https://<vectorcraft-hostname>/.auth/oidc/callback
https://<photocraft-hostname>/.auth/oidc/callback
https://<pdfcraft-hostname>/.auth/oidc/callback
```

Public client aus. Den Zugriff beim Anbieter auf eine Gruppe beschränken.
Preis der Vereinfachung: Wer das Secret kennt, kann sich für alle drei Hostnamen ausgeben.

### Cloudflare-Tunnel

Je App ein öffentlicher Hostname, Pfad leer, Dienst-URL `http://<add-on-hostname>:<port>`:

| Hostname | Dienst-URL |
|---|---|
| `vectorcraft.example.com` | `http://<add-on-hostname>:8081` |
| `photocraft.example.com` | `http://<add-on-hostname>:8082` |
| `pdfcraft.example.com` | `http://<add-on-hostname>:8083` |

Den Add-on-Hostnamen zeigt Home Assistant auf der Info-Seite der App (Form `xxxxxxxx-artcraft-mcp`).
Keine Cloudflare-Access-App davor, der Login läuft über den Proxy. Falls die WAF-Regel
„Block AI bots“ aktiv ist, für diese Hostnamen eine Ausnahme anlegen, sonst kommt Claude nicht durch.

Die Ports müssen unter **Netzwerk** nicht freigegeben werden. Cloudflared erreicht die App im
internen Netz. Nur ohne Tunnel (eigener Reverse Proxy) dort Host-Ports eintragen.

## Claude verbinden

Claude → Einstellungen → Connectors → Add custom connector, je App
`https://<hostname>/mcp`, keine Client-ID. Beim Verbinden öffnet sich die Anmeldung des
OIDC-Anbieters.

Drei Connectoren statt einem: So wird pro Chat nur die App zugeschaltet, die gebraucht wird.

In den Connector-Einstellungen die UI-Tools auf **Blocked** setzen, sie funktionieren ohne
Bildschirm nicht:

- VectorCraft: `inspect_ui`, `ui_inspect`, `ui_screenshot`, `screenshot`, `type_text`, `open_panel`,
  `invoke_menu`, `press_key`, `pointer_gesture`, `select_tool`
- PhotoCraft: `ui_inspect`, `ui_menu_invoke`, `ui_pointer`, `ui_screenshot`, `ui_set`

## Arbeitsordner

Alle drei Apps lesen und schreiben nur in `work_dir` (Standard `/share/artcraft/work`). Eine in
VectorCraft exportierte PDF kann so direkt in PdfCraft weiter. Dateien kommen über die üblichen
Wege in den Ordner: Samba, WebDAV oder Syncthing.

- **Nur Arbeitskopien** in den Ordner legen, die Apps dürfen dort überschreiben.
- Anhänge aus der Claude-App erreichen die Apps nicht, sie müssen im Ordner liegen.
- **Ein Prozess je App für alle Chats:** Das geöffnete Dokument ist geteilt und bleibt zwischen
  Aufrufen offen. Ergebnisse immer mit `save_file` oder `export` sichern. Ein Neustart der App
  verwirft offene Dokumente.

## Updates

Ein GitHub-Workflow prüft täglich, ob es neue Releases der Apps oder des Proxys gibt. Er baut das
Image für aarch64 und amd64 und startet jede App mit genau den Optionen, die das Add-on nutzt
(Selbsttest). Nur wenn das klappt, erhöht er die Add-on-Version. Home Assistant zeigt dann ein
Update mit Changelog an, installiert wird erst auf Klick.

Der Selbsttest erkennt umbenannte Optionen und Apps, die nicht mehr starten. Ob jedes Tool
inhaltlich gleich arbeitet, prüft er nicht. Vor dem Update im Dialog ein Backup anlegen lassen,
damit die vorige Version wiederherstellbar ist.

Nach einem Update im Log die Versionen prüfen. Neue App-Versionen können neue Tools mitbringen,
dann die Liste der geblockten UI-Tools in Claude kurz durchsehen.

## Umzug von einem Docker-Stack

Wer die Apps bisher als eigene Container (z. B. per Portainer) betrieben hat:

1. `legacy_auth_dir` auf den Ordner mit den alten Proxy-Daten setzen, z. B. `/share/artcraft/auth`
   (mit Unterordnern `vectorcraft`, `photocraft`, `pdfcraft`). Beim ersten Start werden sie
   einmalig nach `/data` kopiert, das Original bleibt liegen. Bleiben die Hostnamen gleich, müssen
   die Connectoren in Claude nicht neu verbunden werden.
2. Gleiche URLs und denselben OIDC-Client eintragen, App starten, Log prüfen.
3. Im Tunnel die Dienst-URLs auf `http://<add-on-hostname>:8081` usw. umstellen.
4. In Claude testen, danach den alten Stack stoppen.

Alte und neue Installation stören sich nicht, solange der Tunnel nur auf eine zeigt.

## Sicherheit

- Login über OIDC, optional zusätzlich `oidc_allowed_users`.
- Die Apps sind auf `work_dir` begrenzt (Zugriffe außerhalb werden abgelehnt).
- Das Client-Secret bekommt nur der Proxy, nicht die Apps.
- Alle Downloads werden beim Bau gegen ihre Prüfsummen geprüft.
- Proxy-Daten (registrierte Clients, Schlüssel) liegen in `/data` und sind im Backup der App.

Unterschied zu einem einzeln gehärteten Docker-Stack: Ein Add-on kann pro App keine
Speichergrenze, kein schreibgeschütztes Dateisystem und keine entzogenen Capabilities setzen.
PhotoCraft braucht mit einem 24-MP-Foto rund 0,5 GB. Auf Geräten mit wenig RAM große Fotos meiden.

## Fehlerbehebung

| Symptom | Ursache | Lösung |
|---|---|---|
| App startet nicht, Log: `… ist leer` | Pflichtoption fehlt | Konfiguration ergänzen |
| Log: `Keine App aktiviert` | Keine der drei URLs eingetragen | Mindestens eine URL eintragen |
| Log: `<app>: beendet, Neustart in …` wiederholt | App oder Proxy beendet sich sofort | Zeilen davor im Log lesen, oft eine falsche URL oder ein nicht erreichbarer OIDC-Anbieter |
| Login-Seite leer, kein Redirect | Client-ID oder Secret falsch | Konfiguration prüfen |
| Anbieter meldet ungültige Redirect-URI | Callback des Hostnamens fehlt im Client | Alle Callback-URLs eintragen |
| 502 über Cloudflare | App gestoppt oder falscher Port im Tunnel | Log prüfen, Ports 8081 bis 8083 |
| `outside the write root` | Datei liegt nicht im Arbeitsordner | Pfad unter `work_dir` verwenden |
| Claude kommt nicht durch, Cloudflare blockt | WAF-Regel gegen KI-Bots | Ausnahme für die Hostnamen |
| Installation bricht beim Bauen ab | GitHub nicht erreichbar oder Release geändert | Später erneut versuchen, sonst Issue im Repo |
