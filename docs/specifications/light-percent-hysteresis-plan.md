# Lichtautomatik: prozentuale Hysterese (Implementierungsplan)

Status: Entscheidungen festgelegt (DECIDED / CLOSED, 2026-11-22, siehe `docs/DECISIONS.md`). Umsetzung in Phase B. Die Abschnitte 3 und 6 sind durch die Entscheidung ersetzt.

## 1. Ist-Zustand (belegt im Code)

### Backend

- `helpers/light_policy.py`:
  - `LightPolicyConfig(turn_on_below, turn_off_above)` mit absoluten Lux-Werten. Validierung: endliche, nicht negative Zahlen; `turn_off_above > turn_on_below`.
  - `evaluate_light_policy`: `value <= turn_on_below` → einschalten; `value >= turn_off_above` → ausschalten; dazwischen halten. Die Grenzen sind inklusiv.
  - `light_policy_config_from_feature`: verlangt beide Schlüssel und lehnt andere Werte außer `vacancy_delay` ab.
- Gespeichert werden `features.light.turn_on_below` und `features.light.turn_off_above` (absolute Lux).
- Keine Speicher- oder Schemaänderung nötig, solange diese Schlüssel gleich bleiben.

### Frontend (`frontend/adaptive-areas-panel.js`)

- Formularfelder: `light:threshold` (T) und `light:hysteresis` (H), beide in lx.
- `_lightPairState(form)`: `on = T − H/2`, `off = T + H/2`. Fehler bei unvollständigem Paar, nicht endlichen Werten, `H <= 0` und `on < 0`.
- Unverändertes Speichern sendet die gespeicherten Werte ohne Rundung (über `origOn`/`origOff`).
- Altes Paar ohne `threshold`/`hysteresis`-Felder: `legacy` (direkte Felder `turn_on_below`/`turn_off_above`).

### Bestehende Spezifikation

- `docs/specifications/dashboard-migration-matrix.md`, Abschnitt „Hysteresis definition“, legt die **absolute** Hysterese in lx fest (Beispiel T 100, H 20 → 90/110).
- Diese Festlegung widerspricht der gewünschten Prozentdefinition. Die Änderung ist daher eine Produktentscheidung, keine reine Implementierungsdetail-Änderung.

### Verwandte, andere Hysterese

- `threshold.py` und `const.py` haben `aggregates_illuminance_threshold_hysteresis` mit Prozentangabe (`H/100 × T`), für den Schwellensensor der Aggregate. Das ist eine andere Funktion mit ähnlichem Namen. Die Begriffe müssen in der Dokumentation getrennt bleiben.

## 2. Zielmodell

Für Schwelle T > 0 und Hysterese H in Prozent (0 < H ≤ 200):

- einschalten, wenn Messwert ≤ `T × (1 − H/200)`
- ausschalten, wenn Messwert ≥ `T × (1 + H/200)`

Beispiel: T = 100 lx, H = 20 % → 90 / 110 lx. Dieses Beispiel stimmt mit dem bisherigen absoluten Beispiel überein.

### Umrechnung

- Hinleitung: `on = T(1 − H/200)`, `off = T(1 + H/200)`.
- Rückrechnung aus gespeicherten Grenzen: `T = (on + off) / 2`, `H = 100 × (off − on) / T`.
- Nur symmetrische Paare sind exakt als Prozent darstellbar.

## 3. Grenzfälle

- **T = 0:** Prozentuale Hysterese ist nicht definiert (`on = off = 0`, ungültig, da `off > on` gelten muss). Vorschlag: Prozent-Eingabe bei T = 0 ablehnen und gespeicherte Werte nicht verändern. Entscheidung nötig (siehe Abschnitt 6).
- **H = 200:** `on = 0`. Vorschlag: zulässig (Grenze inklusiv, `on = 0` ist heute erlaubt). H > 200 ist ungültig, da `on < 0` entstünde.
- **H ≤ 0:** ungültig (wie heute).
- **Asymmetrische Altwerte** (z. B. 80/130): nicht exakt als T und H darstellbar. Vorschlag: Anzeige unverändert mit Hinweis; kein stillschweigendes Normalisieren. Speichern ohne Änderung sendet die Originalwerte.
- **Rundung:** Gespeicherte Werte werden ohne Rundung übernommen (wie heute, Test HX2). Anzeige mit einer Nachkommastelle. Berechnete Werte werden erst beim bewussten Ändern gespeichert.
- **Gleichheit:** Grenzen bleiben inklusiv (Tests in `test_light_lux_regression.py`).

