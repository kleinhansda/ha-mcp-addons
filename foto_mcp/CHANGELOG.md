# Änderungen

## 1.4.2 (2026-11-07)

- **Brücke (interner Zugriff):** Falsch benannte Argumente werden umbenannt, wenn eindeutig (ein
  Pflichtfeld fehlt, genau ein unbekanntes Feld ist da, z. B. `command` statt `id`), auch in den
  Schritten eines Batches. Das Protokoll nennt die Umbenennung.

## 1.4.1 (2026-11-06)

- **Nachsicht bei Werkzeug-Argumenten (interner Zugriff):** Schickt ein Modell einen Wert im
  falschen Grundtyp (Text statt Liste, "5" statt 5, "true" statt true), passt die Brücke ihn an das
  Schema an, statt mit einem Validierungsfehler abzubrechen. Das Protokoll nennt das Feld.

## 1.4.0 (2026-11-06)

- **Token für den internen Zugriff (`internal_token`, empfohlen):** Gesetzt, verlangt der interne
  Endpunkt `Authorization: Bearer <Token>`. In Open WebUI bei der Verbindung Authentifizierung
  „Bearer“ wählen und das Token eintragen. Schützt vor anderen Apps und Werkzeugen im internen
  Netz, z. B. den Proxy-Funktionen von ha-mcp. Die Dienste selbst sehen das Token nicht.
  Leer = wie bisher ohne Login; das Protokoll weist dann darauf hin.

## 1.3.1 (2026-11-06)

- Alte „(alt)“-Felder auf oberster Ebene entfernt. Öffentliche URL und OIDC stehen nur noch im
  optionalen Abschnitt „Öffentlicher Zugang (LLM-Client)“.

## 1.3.0 (2026-11-06)

- **Konfiguration neu gegliedert:** Öffentliche URL und OIDC-Felder stehen im aufklappbaren
  Abschnitt „Öffentlicher Zugang (LLM-Client)“, oben bleiben die eigenen Optionen. Werte von
  vorher auf oberster Ebene gelten weiter (als „(alt)“ angezeigt) und gehen beim Update nicht
  verloren; das Protokoll weist darauf hin. Bitte in den Abschnitt übertragen und die alten
  Felder leeren.
- Optionen und Übersetzungen kommen jetzt aus dem gemeinsamen Gerüst (`options.yaml`,
  `common/options/blocks.yaml`).

## 1.2.2 (2026-11-06)

- „Arbeitsordner“ darf jetzt auch `/share` selbst sein. Unterordner regeln dann Skills bzw.
  Anweisungen an das Modell.

## 1.2.1 (2026-11-05)

- Die OIDC-Felder (Konfigurations-URL, Client-ID, Client-Secret) stehen jetzt immer in der
  Konfiguration. Vorher waren sie ohne Wert unter „Unbenutzte optionale Konfigurationsoptionen
  anzeigen“ versteckt. Leer bleiben darf weiterhin, solange keine öffentliche URL gesetzt ist.

## 1.2.0 (2026-11-05)

- **Schräglage: Horizont zuerst.** Gerade Grenze zwischen Himmel und Land/Wasser oder gerade
  Uferlinie über mindestens die halbe Breite, danach senkrechte Kanten (stürzende Linien
  herausgerechnet), zuletzt übrige Waagrechte. Widerspricht ein Horizont starken Senkrechten um
  mehr als 1°, gelten die Senkrechten (meist ist es dann eine Dachkante in Perspektive).
  Gesichter dienen weiter nur dazu, Linien von Personen auszublenden
- **Bildtyp erkennen:** Objekterkennung (NanoDet-Plus, COCO: Personen, Hunde, Katzen, Essen …),
  Szenenhinweise (MobileNetV2, ImageNet: Berge, Wasser, Architektur, Essen, Hunderassen) und
  Bereiche (Himmel, Grün, Wasser aus Farbe und Struktur). Typen: `portraet`, `gruppe`, `tier`,
  `baum`, `landschaft`, `berge`, `meer`, `architektur`, `essen`, `sonstiges`, mit Begründung in
  `neigung_messen`, `ordner_sichten` und im Protokoll
