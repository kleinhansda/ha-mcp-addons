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
   `https://github.com/kleinhansda/ha-mcp-addons`
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
| `extra_env` | Weitere Variablen von Open WebUI, je Eintrag `NAME=Wert` |

Die meisten Einstellungen speichert Open WebUI in seiner Datenbank und pflegt sie im
Admin-Bereich. Eine Variable in `extra_env` wirkt dort nur, solange der Wert nicht im
Admin-Bereich geändert wurde. Die OIDC-Optionen oben gelten dagegen bei jedem Start.

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
- **Dokumente → Inhaltsextraktion:** Tika, falls das Tika-Gotenberg-Add-on läuft:
  `http://ca5234a0-tika-gotenberg:9998`.
- **Audio → Spracherkennung:** OpenAI-kompatibel, z. B. Scaleway mit `whisper-large-v3`, statt
  des lokalen Whisper.

## Tool-Server (MCP)

Die MCP-Apps auf demselben Gerät sind intern über ihren Hostnamen erreichbar. Für Server mit
OAuth-Login (z. B. mcp-auth-proxy, mcp-hub) bleibt trotzdem die öffentliche URL eingetragen:
Der Login-Ablauf prüft, dass Aussteller und Adresse zusammenpassen.

## Updates und Backup

- Die Version von Open WebUI ist fest (`OPEN_WEBUI_VERSION` im Dockerfile) und wird von Hand
  erhöht, zusammen mit `version` in `config.yaml`. Vor einem Update ein Backup der App anlegen:
  Migrationen lassen sich nicht rückgängig machen.
- Das Backup der App enthält `/data` (Datenbank, Uploads, Vektoren, Schlüssel), ohne
  heruntergeladene Modelle (`cache/embedding`, `cache/whisper`).