## 4. Umsetzungsschritte (nach Freigabe)

1. **Entscheidung dokumentieren:** `docs/DECISIONS.md` und `dashboard-migration-matrix.md` (Abschnitt „Hysteresis definition“) auf Prozent umstellen. Bestehende Abschnitte nicht stillschweigend überschreiben, sondern als ersetzt kennzeichnen.
2. **Backend:** keine Änderung am Datenmodell. `LightPolicyConfig` und die Auswertung bleiben unverändert. Optional: Hilfsfunktionen `percent_pair_from_limits` und `limits_from_percent_pair` in `helpers/light_policy.py`, rein rechnerisch, ohne Persistenz.
3. **Frontend:** `_lightPairState` auf Prozentformel umstellen. Eingabelabels und Hilfetext auf „Hysterese in %“ ändern. Validierung: T > 0, 0 < H ≤ 200. Anzeige berechneter Lux-Grenzen als Hinweis.
4. **Anzeige bestehender Werte:** gespeicherte symmetrische Paare als T und H % zeigen. Asymmetrische Paare unverändert mit Hinweis anzeigen.
5. **Keine Migration:** gespeicherte Werte bleiben. Eine Normalisierung erfolgt nur bei bewusstem Speichern nach Änderung.
6. **Tests:**
   - Python: Umrechnung hin und zurück (T 100, H 20 → 90/110), Grenzfälle T = 0, H = 200, H ≤ 0, asymmetrische Werte, Rundung.
   - Browser-Harness: Eingabe in %, Fehler bei T = 0, unverändertes Speichern sendet Originalwerte, asymmetrischer Hinweis, Konfliktpfad.
7. **Dokumentation:** `docs/source/features/` (Lichtautomatik, falls vorhanden), `CHANGELOG.md`, `docs/CURRENT_STATE.md`, `docs/HANDOVER.md`.

## 5. Aufwand (grob)

- Backend: gering (nur optionale Rechenhilfen).
- Frontend: mittel (Formel, Labels, Validierung, Hinweise, Harness-Anpassungen).
- Tests und Dokumentation: mittel.
- Kein Migrationsaufwand, wenn Speichermodell unverändert bleibt.

## 6. Entscheidungen (festgelegt)

- Prozentdefinition ersetzt die absolute Hysterese. T > 0, 0 ≤ H ≤ 200, Anzeige mit maximal einer Nachkommastelle, keine Zwischenrundung.
- Speichermodell bleibt (`turn_on_below`, `turn_off_above`), keine Schemaänderung, keine Migration, keine zusätzliche Persistenz von `hysteresis_percent`.
- Asymmetrische Altwerte bleiben unverändert und werden nur nach ausdrücklicher Benutzeraktion ersetzt.
- Aggregate-Schwellensensor behält seine eigene Prozent-Hysterese.
- H = 0 ergibt gleiche Grenzen. Das Backend akzeptiert dies (siehe DECISIONS.md).

## 6a. Ehemals offene Entscheidungen (zur Historie)

1. **Produktentscheidung:** Die bestehende Spezifikation sagt absolute lx. Soll die Prozentdefinition sie ersetzen?
2. **Speichermodell:** Nur Anzeige in Prozent, Speicherung weiter als Lux-Grenzen (empfohlen, keine Migration). Alternative: zusätzlich `hysteresis_percent` speichern (Schemaänderung, Migrationspflicht).
3. **T = 0:** Prozent-Eingabe ablehnen (empfohlen) oder bei T = 0 absolute Eingabe erlauben?
4. **Asymmetrische Altwerte:** nur anzeigen (empfohlen) oder beim Speichern normalisieren (verändert Werte, braucht Bestätigung)?
5. **Anzeigegenauigkeit:** eine Nachkommastelle (empfohlen) oder ganze Lux?
6. **Obergrenze:** H = 200 zulassen (empfohlen) oder auf < 200 begrenzen?
7. **Begriffe:** Namen für die beiden Hysteresen (Lichtautomatik gegen Aggregate-Schwellensensor) in der Dokumentation trennen.

## 7. Risiken

- Falsche Erwartung: Nutzer sehen Prozent, die gespeicherten Lux-Werte sind asymmetrisch. Hinweis nötig.
- Rundungsdrift: Umrechnung hin und zurück kann kleine Abweichungen erzeugen. Dagegen hilft das Prinzip „nur bei Änderung neu berechnen“.
- Doppelte Begriffe mit dem Aggregate-Schwellensensor.
- Der Browser-Harness testet das Verhalten, nicht die Entscheidung. Die fachliche Freigabe bleibt manuell.
