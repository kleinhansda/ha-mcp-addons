# Netlify: Hintergrund

Bedienung in [netlify_mcp/DOCS.md](../netlify_mcp/DOCS.md).

## Server

`@netlify/mcp` ist der offizielle MCP-Server von Netlify, nur als npm-Paket mit stdio. Einen
gehosteten Remote-Endpunkt gibt es nicht. Nutzen: Sites auflisten, Deploy-Status und Build-Logs
lesen, Preview-URLs holen, Umgebungsvariablen setzen, Deploys auslösen.

## Image

- **Node 22:** `@netlify/mcp` verlangt mindestens Node 20. Unter Node 18 startet er, verweigert
  aber jeden Tool-Aufruf mit dem Hinweis auf eine veraltete Node-Version.
- **Installation beim Bau statt `npx` beim Start:** `npx -y @netlify/mcp` lädt das Paket bei
  jedem Start neu. Das braucht Internet beim Start, und Version und Abhängigkeiten ändern sich
  unbemerkt. Das Add-on installiert aus `package-lock.json` (feste Versionen und Prüfsummen
  aller Abhängigkeiten). `update.yml` erneuert die Sperrdatei nur, wenn `@netlify/mcp` selbst
  eine neue Version hat.
- **CA-Zertifikate:** Node bringt eigene mit, die Go-Binary des Proxys nicht. Ohne
  `ca-certificates` scheitert die OIDC-Discovery mit `x509: certificate signed by unknown authority`.

## Token

Personal Access Token (User settings → Applications → Personal access tokens), nicht eine
OAuth-Anwendung: Der Server läuft ohne Benutzer und braucht ein sofort gültiges Zugangsmittel.

- Der Token gilt für **alle Sites des Accounts**, eine Einschränkung gibt es nicht. Das
  Ablaufdatum ist der einzige Schadensbegrenzer. Datum notieren.
- Läuft er ab, scheitern die Tool-Aufrufe, das Add-on selbst meldet nichts.

## Getestet

2026-10-18, `@netlify/mcp` 1.19.0 unter Node 22 (x86_64): Tool-Liste ohne Token. Das Tool
`netlify-coding-rules` lädt seine Themen beim Start aus dem Internet und fehlt, wenn das nicht
klappt. Lesend mit Token über einen Portainer-Stack mit demselben Muster seit 2026-10-17 im Einsatz.
