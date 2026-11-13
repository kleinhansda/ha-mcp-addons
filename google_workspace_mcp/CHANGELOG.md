# Änderungen

Neue Versionen von mcp-auth-proxy trägt der Workflow `update.yml` automatisch ein,
nachdem der Selbsttest auf aarch64 und amd64 bestanden ist. workspace-mcp und seine
Abhängigkeiten sind in `requirements.txt` fest eingetragen und werden von Hand aktualisiert.

## 1.0.3 (2026-11-13)

- mcp-auth-proxy 2.10.2 → 2.10.4

## 1.0.2 (2026-11-09)

- Dokumentation: OAuth-Konfiguration vor dem Client, Hinweise zum Anwendungstyp Desktop-App.

## 1.0.1 (2026-11-09)

- Dokumentation: direkte Links zu jedem Schritt in der Google Cloud Console.

## 1.0.0 (2026-11-09)

- Erste Version: [workspace-mcp](https://github.com/taylorwilsdon/google_workspace_mcp) 2.4.0
  (FastMCP 4.1) für ein Konto (`--single-user`).
- Rechte je Dienst: Gmail (aus/lesen/entwuerfe), Kalender und Drive (aus/lesen/schreiben),
  Werkzeugumfang core/extended/complete. Senden von Mails ist nicht vorgesehen.
- Anmeldung ohne Rückruf-Server: Link im Log, Antwort-Adresse in die Option „Anmelde-Antwort“
  (`gws_auth.py`, OAuth mit PKCE, Desktop-Client). Geänderte Rechte verlangen eine neue Zustimmung.
- Hochladen nach Drive aus `/share` (`file:///share/…`), Downloads nach `/share/google`.
