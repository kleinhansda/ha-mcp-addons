# mailbox.org MCP

## Voraussetzungen

- **Passwörter** bei mailbox.org anlegen (Einstellungen → Sicherheit), niemals
  das Hauptpasswort verwenden. Pro Anwendungstyp ein eigenes: ein
  **E-Mail-App-Passwort** für Mail (`app_password`) und ein
  **Anwendungspasswort „Kalender- und Adressbuch-Client (CalDAV/CardDAV)“** für
  Kalender und Adressbuch (`dav_password`). Für Drive zusätzlich ein
  **Anwendungspasswort „WebDAV-Client“** (`webdav_password`).
- Eine **öffentliche HTTPS-Adresse** mit Reverse-Proxy (z. B. Nginx Proxy
  Manager oder Cloudflare Tunnel) auf Port `8099` des Add-ons. Ohne TLS
  funktioniert der OAuth-Login nicht. Läuft der Proxy/Tunnel selbst als App in
  Home Assistant, zeigt er auf den internen Hostnamen, z. B.
  `http://<repo-hash>-mailbox-org-mcp:8099`. Ein Host-Port ist dann nicht nötig
  (Standard seit 0.2.0: nicht veröffentlicht).

## Optionen

| Option                     | Bedeutung                                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------------ |
| `email`                    | Deine mailbox.org-Adresse                                                                  |
| `app_password`             | E-Mail-App-Passwort (IMAP, SMTP). Für Kalender/Adressbuch nur als Fallback, wenn `dav_password` leer ist |
| `dav_password`             | Anwendungspasswort vom Typ „Kalender- und Adressbuch-Client (CalDAV/CardDAV)“. mailbox.org vergibt Passwörter je Anwendungstyp, ein E-Mail-App-Passwort gilt nicht für Kalender/Adressbuch (HTTP 401). Leer = `app_password` |
| `webdav_password`          | Anwendungspasswort vom Typ „WebDAV-Client“, nur für Drive nötig                            |
| `hub_password`             | Passwort für den Login, den Claude beim Verbinden anzeigt                                  |
| `external_url`             | Öffentliche Basis-URL ohne Pfad, z. B. `https://mcp.example.net`                           |
| `timezone`                 | IANA-Zeitzone für Kalendertermine                                                          |
| `essential_tools`          | Nur die kuratierte Werkzeugauswahl je Dienst laden (empfohlen)                             |
| `mail_enabled`             | Mail lesen (IMAP)                                                                           |
| `mail_write`               | Verschieben, Flags, Entwürfe, Löschen erlauben (Löschen/Verschieben fragen trotzdem nach) |
| `smtp_enabled`             | SMTP-Server laden (ohne `smtp_allow_send` nur Vorschau)                                     |
| `smtp_allow_send`          | Senden erlauben – **erst nach Test aktivieren**                                            |
| `smtp_allowed_recipients`  | Pflicht bei Senden: `a@x.de,@firma.de`; `*` = alle                                         |
| `smtp_from_name`           | Anzeigename des Absenders                                                                  |
| `calendar_enabled` / `calendar_write` | Kalender lesen / schreiben                                                      |
| `contacts_enabled` / `contacts_write` | Adressbuch lesen / schreiben                                                    |
| `drive_enabled` / `drive_write` | Drive lesen / Textdateien und Ordner anlegen (kein Löschen, kein Verschieben)         |
| `drive_root`               | Drive-Zugriff auf einen Ordner beschränken, z. B. `/Userstore/Name/MCP`; leer = ganzes Drive |
| `work_dir`                 | Arbeitsordner unter `/share` (Standard `/share/artcraft/work`), siehe unten; leer = aus     |
| `imap_trusted_authserv_id` | authserv-id aus dem `Authentication-Results`-Header von mailbox.org; macht SPF/DKIM-Urteile vertrauenswürdig |
| `trusted_proxies`          | IP/CIDR deines Reverse-Proxys, damit das Login-Rate-Limit pro Client greift (z. B. `172.30.32.0/23` für einen Tunnel als HA-App) |
| `passkey_enabled`          | Passkey-Gate vor den Hub schalten (siehe unten)                                            |
| `oidc_issuer`              | Basis-URL des OIDC-Anbieters, z. B. `https://id.example.net`                              |
| `oidc_client_id` / `oidc_client_secret` | OIDC-Client, den du beim Anbieter für dieses Add-on anlegst                  |
| `passkey_allowed_users`    | Wer freigeben darf: E-Mail-Adressen, Benutzernamen oder `sub`, kommagetrennt               |
| `internal_access`          | Jeden aktiven Dienst zusätzlich ohne Login im internen Netz anbieten (siehe unten), Standard aus |

Standard ist überall **nur lesen**. Schreib- und Sendewerkzeuge werden nicht
abgelehnt, sondern gar nicht erst registriert.

