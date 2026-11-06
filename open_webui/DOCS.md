# Open WebUI

[Open WebUI](https://github.com/open-webui/open-webui) als App auf dem Home-Assistant-Gerät:
das offizielle Image (amd64 und arm64), ergänzt um ein Startskript für die Optionen, den Login
über einen OIDC-Anbieter wie Pocket ID und die einmalige Übernahme einer bestehenden
Installation.

Warum auf dem Home-Assistant-Gerät: Es läuft ohnehin rund um die Uhr, die MCP-Apps dieses
Repositorys laufen daneben, und die Daten landen in den normalen Backups.

## Voraussetzungen

- **Speicher:** Das Image ist mehrere GB groß (es enthält PyTorch für lokale Modelle). Rechne mit
  rund 6 GB freiem Platz für Image und Update.
- **Arbeitsspeicher:** Mit externen Modellen (z. B. Scaleway, OpenAI-kompatibel) braucht Open WebUI
  etwa 1 GB. Lokale Embeddings oder lokale Spracherkennung (Whisper) sind auf einem Raspberry Pi
  langsam und speicherhungrig. Stell beides auf externe Dienste um, siehe unten.
- Ein OIDC-Client beim Anbieter mit Callback `https://<webui_url>/oauth/oidc/callback`. Beim Umzug
  bleibt der bisherige Client gültig, solange die URL gleich bleibt.

## Installation

1. Einstellungen → Apps → App Store → ⋮ → Repositories:
   `https://github.com/kleinhansda/ha-addons`
2. **Open WebUI** installieren. Home Assistant lädt dabei das offizielle Image, das dauert auf
   einem Raspberry Pi eine Weile.
3. Optionen setzen (unten), noch **nicht** starten, wenn Daten übernommen werden sollen.
4. Erreichbarkeit: im Cloudflared-Add-on bzw. im Cloudflare-Dashboard den Hostnamen auf
   `http://<repo-hash>-open-webui:8080` zeigen lassen. `<repo-hash>` ist das Präfix vor
   `_open_webui` in der Adresszeile der App-Seite, z. B. `be60cb4b`.

## Optionen

| Option | Bedeutung |
|---|---|
| `webui_url` | Öffentliche Adresse ohne Pfad, z. B. `https://ai.example.com` |
| `webui_secret_key` | Nur beim Umzug, wenn der alte Schlüssel als Umgebungsvariable gesetzt war. Leer = Datei `/data/.webui_secret_key` |
| `oidc_configuration_url` | Discovery-URL, z. B. `https://id.example.com/.well-known/openid-configuration` |
| `oidc_provider_name` | Beschriftung des Login-Knopfs |
| `oidc_client_id` / `oidc_client_secret` | OIDC-Client. Leer = nur Login mit E-Mail und Passwort |
| `oidc_signup` | Neue Konten beim ersten OIDC-Login anlegen (Standard aus) |
| `oidc_merge_by_email` | OIDC-Login mit bestehendem Konto gleicher E-Mail verknüpfen (Standard aus) |
| `login_form` | Login mit E-Mail und Passwort anbieten. Aus = nur OIDC (bleibt an, solange kein OIDC eingerichtet ist) |
| `searxng` | Private SearXNG-Instanz als Web-Suche (Standard an), siehe unten |
| `open_terminal_api_key` | Schlüssel der App Open Terminal. Gesetzt = Open Terminal wird automatisch eingetragen |
| `open_terminal_url` | Nur für ein Open Terminal außerhalb dieses Repositorys. Leer = `http://<repo-hash>-open-terminal:8000` |
| `extra_env` | Weitere Variablen von Open WebUI, je Eintrag `NAME=Wert` |

Die meisten Einstellungen speichert Open WebUI in seiner Datenbank und pflegt sie im
Admin-Bereich. Eine Variable in `extra_env` wirkt dort nur, solange der Wert nicht im
Admin-Bereich geändert wurde. Die OIDC-Optionen oben gelten dagegen bei jedem Start.

## Web-Suche mit SearXNG

Mit `searxng` an (Standard) startet die App eine eigene SearXNG-Instanz, erreichbar nur
innerhalb der App unter `127.0.0.1:8888`. Open WebUI wird bei jedem Start darauf eingestellt
(Admin-Bereich → Web-Suche: Engine `searxng`). Nichts weiter einzurichten; im Chat schaltest
du die Web-Suche beim Eingabefeld zu.

Die Einstellung wird bei jedem Start erneut gesetzt. Wer eine andere Suchmaschine nutzen
will, schaltet `searxng` aus und richtet sie im Admin-Bereich ein.

## Open Terminal

Open Terminal (Shell, Dateien und Werkzeuge für das Modell) läuft als eigene App, damit
Befehle des Modells nicht an Datenbank und Schlüssel von Open WebUI kommen:

1. App **Open Terminal** aus diesem Repository installieren und starten.
2. Den Schlüssel aus ihrem Protokoll hier bei `open_terminal_api_key` eintragen, Open WebUI
   neu starten.

Open WebUI trägt die Verbindung selbst ein (Admin-Bereich → Integrationen → Open Terminal),
zunächst nur für Admins. Freigaben für weitere Nutzer dort bleiben bei Neustarts erhalten.
Leerer Schlüssel = der Eintrag wird beim nächsten Start entfernt.

## Umzug einer bestehenden Installation

Das Startskript übernimmt einmalig den Inhalt von
`/addon_configs/<repo-hash>_open_webui/import/`, solange die App noch keine eigene Datenbank hat.
Danach prüft es die Datenbank und benennt den Ordner in `import.erledigt-<Datum>` um.

> **Wichtig:** Alte und neue Installation dürfen nicht gleichzeitig laufen. Sonst entstehen zwei
> Datenbanken, die auseinanderlaufen, und Chats aus der einen fehlen in der anderen.
> Den alten Container erst stoppen, dann kopieren. Eine laufende SQLite-Datenbank zu kopieren kann
> eine beschädigte Kopie ergeben; das Startskript erkennt das und bricht ab.

1. **Schlüssel sichern.** Ohne den alten Schlüssel ist nach dem Umzug jeder abgemeldet, und
   per OAuth verbundene Tool-Server müssen neu verbunden werden. Auf dem alten Host (Name des
   Containers ggf. anpassen):
   ```sh
   docker exec open-webui sh -c 'echo "ENV: $WEBUI_SECRET_KEY"; cat /app/backend/.webui_secret_key'
   ```
   Steht ein Wert hinter `ENV:`, kommt er in die Option `webui_secret_key`. Sonst den Inhalt der
   Datei als `import/.webui_secret_key` ablegen (Schritt 3).
2. **Alten Container stoppen** (`docker stop open-webui` bzw. Stack stoppen). Nicht löschen, er ist
   der Weg zurück.
3. **Daten kopieren.** Den Inhalt des Datenordners (im Container `/app/backend/data`, auf dem Host
   z. B. `/mnt/user/appdata/open-webui`) nach `/addon_configs/<repo-hash>_open_webui/import/`,
   also `webui.db`, `uploads/`, `vector_db/` und was sonst darin liegt. Heruntergeladene Modelle
   (`cache/embedding`, `cache/whisper`) lässt das Startskript aus; die kannst du auch gleich
   weglassen. Der Rest von `cache/` enthält u. a. erzeugte Bilder und gehört dazu.
   Wege dorthin: Samba-Freigabe `addon_configs`, Studio Code Server oder `scp` über das
   SSH-Add-on.
4. **App starten** und im Protokoll auf `Übernahme fertig, Datenbank geprüft` achten. Der erste
   Start nach einem Versionssprung führt Datenbank-Migrationen aus und kann auf einem Pi mehrere
   Minuten dauern. Die App gilt erst danach als gestartet.
5. **Hostnamen umstellen** (Cloudflare) auf `http://<repo-hash>-open-webui:8080` und mit dem
   OIDC-Login testen.

**Zurück:** Hostnamen wieder auf den alten Host zeigen lassen und den alten Container starten.
Chats, die inzwischen in der App entstanden sind, fehlen dort. Den alten Container erst löschen,
wenn alles läuft.

## Empfohlene Einstellungen auf einem Raspberry Pi

Im Admin-Bereich von Open WebUI:

- **Dokumente → Embedding:** Engine „OpenAI“ mit einem externen Anbieter, z. B. Scaleway
  (`https://api.scaleway.ai/v1`, Modell `bge-multilingual-gemma2` oder ein Qwen-Embedding-Modell).
  Nach einem Wechsel des Embedding-Modells passen die alten Vektoren nicht mehr: unten auf der
  Seite **Neu indizieren** ausführen.
- **Web-Suche:** erledigt die App (SearXNG), siehe oben.
- **Dokumente → Inhaltsextraktion:** Tika, falls das Tika-Gotenberg-Add-on läuft:
  `http://ca5234a0-tika-gotenberg:9998`.
- **Audio → Spracherkennung:** OpenAI-kompatibel, z. B. Scaleway mit `whisper-large-v3`, statt
  des lokalen Whisper.

## Tool-Server (MCP)

Die MCP-Apps auf demselben Gerät sind intern über ihren Hostnamen erreichbar
(`http://<repo-hash>-<slug>:<port>`, Bindestriche statt Unterstriche). Zwei Fälle:

- **Mit internem Zugang ohne Login** (empfohlen auf demselben Gerät): Admin-Bereich →
  Einstellungen → Integrationen → **+**, Typ *MCP Streamable HTTP*, Authentifizierung *Keine*,
  URL je App:

  | App | Option | URL |
  |---|---|---|
  | Foto MCP, GitHub MCP, Netlify MCP (ab 1.1.0) | `internal_access` | `http://<repo-hash>-foto-mcp:9080/mcp` bzw. `-github-mcp`, `-netlify-mcp` |
  | ArtCraft MCP (ab 1.4.0) | `internal_apps` | `http://<repo-hash>-artcraft-mcp:9081/mcp` usw., je App ein Port |
  | mailbox.org MCP (ab 0.5.0) | `internal_access` | `http://<repo-hash>-mailbox-org-mcp:9081/mcp` (Mail), `:9082` SMTP, `:9083` Kalender, `:9084` Adressbuch, `:9085` Drive |
  | Files MCP | `internal_access` | `http://<repo-hash>-files-mcp:9080/mcp` |

  `<repo-hash>` ist für dieses Repository `be60cb4b`. Die genaue Adresse
  steht beim Start im Protokoll der MCP-App.
- **Nur mit OAuth-Login** (mcp-auth-proxy): die öffentliche URL eintragen. Der Login-Ablauf
  prüft, dass Aussteller und Adresse zusammenpassen, die interne Adresse geht dort nicht.

## Updates und Backup

- Die Version von Open WebUI ist fest (`OPEN_WEBUI_VERSION` im Dockerfile). Ein täglicher
  Workflow prüft neue Releases, baut die App zusammen mit Open Terminal für amd64 und arm64 und
  testet den echten Start (Healthcheck, SearXNG, Terminal, Datenübernahme). Erst dann wird die
  Version eingetragen und Home Assistant zeigt das Update an. Die Add-on-Version folgt der
  Version von Open WebUI, eigene Änderungen hängen `-1`, `-2` … an.
- **Vor dem Update im Dialog ein Backup anlegen lassen:** Datenbank-Migrationen lassen sich
  nicht rückgängig machen. Der erste Start nach dem Update kann auf einem Pi mehrere Minuten
  dauern.
- Open Terminal am besten zusammen aktualisieren, neue Funktionen setzen oft beide Versionen voraus.
- Das Backup der App enthält `/data` (Datenbank, Uploads, Vektoren, Schlüssel), ohne
  heruntergeladene Modelle (`cache/embedding`, `cache/whisper`).
