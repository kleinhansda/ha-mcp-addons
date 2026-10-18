# Architektur

Gemeinsames Muster aller Add-ons und die Entscheidungen dahinter.

## Problem

Die meisten MCP-Server laufen nur über stdio: Der Client startet sie als Prozess und spricht
über Ein- und Ausgabe mit ihnen. Claude Desktop und Claude Code können das, die Claude-App
auf dem Smartphone nicht. Sie kennt nur Remote-Connectoren: eine HTTPS-URL, Login per OAuth,
keine Möglichkeit, eigene HTTP-Header (z. B. einen festen API-Schlüssel) einzutragen.

## Muster

Je MCP-Server ein `mcp-auth-proxy`:

1. Der Proxy startet den stdio-Server als Kindprozess, **einmal** beim Start, nicht pro Sitzung.
2. Er bietet ihn als Streamable-HTTP-Endpunkt unter `/mcp` an.
3. Gegenüber Claude ist er ein OAuth-2.1-Server mit Dynamic Client Registration.
4. Angemeldet wird über einen OIDC-Anbieter (z. B. Pocket ID). Optional prüft der Proxy die
   E-Mail-Adresse zusätzlich gegen eine Liste.

Ablauf beim Verbinden eines Connectors:

1. Claude holt `/.well-known/oauth-authorization-server` und registriert sich unter `/.idp/register`.
2. `/.idp/auth` führt zu `/.auth/login` und, bei nur einem Anbieter, direkt weiter zum OIDC-Anbieter.
3. Der Anbieter liefert das Profil, der Proxy gleicht es gegen `oidc_allowed_users` ab.

Folgen:

- **Ein Hostname je MCP-Server.** Der Proxy braucht `/.well-known`, `/.idp` und `/.auth` an der
  Wurzel. Pfade unter einem gemeinsamen Hostnamen gehen nicht.
- **Ein Prozess für alle Chats.** Zustand im Server (z. B. ein geöffnetes Dokument) ist zwischen
  Chats geteilt.
- **Zwei unabhängige Filter** für den Zugang: die Gruppenbeschränkung am OIDC-Client und die
  Nutzerliste im Proxy.

## Netzwerk

- Der Proxy lauscht im internen Netz von Home Assistant (Port 8080, bei ArtCraft 8081 bis 8083).
  Host-Ports sind nicht nötig.
- Ein Cloudflare-Tunnel (Cloudflared-Add-on) veröffentlicht je Server einen Hostnamen mit der
  Dienst-URL `http://<add-on-hostname>:<port>`. Den Add-on-Hostnamen zeigt Home Assistant auf
  der Info-Seite der App.
- TLS terminiert Cloudflare, daher `--no-auto-tls`. Ohne diese Option versucht der Proxy, aus
  der externen URL selbst ein Zertifikat zu holen.
- Keine Cloudflare-Access-App davor, der Login läuft über den Proxy. Regeln wie „Block AI bots“
  brauchen eine Ausnahme für diese Hostnamen.

## Startskript

`common/run.sh` ist in allen Add-ons gleich. Was ein Add-on startet, steht in seiner
`services.sh`: Dienste, Ports, Name der URL-Option, Startbefehl. Das Skript

- liest die Optionen aus `/data/options.json`,
- übergibt die OIDC-Werte als Umgebungsvariablen an den Proxy (nicht als Argumente, sonst
  stünden sie in der Prozessliste) und entfernt sie vor dem Start des MCP-Servers mit `env -u`,
- startet je Dienst eine Schleife: Beendet sich der Dienst, startet er nach 5 s neu, bei
  wiederholtem Sofort-Absturz mit wachsender Pause bis 60 s,
- beendet bei SIGTERM alle Prozesse der Gruppe sauber,
- übernimmt beim ersten Start einmalig Proxy-Daten aus `legacy_auth_dir` (Umzug von einem
  Docker-Stack ohne neue Anmeldung in Claude).

## Versionen

Home Assistant baut ein lokal gebautes Add-on nur neu, wenn sich die Add-on-Version ändert.
„Immer das neueste Release“ im Dockerfile würde deshalb nie greifen und Builds unvorhersehbar
machen. Stattdessen:

- Jedes Dockerfile nennt feste Versionen, jede Datei wird gegen ihre Prüfsumme geprüft
  (`SHA256SUMS.txt` der Releases, Digests der Release-Dateien, `package-lock.json` bei npm).
- `update.yml` prüft täglich die Quellen, baut betroffene Add-ons für aarch64 und amd64 und
  führt `mcp-selftest` aus. Erst danach werden Version und Changelog eingetragen.
