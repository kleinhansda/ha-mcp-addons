# ArtCraft MCP

Macht VectorCraft, PhotoCraft und PdfCraft sowie CADCraft, WordCraft, DeckCraft, GridCraft,
FigCraft und Craft Anything ([storytold](https://github.com/storytold)) als
Remote-MCP-Server für Claude erreichbar, auch für die Smartphone-App. Vor jeder App sitzt ein
[mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy). Er ist gegenüber Claude der
OAuth-Server (mit Dynamic Client Registration) und lässt nur Nutzer durch, die sich bei deinem
OIDC-Anbieter (z. B. Pocket ID) anmelden.

Zusätzlich oder stattdessen können die Apps **intern ohne Login** laufen, z. B. für
Open WebUI auf demselben Home Assistant (siehe [Interner Zugriff](#interner-zugriff-ohne-login-z-b-open-webui)).

| App | Zweck | Port öffentlich | Port intern | `internal_apps` |
|---|---|---|---|---|
| VectorCraft | Vektorgrafik, Etiketten, SVG/PDF-Export | 8081 | 9081 | `vectorcraft` |
| PhotoCraft | Bildbearbeitung, PSD | 8082 | 9082 | `photocraft` |
| PdfCraft | PDFs bearbeiten, prüfen, zusammenführen | 8083 | 9083 | `pdfcraft` |
| CADCraft | 2D-CAD, Zeichnungen (DXF/DWG) | 8085 | 9085 | `cadcraft` |
| WordCraft | Textverarbeitung (.docx, .doc) | 8086 | 9086 | `wordcraft` |
| DeckCraft | Präsentationen (.pptx) | 8087 | 9087 | `deckcraft` |
| GridCraft | Tabellenkalkulation (.xlsx) | 8088 | 9088 | `gridcraft` |
| FigCraft | Interface-Design, Prototyping | 8089 | 9089 | `figcraft` |
| Craft Anything | Reverse Engineering, Rebuild | 8090 | 9090 | `craft-anything` |
| Dateien | Arbeitsordner: auflisten, holen, ablegen | 8084 | 9084 | `files` |

Hintergrund, Testergebnisse und Entscheidungen stehen in
[docs/ARTCRAFT.md](https://github.com/kleinhansda/ha-mcp-addons/blob/main/docs/ARTCRAFT.md).

## Voraussetzungen

Nur für den öffentlichen Zugang (z. B. Claude). Für den rein internen Zugang ist nichts davon nötig.

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
4. Im Log prüfen: Die Versionen stehen oben, je App folgt `öffentlich auf Port …` bzw.
   `intern ohne Login unter …`, bei VectorCraft zusätzlich `files confined: read root …, write root …`.

Wer ArtCraft MCP bisher aus `kleinhansda/artcraft-mcp-ha` installiert hat: siehe
[Umzug aus artcraft-mcp-ha](#umzug-aus-artcraft-mcp-ha).

## Konfiguration

| Option | Bedeutung |
|---|---|
| `oidc_configuration_url` | Discovery-URL, z. B. `https://id.example.com/.well-known/openid-configuration`. Die OIDC-Optionen sind nur nötig, wenn eine öffentliche URL eingetragen ist |
| `oidc_provider_name` | Name auf der Anmeldeseite, z. B. `Pocket ID` |
| `oidc_client_id`, `oidc_client_secret` | Ein Client für alle Apps |
| `oidc_allowed_users` | Optional, kommagetrennt (Standard: E-Mail-Adresse). Zusätzlich zur Gruppenbeschränkung beim Anbieter |
| `vectorcraft_url`, `photocraft_url`, `pdfcraft_url`, `cadcraft_url`, `wordcraft_url`, `deckcraft_url`, `gridcraft_url`, `figcraft_url`, `craft_anything_url`, `files_url` | Öffentliche Adresse ohne Pfad, z. B. `https://vectorcraft.example.com`. Leer = App wird nicht gestartet |
| `internal_apps` | Apps, die zusätzlich intern ohne Login erreichbar sind, siehe unten. Leer = kein interner Zugriff |
| `pdfcraft_compact` | `true`: Kern-Tools plus `tool_search` und `tool_call` statt über 160 Tools |
| `work_dir` | Gemeinsamer Arbeitsordner unter `/share`, Standard `/share/artcraft/work` |
| `fonts_to_work` | Mitgelieferte Schriften nach `<work_dir>/fonts/standard` kopieren (Standard an), siehe [Schriften](#schriften) |
| `legacy_auth_dir` | Nur beim Umzug von einem Docker-Stack, siehe unten |

### OIDC-Client

Ein Client, je App eine Callback-URL:

```
https://<vectorcraft-hostname>/.auth/oidc/callback
https://<photocraft-hostname>/.auth/oidc/callback
https://<pdfcraft-hostname>/.auth/oidc/callback
https://<cadcraft-hostname>/.auth/oidc/callback
https://<wordcraft-hostname>/.auth/oidc/callback
https://<deckcraft-hostname>/.auth/oidc/callback
https://<gridcraft-hostname>/.auth/oidc/callback
https://<figcraft-hostname>/.auth/oidc/callback
https://<craft-anything-hostname>/.auth/oidc/callback
https://<files-hostname>/.auth/oidc/callback
```

Public client aus. Den Zugriff beim Anbieter auf eine Gruppe beschränken.
Preis der Vereinfachung: Wer das Secret kennt, kann sich für alle Hostnamen ausgeben.

### Cloudflare-Tunnel

Je App ein öffentlicher Hostname, Pfad leer, Dienst-URL `http://<add-on-hostname>:<port>`:

| Hostname | Dienst-URL |
|---|---|
| `vectorcraft.example.com` | `http://<add-on-hostname>:8081` |
| `photocraft.example.com` | `http://<add-on-hostname>:8082` |
| `pdfcraft.example.com` | `http://<add-on-hostname>:8083` |
| `cadcraft.example.com` | `http://<add-on-hostname>:8085` |
| `wordcraft.example.com` | `http://<add-on-hostname>:8086` |
| `deckcraft.example.com` | `http://<add-on-hostname>:8087` |
| `gridcraft.example.com` | `http://<add-on-hostname>:8088` |
| `figcraft.example.com` | `http://<add-on-hostname>:8089` |
| `craft-anything.example.com` | `http://<add-on-hostname>:8090` |
| `files.example.com` | `http://<add-on-hostname>:8084` |

Den Add-on-Hostnamen zeigt Home Assistant auf der Info-Seite der App (Form `xxxxxxxx-artcraft-mcp`).
Keine Cloudflare-Access-App davor, der Login läuft über den Proxy. Falls die WAF-Regel
"Block AI bots" aktiv ist, für diese Hostnamen eine Ausnahme anlegen, sonst kommt Claude nicht durch.

Die Ports (8081 bis 8090) müssen unter **Netzwerk** nicht freigegeben werden. Cloudflared erreicht die App im
internen Netz. Nur ohne Tunnel (eigener Reverse Proxy) dort Host-Ports eintragen.

## Claude verbinden

Claude → Einstellungen → Connectors → Add custom connector, je App
`https://<hostname>/mcp`, keine Client-ID. Beim Verbinden öffnet sich die Anmeldung des
OIDC-Anbieters.

Ein Connector je App (bis zu elf) statt einem: So wird pro Chat nur die App zugeschaltet, die gebraucht wird.

In den Connector-Einstellungen die UI-Tools auf **Blocked** setzen, sie funktionieren ohne
Bildschirm nicht:

- VectorCraft: `inspect_ui`, `ui_inspect`, `ui_screenshot`, `screenshot`, `type_text`, `open_panel`,
  `invoke_menu`, `press_key`, `pointer_gesture`, `select_tool`
- PhotoCraft: `ui_inspect`, `ui_menu_invoke`, `ui_pointer`, `ui_screenshot`, `ui_set`

## Interner Zugriff ohne Login (z. B. Open WebUI)

Für Clients, die auf demselben Home Assistant laufen (z. B. Open WebUI als App), kann jede App
zusätzlich **ohne Anmeldung** im internen Docker-Netz bereitstehen. Dafür die App unter
`internal_apps` auswählen. Öffentliche URL und interner Zugriff schließen sich nicht aus.

- Adresse: `http://<add-on-hostname>:<port intern>/mcp`, z. B. `http://xxxxxxxx-artcraft-mcp:9081/mcp`.
  Das Log zeigt beim Start für jede App die fertige Adresse (`… intern ohne Login unter …`).
- Ports 9081 bis 9090 (öffentlicher Port + 1000). Sie stehen nicht unter **Netzwerk** und werden
  nie auf den Host gelegt, sind also aus dem Heimnetz nicht erreichbar.
- Kein OIDC nötig, wenn nur interne Apps gewählt sind.
- Die App startet erst beim ersten Zugriff, ungenutzte Apps belegen keinen Speicher.
- Läuft eine App öffentlich **und** intern, sind das zwei getrennte Prozesse mit getrennten offenen Dokumenten.

### Open WebUI einrichten

Admin-Bereich → Einstellungen → Externe Werkzeuge (bzw. Verbindungen) → **+**:

| Feld | Wert |
|---|---|
| Typ | MCP (Streamable HTTP) |
| URL | `http://<add-on-hostname>:9081/mcp` (je App eine Verbindung) |
| Authentifizierung | Keine |

Danach die Werkzeuge im Modell oder im Chat zuschalten. Die UI-Tools (siehe oben) dort deaktivieren
bzw. im System-Prompt ausschließen, sie funktionieren ohne Bildschirm nicht.

**Sicherheit:** Jeder Container im internen Netz von Home Assistant (alle Apps, Home Assistant
selbst) und Apps mit Host-Netzwerk können die internen Ports ohne Login nutzen. Das schließt den
Lese- und Schreibzugriff auf den Arbeitsordner ein (insbesondere `files`). Nur Apps freigeben, die
intern gebraucht werden. Anfragen aus dem Browser (mit `Origin`-Header) werden abgelehnt.

## Arbeitsordner

Alle Apps lesen und schreiben nur in `work_dir` (Standard `/share/artcraft/work`). Eine in
VectorCraft exportierte PDF kann so direkt in PdfCraft weiter. Dateien kommen über die üblichen
Wege in den Ordner: Samba, WebDAV oder Syncthing.

- **Nur Arbeitskopien** in den Ordner legen, die Apps dürfen dort überschreiben.
- Anhänge aus der Claude-App erreichen die Apps nicht, sie müssen im Ordner liegen.
- **Ein Prozess je App für alle Chats:** Das geöffnete Dokument ist geteilt und bleibt zwischen
  Aufrufen offen. Ergebnisse immer mit `save_file` oder `export` sichern. Ein Neustart der App
  verwirft offene Dokumente.

### Schriften

Das Image bringt offene Schriften mit (DejaVu, Liberation, Open Sans, Lato, Inter, je Familie
Regular, Italic, Bold, BoldItalic; SIL OFL, Apache, Bitstream Vera).

- VectorCraft, PhotoCraft und die übrigen Apps finden sie unter `/usr/share/fonts`.
- PdfCraft sucht nur im Arbeitsordner und folgt keinen Symlinks. Mit `fonts_to_work` (Standard an)
  kopiert das Add-on die Schriften deshalb beim Start nach `<work_dir>/fonts/standard` (ca. 12 MB,
  nur neuere Dateien).
- **Eigene Schriften** nach `<work_dir>/fonts` legen (`.ttf`, `.otf`, nicht `.ttc`). Eine
  fontconfig-Datei macht den Ordner auch den anderen Apps bekannt, PdfCraft findet sie ohnehin.
  Nach dem Ablegen die App neu starten.
- Das Log zeigt beim Start `Schriften: <Anzahl> Dateien in …`. Der Selbsttest prüft, dass PdfCraft
  die Schriften findet und eine davon mit Umlauten und `€` einbetten kann.

### Dateien-Connector (`files_url`)

Ein kleiner eigener MCP-Server für den Arbeitsordner. Damit kommt Claude an Ergebnisse der Apps
heran (z. B. ein exportiertes WebP aus PhotoCraft) und kann Dateien dort ablegen, ohne Umweg über
Syncthing und einen Rechner.

| Tool | Wirkung |
|---|---|
| `files_list` | Listet Dateien und Ordner (optional rekursiv, höchstens 500 Einträge) |
| `file_get` | Liefert eine Datei als Binärinhalt (Resource mit Blob), höchstens 10 MB |
| `file_put` | Legt eine Datei ab (base64), **überschreibt nur mit `overwrite=true`**, höchstens 10 MB |

- Pfade sind relativ zu `work_dir`. `..` und Symlinks nach draußen werden abgelehnt.
- Die Grenze lässt sich über die Umgebungsvariable `FILES_MAX_BYTES` im Image ändern, nicht in der Oberfläche.
- Der Server ist wie die Apps hinter dem Login-Proxy. Wer Zugriff auf den Connector hat, kann den
  **gesamten** Arbeitsordner lesen und schreiben. Deshalb nur Arbeitskopien dort ablegen.
- Der Connector braucht eigene Hostnamen, Callback-URL und Tunnel-Eintrag wie die anderen Apps.

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

## Umzug aus artcraft-mcp-ha

ArtCraft MCP lag zwischenzeitlich in einem eigenen Repository (`kleinhansda/artcraft-mcp-ha`).
Die App aus diesem Repository ist dieselbe, hat aber einen anderen Hostnamen
(`be60cb4b-artcraft-mcp` statt `d292e89e-artcraft-mcp`). Beide können kurz parallel laufen.

1. **ArtCraft MCP** aus diesem Repository installieren, Optionen von der alten App übernehmen
   (gleiche URLs, gleicher OIDC-Client, gleicher `work_dir`). Noch nicht starten.
2. Alte App **stoppen**, neue starten. Der Arbeitsordner unter `/share` bleibt, wie er ist.
3. Im Cloudflare-Tunnel die Dienst-URLs auf `http://be60cb4b-artcraft-mcp:<port>` umstellen,
   in Open WebUI die internen URLs (`…:9081/mcp` usw.) ebenso.
4. Die Connectoren in Claude einmal neu verbinden: Die registrierten Clients liegen in `/data`
   der alten App und werden nicht übernommen.
5. Läuft alles, die alte App deinstallieren und das Repository `artcraft-mcp-ha` in Home
   Assistant entfernen.

## Umzug von einem Docker-Stack

Wer die Apps bisher als eigene Container (z. B. per Portainer) betrieben hat:

1. `legacy_auth_dir` auf den Ordner mit den alten Proxy-Daten setzen, z. B. `/share/artcraft/auth`
   (mit Unterordnern `vectorcraft`, `photocraft`, `pdfcraft`, `cadcraft`, `wordcraft`, `deckcraft`, `gridcraft`, `figcraft`, `craft-anything`). Beim ersten Start werden sie
   einmalig nach `/data` kopiert, das Original bleibt liegen. Bleiben die Hostnamen gleich, müssen
   die Connectoren in Claude nicht neu verbunden werden.
2. Gleiche URLs und denselben OIDC-Client eintragen, App starten, Log prüfen.
3. Im Tunnel die Dienst-URLs auf `http://<add-on-hostname>:8081` usw. umstellen.
4. In Claude testen, danach den alten Stack stoppen.

Alte und neue Installation stören sich nicht, solange der Tunnel nur auf eine zeigt.

## Sicherheit

- Login über OIDC, optional zusätzlich `oidc_allowed_users`.
- Interner Zugriff (`internal_apps`) ohne Login, nur im internen Docker-Netz, Ports nie auf dem Host.
- Die Apps WordCraft, DeckCraft und FigCraft sind auf `work_dir` begrenzt (Zugriffe außerhalb
  werden abgelehnt). CADCraft, GridCraft und Craft Anything bieten diese Begrenzung nicht, ihre
  Tools können außerhalb des Arbeitsordners lesen.
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
| Log: `Keine App aktiviert` | Weder URL noch `internal_apps` eingetragen | URL eintragen oder Apps unter `internal_apps` wählen |
| Log: `oidc_… ist leer (nötig für öffentliche URLs)` | Öffentliche URL ohne OIDC-Daten | OIDC ergänzen oder URL leeren und `internal_apps` nutzen |
| Open WebUI: Verbindung schlägt fehl | Falscher Hostname oder Port, App nicht in `internal_apps` | Adresse aus dem Log übernehmen, Pfad `/mcp` nicht vergessen |
| Interner Zugriff: `Origin nicht erlaubt` (403) | Aufruf aus dem Browser | Nur serverseitige Clients wie Open WebUI nutzen |
| Log: `<app>: beendet, Neustart in …` wiederholt | App oder Proxy beendet sich sofort | Zeilen davor im Log lesen, oft eine falsche URL oder ein nicht erreichbarer OIDC-Anbieter |
| Login-Seite leer, kein Redirect | Client-ID oder Secret falsch | Konfiguration prüfen |
| Anbieter meldet ungültige Redirect-URI | Callback des Hostnamens fehlt im Client | Alle Callback-URLs eintragen |
| 502 über Cloudflare | App gestoppt oder falscher Port im Tunnel | Log prüfen, Ports 8081 bis 8090 |
| `Pfad liegt außerhalb des Arbeitsordners` | Pfad zeigt aus `work_dir` heraus (Dateien-Connector) | Relativen Pfad unter `work_dir` verwenden |
| `outside the write root` | Datei liegt nicht im Arbeitsordner | Pfad unter `work_dir` verwenden |
| PdfCraft findet eine Schrift nicht | `fonts_to_work` aus, Schrift außerhalb von `<work_dir>/fonts` oder `.ttc` | `fonts_to_work` an, Schrift als `.ttf`/`.otf` nach `<work_dir>/fonts`, App neu starten |
| Claude kommt nicht durch, Cloudflare blockt | WAF-Regel gegen KI-Bots | Ausnahme für die Hostnamen |
| Installation bricht beim Bauen ab | GitHub nicht erreichbar oder Release geändert | Später erneut versuchen, sonst Issue im Repo |
