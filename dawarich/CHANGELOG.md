# Änderungen

## 1.23.0 (2026-11-15)

- Erste Version im Repo: Dawarich 1.23.0 mit PostgreSQL 17/PostGIS, Redis und nginx für Ingress,
  Startskripte aus thomdev-j/dawarich-home-assistant-addon 1.15.3-2 (AGPL-3.0).
- Start bricht nicht mehr ab, wenn der Geocoder nicht erreichbar ist (nur Warnung).
- `rails db:seed` nach dem Anlegen des Admin-Kontos: Ländertabelle, Regionen, Standard-Tags.
- `rake data:migrate` bei jedem Start wie im offiziellen Image.
- Hintergrundaufgaben eingebettet (`SIDEKIQ_EMBEDDED`), kein eigener Sidekiq-Dienst mehr.
- Umzug aus einer anderen Dawarich-App über `/share/dawarich_umzug.tar.gz`, inklusive
  `secret_key_base`.
- curl nachinstalliert (fehlt im Image seit Dawarich 1.23), kein Asset-Precompile beim Start.
- Neue Option `photon_language`; Photon-Server ohne Standard (statt photon.komoot.io).
- Neue Dawarich-Versionen trägt der Update-Workflow nach bestandenem Test selbst ein.