## Drive (optional)

mailbox.org Drive läuft über WebDAV (`https://dav.mailbox.org/servlet/webdav.infostore`).
Dafür bringt das Add-on einen eigenen kleinen Server mit (`webdav/webdav-mcp.mjs`):

| Werkzeug               | Wirkung                                                              |
| ---------------------- | -------------------------------------------------------------------- |
| `drive_list`           | Ordnerinhalt auflisten                                               |
| `drive_search`         | Dateien/Ordner nach Namensteil suchen (rekursiv, begrenzt)           |
| `drive_info`           | Größe, Typ, Änderungsdatum                                           |
| `drive_read`           | Textdatei lesen (UTF-8, bis 1 MiB); PDFs, Bilder, Office nicht       |
| `drive_write_file`     | nur mit `drive_write`: Textdatei anlegen, Ersetzen nur mit `overwrite` |
| `drive_create_folder`  | nur mit `drive_write`: Ordner anlegen                                 |
| `work_list`, `drive_to_work` | mit `work_dir`: Arbeitsordner auflisten, Dateien aus dem Drive dorthin kopieren |
| `work_to_drive`        | mit `work_dir` und `drive_write`: Datei aus dem Arbeitsordner ins Drive |

Löschen, Verschieben, Kopieren innerhalb des Drives und Freigaben gibt es bewusst nicht. Pfade
können `drive_root` nicht verlassen (`..` und kodierte Varianten werden
abgewiesen).

Einrichtung: mailbox.org → Einstellungen → Sicherheit → Anwendungspasswörter →
„WebDAV-Client“, in `webdav_password` eintragen, `drive_enabled` an. Lass
`drive_root` zuerst leer und frag nach dem Inhalt von `/`, um die Ordnerstruktur
zu sehen; danach auf den gewünschten Ordner beschränken.

## Arbeitsordner

Mit `work_dir` (Standard `/share/artcraft/work`) teilt das Add-on einen Ordner mit
ArtCraft, Foto MCP und Open Terminal. Das Add-on legt `inbox/` und `out/` an und gibt
den Servern (uid 1000) dort Schreibrechte.

| Dienst | Was                                                                                      |
| ------ | ---------------------------------------------------------------------------------------- |
| Mail   | `get_attachments` speichert Anhänge nach `inbox/` (bei `essential_tools` zusätzlich freigeschaltet) |
| Senden | Anhänge nur aus `out/`, nur Dateiname ohne Ordner, mit Typprüfung von smtp-mcp           |
| Drive  | `work_list` listet den Arbeitsordner, `drive_to_work` kopiert Dateien beliebigen Typs (bis 100 MiB, Ordner nicht rekursiv, höchstens 50) nach `inbox/`. Mit `drive_write` zusätzlich `work_to_drive` (z. B. Ergebnisse aus `out/` ins Drive) |

Im Arbeitsordner wird nie überschrieben: bei gleichem Namen heißt die Kopie
`name-1.jpg`. Pfade können den Arbeitsordner nicht verlassen, auch nicht über Links.
`drive_to_work` schreibt lokal und ist deshalb auch ohne `drive_write` da.

`map: share` gibt dem Add-on Zugriff auf ganz `/share`. Die Server nutzen nur
`work_dir`, die Grenze ziehen ihre Pfadprüfungen, nicht Home Assistant.

## Passkey-Login (optional)

`mcp-hub` kennt als Login nur das `hub_password`. Mit `passkey_enabled` lauscht
auf Port 8099 ein Gate, der Hub läuft intern auf 8100:

- Login- und Freigabeseiten (`/interaction/…`) verlangen zuerst eine Anmeldung
  beim OIDC-Anbieter (z. B. Pocket ID → Passkey).
- Danach zeigt das Gate die Freigabeseite des Hubs mit Client-Name und
  Rückleitungsziel, aber ohne Passwortfeld. Ein Klick auf **Freigeben** schickt
  das Formular ab, das Gate setzt das `hub_password` serverseitig ein.
- Ein Login-Versuch ohne Passkey-Sitzung wird abgewiesen – das Hub-Passwort ist
  von außen nicht mehr verwendbar. `hub_password` bleibt trotzdem Pflicht;
  nimm einen langen Zufallswert, du tippst ihn nie ein.
- Alles andere (`/hub`, `/<name>/mcp`, `/token`, `/register`, `/.well-known/…`)
  reicht das Gate unverändert durch. Das sind Aufrufe der MCP-Clients von ihrem
  Server aus, geschützt durch die Tokens des Hubs.

Einrichtung bei **Pocket ID**:

1. Administration → OIDC-Clients → Hinzufügen.
2. Name z. B. `mailbox.org MCP`, Callback-URL:
   `https://<external_url>/passkey/callback` (exakt so, ohne Platzhalter).
