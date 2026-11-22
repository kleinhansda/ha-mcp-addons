# Basis: mcp-hub (Node 24, tini, uid 1000 "node"). Multi-arch amd64/arm64.
# Für reproduzierbare Builds zusätzlich auf @sha256:<digest> pinnen.
FROM ghcr.io/ni-c/mcp-hub:0.11.7

USER root

# Einzelserver exakt gepinnt, ohne Install-Skripte
RUN npm install -g --ignore-scripts \
      @ni-c/imap-mcp@0.5.3 \
      @ni-c/smtp-mcp@0.2.0 \
      @ni-c/caldav-mcp@0.1.5 \
      @ni-c/carddav-mcp@0.1.3 \
    && npm cache clean --force

# Bestätigungsdialog von smtp-mcp: mcp-approval kürzt jeden Wert auf 200 Zeichen, damit ein langer
# Wert die Frage nicht aus dem Blick schiebt. Open WebUI zeigt die Frage als eigenes Pflichtfeld unter
# dem Text, deshalb hier 4000 Zeichen: der Mailtext steht vollständig im Dialog. Zeilenumbrüche und
# Steuerzeichen entfernt mcp-approval weiterhin. Nur die Kopie von smtp-mcp; passt das Muster nicht
# (neue Version), bricht der Build ab.
RUN f="$(find "$(npm root -g)/@ni-c/smtp-mcp" -path '*/mcp-approval/dist/confirm.js' | head -n 1)" \
    && [ -n "$f" ] && grep -q 'const MAX_DETAIL_LENGTH = 200;' "$f" \
    && sed -i 's/const MAX_DETAIL_LENGTH = 200;/const MAX_DETAIL_LENGTH = 4000;/' "$f" \
    && grep -q 'const MAX_DETAIL_LENGTH = 4000;' "$f"

# Drive (WebDAV): eigener kleiner Server, Abhängigkeiten exakt gepinnt
COPY webdav/package.json webdav/webdav-mcp.mjs /app/webdav/
RUN cd /app/webdav \
    && npm install --omit=dev --ignore-scripts --no-audit --no-fund \
    && npm cache clean --force

# setfacl: Schreibrechte für uid 1000 im Arbeitsordner unter /share. Fehlt es,
# übergibt run.mjs inbox/ und out/ per chown (kein Abbruch des Builds).
RUN (command -v setfacl >/dev/null 2>&1) \
    || (command -v apk >/dev/null 2>&1 && apk add --no-cache acl) \
    || (apt-get update && apt-get install -y --no-install-recommends acl && rm -rf /var/lib/apt/lists/*) \
    || echo "setfacl nicht installiert, Fallback chown"

# python3 für die interne Brücke ohne Login (internal_access, mcp_bridge.py,
# nur Standardbibliothek). Anders als setfacl ist sie Pflicht: ohne python3
# bricht der Build ab.
RUN (command -v python3 >/dev/null 2>&1) \
    || (command -v apk >/dev/null 2>&1 && apk add --no-cache python3) \
    || (apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*) \
    && python3 -c "import http.server, json, queue, subprocess, threading, uuid"

COPY run.mjs gate.mjs mcp_bridge.py health.mjs /app/

# Das Basis-Image prüft :80/livez (sein Standard-PORT). Hier prüft health.mjs alle Endpunkte,
# die run.mjs gestartet hat: Hub bzw. Passkey-Gate auf 8099 (/livez, nur mit externer URL) und die
# internen Brücken (/health). Ohne passende Prüfung bleibt Home Assistant bei "Wird gestartet"
# oder der Watchdog startet die App immer wieder neu.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD ["node", "/app/health.mjs"]

# Entrypoint läuft als root (liest /data/options.json, setzt Rechte),
# startet den Hub danach per setpriv als uid 1000.
ENTRYPOINT ["tini", "--"]
CMD ["node", "/app/run.mjs"]
