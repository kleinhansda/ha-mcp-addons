# Google Workspace MCP

Macht ein Google-Workspace-Konto für LLM-Clients wie Open WebUI nutzbar: Mails suchen und lesen,
Termine lesen und anlegen, Drive-Dateien suchen, lesen, anlegen und hochladen. Server ist
[workspace-mcp](https://github.com/taylorwilsdon/google_workspace_mcp) (MIT) von Taylor Wilsdon,
hier für genau ein Konto. Öffentlich hinter [mcp-auth-proxy](https://github.com/sigbit/mcp-auth-proxy)
mit OIDC-Login, intern über die Brücke mit Token.

## Rechte

| Option | Werte | Google-Berechtigung |
|---|---|---|
| Gmail | `aus`, `lesen`, `entwuerfe` | `gmail.readonly`, bei Entwürfen zusätzlich `gmail.compose` – **Senden gibt es nicht** |
| Kalender | `aus`, `lesen`, `schreiben` | `calendar.readonly` bzw. `calendar` |
| Drive | `aus`, `lesen`, `schreiben` | `drive.readonly` bzw. `drive` |

Google erteilt genau diese Rechte, mehr kann die App nicht, auch wenn ein Modell es versucht.
**Werkzeugumfang** `core` reicht meist: mit Gmail lesen, Kalender und Drive schreiben sind es 15
Werkzeuge (u. a. `search_gmail_messages`, `get_events`, `manage_event`, `search_drive_files`,
`get_drive_file_content`, `create_drive_file`). `extended` hat 27.

Drive kann Dateien aus `/share` hochladen: `create_drive_file` mit `fileUrl` `file:///share/…`
(nur aus den Ordnern unter „Erlaubte Ordner zum Hochladen“). Heruntergeladenes landet in
`/share/google`.

> **Vorsicht:** Mails und Dokumente können Anweisungen an das Modell enthalten (Prompt
> Injection). Mit Drive „schreiben“ kann ein Modell Dateien ändern und freigeben. Inhalte gehen
> bei jeder Abfrage an das Sprachmodell.

## Einrichtung bei Google (einmalig)

1. [console.cloud.google.com](https://console.cloud.google.com) mit dem Workspace-Konto (oder
   einem Admin) öffnen, **neues Projekt** anlegen, z. B. „Hannesbräu MCP“.
2. **APIs aktivieren** (APIs & Dienste → Bibliothek): Gmail API, Google Calendar API, Google
   Drive API, für Docs/Sheets-Inhalte auch Google Docs API und Google Sheets API.
3. **OAuth-Zustimmungsbildschirm** (Google Auth Platform → Branding/Zielgruppe): Nutzertyp
   **Intern**. Damit sind nur Konten eurer Workspace-Domain zugelassen, es braucht keine
   Prüfung durch Google, und die Anmeldung läuft nicht nach 7 Tagen ab (das passiert bei
   „Extern“ im Testmodus).
4. **Client anlegen** (Clients → Client erstellen): Anwendungstyp **Desktop-App**. Client-ID und
   Client-Secret notieren.

## Einrichtung der App

1. **Google Workspace MCP** aus „didi's Apps“ installieren.
2. Google-Konto, Client-ID, Client-Secret und die Rechte eintragen, `internal_access` an,
   `internal_token` setzen, starten.
3. Im **Log** steht ein Link `https://accounts.google.com/…`. Ihn im Browser öffnen (auch am
   Handy), mit dem Konto anmelden und zustimmen.
4. Der Browser landet auf einer **nicht erreichbaren Seite** `http://localhost/?state=…&code=…`.
   Das ist richtig. Die komplette Adresse aus der Adresszeile kopieren, in die Option
   **Anmelde-Antwort** einfügen, speichern, App neu starten. Der Code gilt nur wenige Minuten.
5. Im Log: `Anmeldung gespeichert für …`. Die Option „Anmelde-Antwort“ wieder leeren.
6. **Open WebUI:** Admin → Einstellungen → Integrationen → `+`, Typ **MCP (Streamable HTTP)**,
   URL `http://be60cb4b-google-workspace-mcp:9080/mcp`, Authentifizierung **Bearer** mit dem
   `internal_token`.

Ändern sich die Rechte (z. B. Gmail von `lesen` auf `entwuerfe`), erscheint beim Start ein neuer
Link; Schritte 3–5 wiederholen. Die Anmeldung liegt in `/data/google-auth` der App (mit
Refresh-Token, nicht in `/share`). Entziehen: [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

## Konfiguration

| Option | Bedeutung |
|---|---|
| `google_email` | Konto, mit dem sich die App anmeldet |
| `oauth_client_id`, `oauth_client_secret` | Desktop-Client aus der Cloud Console |
| `auth_response` | Adresse nach der Zustimmung, nur für die Anmeldung |
| `gmail`, `calendar`, `drive` | Rechte je Dienst, siehe oben |
| `tool_tier` | `core`, `extended`, `complete` |
| `upload_dirs` | Ordner, aus denen Drive hochladen darf (`:` trennt) |
| `download_dir` | Ablage für Downloads |
| `internal_access`, `internal_token` | interner Zugang über die Brücke, mit Token |
| `public` | öffentliche URL und OIDC für mcp-auth-proxy |