3. Kein öffentlicher Client, PKCE darf an sein. Client-ID und Client-Secret
   kopieren.
4. Optional: Zugriff auf eine Benutzergruppe beschränken.
5. Im Add-on setzen: `passkey_enabled: true`, `oidc_issuer` (z. B.
   `https://id.example.net`), `oidc_client_id`, `oidc_client_secret`,
   `passkey_allowed_users` (deine E-Mail-Adresse bei Pocket ID). App neu
   starten.

Im Log erscheint dann `[passkey-gate] lauscht auf :8099 …`. Jede Anmeldung und
jede abgewiesene Anfrage wird dort protokolliert.

Die Passkey-Sitzung gilt 10 Minuten und nur für den Freigabe-Moment. Danach
verbinden sich bereits freigegebene Clients über ihre Tokens, ohne Login.

## Verbinden

- **Claude (Web/Desktop/Mobile):** Einstellungen → Connectors → Custom
  Connector → `https://<external_url>/hub` → mit `hub_password` anmelden
  (bzw. mit Passkey, wenn `passkey_enabled` an ist).
- **Einzelner Dienst:** `https://<external_url>/mail/mcp`,
  `/smtp/mcp`, `/calendar/mcp`, `/contacts/mcp`, `/drive/mcp`.

## Interner Zugriff ohne Login (optional)

Für Clients auf demselben Gerät, z. B. Open WebUI als App: Mit `internal_access`
startet je aktivem Dienst eine Brücke (`mcp_bridge.py`, dieselbe wie in den
anderen Add-ons dieses Repos) ohne Login:

| Dienst   | URL                                              |
| -------- | ------------------------------------------------ |
| Mail     | `http://<repo-hash>-mailbox-org-mcp:9081/mcp`    |
| SMTP     | `http://<repo-hash>-mailbox-org-mcp:9082/mcp`    |
| Kalender | `http://<repo-hash>-mailbox-org-mcp:9083/mcp`    |
| Adressbuch | `http://<repo-hash>-mailbox-org-mcp:9084/mcp`  |
| Drive    | `http://<repo-hash>-mailbox-org-mcp:9085/mcp`    |

Den Hostnamen zeigt Home Assistant auf der Info-Seite der App, das Log nennt die
fertigen URLs. In Open WebUI: Tool-Server vom Typ MCP (Streamable HTTP),
Authentifizierung **Keine**.

- Die Ports stehen nicht in `config.yaml` und werden nie auf den Host gelegt,
  erreichbar sind sie nur im internen Netz von Home Assistant.
- Anfragen mit `Origin`-Header (Browser) lehnt die Brücke ab.
- **Jede App im internen Netz** kann dann ohne Login Mails lesen und, je nach
  Optionen, ändern. `smtp_allow_send` deshalb nur mit enger
  `smtp_allowed_recipients`-Liste einschalten.
- Ein Server je Dienst für alle internen Clients. Stürzt er ab, startet nur
  seine Brücke neu; Hub und Gate laufen weiter.
- Der öffentliche Zugang über `external_url` bleibt davon unberührt.

## Umzug aus ha-mailbox-org-mcp

Das Add-on lag früher im eigenen Repo `kleinhansda/ha-mailbox-org-mcp`. Mit dem
Umzug ändert sich der Slug, die neue App startet mit leerem `/data`: Optionen
neu eintragen, verbundene Clients (z. B. Claude) einmal neu verbinden.

1. **Optionen notieren:** In der alten App unter „Konfiguration“ alle Werte
   abschreiben, auch die Passwörter (Home Assistant übernimmt sie nicht).
2. **Alte App stoppen**, neue App installieren, Optionen eintragen, starten.
3. **Tunnel umstellen:** Im Cloudflared-Add-on die Dienst-URL für
   `external_url` auf `http://<neuer-hash>-mailbox-org-mcp:8099` ändern.
4. **Clients neu verbinden:** in Claude den Connector entfernen und neu anlegen.
5. **Aufräumen:** alte App deinstallieren, Repo `ha-mailbox-org-mcp` aus dem
   App-Store entfernen.

## Verwaltung

Verbundene Clients anzeigen oder sperren (Terminal-Add-on, Container-Name
ggf. mit `docker ps` prüfen):

```sh
docker exec addon_<repo-hash>_mailbox_org_mcp \
  setpriv --reuid=1000 --regid=1000 --init-groups \
  env DATA_PATH=/data/hub node /app/dist/admin.js clients list
```

## Hinweise

- `/data/hub` enthält OAuth-Schlüssel und Freigaben. Wird es gelöscht, müssen
  sich alle Clients neu verbinden.
- Prüfe gelegentlich unter mailbox.org → Einstellungen → E-Mail → Filter, ob
  unbekannte Weiterleitungen aktiv sind. Dieses Add-on legt keine an, ein
  kompromittiertes App-Passwort könnte es aber.