- `mcp-selftest` startet jeden Server mit genau dem Befehl aus `services.sh` und erwartet eine
  Antwort auf `tools/list`. Umbenannte Optionen oder Server, die nicht mehr starten, fallen so
  vor dem Update auf. Ob jedes Tool inhaltlich gleich arbeitet, prüft er nicht.

## Entscheidungen

### Add-on statt HACS-Integration

Eine HACS-Integration ist Python-Code im Home-Assistant-Core-Prozess. Der Core-Container
basiert auf Alpine (musl), manche Server brauchen glibc. Außerdem würden fremde Prozesse aus
dem Core gestartet, ein hängender Server träfe Home Assistant selbst. Ein Add-on ist ein
eigener Container mit eigenem Basis-Image, Log, Watchdog und Backup.

### Add-on statt Portainer-Stack

Ein Stack mit selbst gebauten Images funktioniert, hat aber Lücken: Das Dockerfile speichert
Portainer nicht, die Images sind nicht im Backup, Secrets stehen in Stack-Variablen, Updates
heißen „Image neu bauen, Stack neu deployen“, und der Supervisor kennt die Container nicht.
Das Add-on behebt alles davon. Einziger Nachteil: Ein Add-on kann keine Speichergrenze, kein
schreibgeschütztes Dateisystem und keine entzogenen Capabilities pro Container setzen.

### Ein Repo für alle Add-ons

Home Assistant kennt keine Abhängigkeiten zwischen Add-ons. Ein Repo mit mehreren unabhängigen
Add-ons ist eine URL in Home Assistant, ein Satz Workflows und ein gemeinsames Startskript.
Jedes Add-on bleibt einzeln installierbar und hat seine eigene Version.

### mcp-auth-proxy statt MCPHub

[MCPHub](https://github.com/samanhappy/mcphub) (als Home-Assistant-App verfügbar) verwaltet
mehrere MCP-Server zentral und bietet Gruppen für Least Privilege. Für die Claude-App taugt es
nicht: kein OAuth und keine Dynamic Client Registration, der Fernzugriff verlangt einen festen
Bearer-Header, den die App nicht setzen kann. Dazu kommen ein statischer Schlüssel ohne Ablauf,
alle Zugangsdaten an einer Stelle und ein zentraler Ausfallpunkt.

### Drei Connectoren statt einem Sammel-Server

Ein Sammel-Server (z. B. 1MCP) vor mehreren MCP-Servern spart Hostnamen, lädt aber alle Tools
in jeden Chat. Getrennte Connectoren lassen sich pro Chat zu- und abschalten und fallen
einzeln aus. Details zur Prüfung bei ArtCraft in [ARTCRAFT.md](ARTCRAFT.md).

## Sicherheit

- Login nur über den OIDC-Anbieter, Zugang am Client auf eine Gruppe beschränken.
- Token für GitHub und Netlify mit minimalen Rechten und Ablaufdatum, siehe
  [GITHUB.md](GITHUB.md) und [NETLIFY.md](NETLIFY.md).
- Das Backup der App enthält Proxy-Daten und die Optionen samt Tokens im Klartext.
  Backup-Verschlüsselung einschalten, vor allem wenn Backups an externe Ziele gehen.
- Proxy-Daten nicht in einen per Syncthing o. Ä. synchronisierten Ordner legen: Halb
  geschriebene Dateien und Konflikt-Kopien beschädigen die Datenbank, und die Zugangsdaten
  landen auf weiteren Geräten.

## Fehlerbilder des Proxys

| Symptom | Ursache | Lösung |
|---|---|---|
| Login-Seite leer, kein Redirect zum Anbieter, keine OIDC-Zeile im Log | Client-ID oder Secret leer oder falsch. Der Proxy verwirft den Anbieter ohne Fehlermeldung | Optionen prüfen |
| `x509: certificate signed by unknown authority` | Im Image fehlen CA-Zertifikate | `ca-certificates` gehört ins Image (in allen Dockerfiles enthalten) |
| `TLS host is auto-detected, but tlsAcceptTOS is not set` | Proxy will selbst TLS machen | `--no-auto-tls` (im Startskript gesetzt) |
| Anbieter: „not allowed to access this service“ | Gruppenbeschränkung am OIDC-Client | Gruppe zuweisen |
| Anbieter: ungültige Redirect-URI | Callback fehlt | `https://<hostname>/.auth/oidc/callback` eintragen |
| 502 über Cloudflare | Add-on gestoppt oder falscher Port im Tunnel | Log prüfen, Port laut `DOCS.md` |