- **Regeln je Bildtyp:** Zuschnitt (Motiv mittig, Originalformat oder Horizont auf ein Drittel),
  dezenter Look, Retusche bei Porträts. Abschaltbar mit `regeln: false`, Typ vorgebbar mit `typ`.
  Bei Person mit Hund bleiben beide im Ausschnitt; Personen ohne erkanntes Gesicht (Rücken,
  Profil) werden über die Objekterkennung gefunden
- **Regler wie in Snapseeds Feinabstimmung:** `helligkeit`, `kontrast`, `lichter`, `schatten`,
  `atmosphaere`, `struktur`, `saettigung`, `waerme`, `schaerfen`, `vignette` (-100..100), global
  oder je Bereich (`himmel`, `gruen`, `wasser`, `person`, `motiv`, `hintergrund`), in
  `optimieren` und im neuen Werkzeug `anpassen` (nur Regler und Effekte, z. B. auf `_final.jpg`)
- Neue Effekte: `tonal` (tonaler Kontrast), `hdr`, `drama`, `vignette`, `lens_blur` (Hintergrund
  weich, Motiv scharf)
- **Rezepte:** Looks als `rezepte/<name>.json` im Arbeitsordner speichern (`rezept_speichern`,
  überschreibt nur mit `ueberschreiben: true`) und mit `rezept` auf eine ganze Serie anwenden
  (`rezepte` zeigt sie)
- **Protokoll:** Jeder Job schreibt `protokoll_<zeit>_<job>.md` neben die Ergebnisse: je Bild
  Tonwert, Entrauschen, Schärfen, Schräglage mit Bezug, Erkanntes, Bildtyp, Zuschnitt, Look mit
  Herkunft (Regel < Rezept < Vorgabe), Effekte, Retusche, Dateien. `job_status` liefert es mit
- Szenenanalyse läuft auf dem unbearbeiteten Bild, damit Sichtung, Messung und Optimierung
  dasselbe sehen. Image ca. 18 MB größer (zwei Modelle aus dem OpenCV Model Zoo, SHA-256 geprüft)

## 1.1.1 (2026-11-04)

- Behoben: Speichern ohne OIDC (nur interner Zugriff) schlug fehl mit „Missing required option
  'oidc_configuration_url'“. Die OIDC-Felder haben keinen leeren Standardwert mehr und stehen
  bei leerer Konfiguration unter „Ungenutzte optionale Konfigurationsoptionen anzeigen“
- Öffentliche URL ist im Formular nicht mehr als Pflichtfeld markiert

## 1.1.0 (2026-11-04)

- Neu: interner Zugriff ohne Login (`internal_access`), z. B. für Open WebUI auf demselben Home
  Assistant, unter `http://<repo-hash>-foto-mcp:9080/mcp`. Nur im internen Docker-Netz
- OIDC-Optionen und `external_url` sind nur noch Pflicht für den öffentlichen Zugang

## 1.0.1 (2026-10-31)

- Keine Stufen mehr in Himmel und Verläufen: Entrauschen nur noch der Farbe (Helligkeit erst ab ISO 1600, halb), Schärfen mit Schwelle, Speichern mit Dithering
- Weißpunkt aus dem hellsten Kanal, dadurch laufen bläuliche Himmel nicht mehr neu aus (vorher bis 10 % ausgefressen)
- Lichter werden über eine kantenerhaltende Basisebene etwas abgesenkt, Struktur in hellen Fassaden bleibt
- `clarity` auf 16-Bit-Helligkeit und nur in strukturierten Bereichen, glatte Flächen bleiben unverändert

## 1.0.0 (2026-10-31)

- Erste Version: eigener MCP-Server mit Python 3.11, OpenCV 4.14 und MediaPipe 1.2 (Face Landmarker)
- Werkzeuge: `ordner_sichten`, `vorschau`, `neigung_messen`, `aussortieren`, `optimieren`, `retusche`, `job_status`
- Optimieren und Retusche laufen als Hintergrundjob, einer nach dem anderen
- Arbeitsordner wie bei ArtCraft MCP (`/share/artcraft/work`), Zugriffe außerhalb werden abgelehnt
- Selbsttest prüft auf beiden Architekturen Schräglage, Gesichtsmodell, Job und Pfadgrenze
