# ArtCraft

ArtCraft MCP (VectorCraft, PhotoCraft, PdfCraft, CADCraft, WordCraft, DeckCraft, GridCraft,
FigCraft, Craft Anything und ein Datei-Server) hat ein eigenes Repository:
**[kleinhansda/artcraft-mcp-ha](https://github.com/kleinhansda/artcraft-mcp-ha)**.
Hintergrund, Testergebnisse und Entscheidungen stehen dort in
[docs/NOTIZEN.md](https://github.com/kleinhansda/artcraft-mcp-ha/blob/main/docs/NOTIZEN.md).

Bis November 2026 lag hier eine eigene Kopie mit drei Apps (`artcraft_mcp`, zuletzt 1.0.10).
Sie wurde entfernt, damit nur eine Fassung gepflegt wird. Wer sie noch installiert hat:

1. Repository `https://github.com/kleinhansda/artcraft-mcp-ha` in Home Assistant hinzufügen und
   **ArtCraft MCP** daraus installieren.
2. Gleiche URLs und denselben OIDC-Client eintragen. Die Proxy-Daten (registrierte Clients)
   liegen in `/data` der alten App und sind nur über deren Backup erreichbar. Einfacher: die
   Connectoren in Claude nach dem Umzug einmal neu verbinden.
3. Im Cloudflare-Tunnel die Dienst-URLs auf den Hostnamen der neuen App umstellen
   (`http://<repo-hash>-artcraft-mcp:8081` usw.), testen, dann die alte App deinstallieren.

Die alte Fassung brachte eigene Schriften mit (Option `fonts_to_work`, Kopie nach
`<work_dir>/fonts/standard` für PdfCraft). Die Beschreibung steht in der Git-Historie dieses
Repositorys (`docs/ARTCRAFT.md`, Abschnitt „Schriften“).
