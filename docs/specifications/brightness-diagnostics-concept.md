# Helligkeit: Diagnoseanzeige und Quellenkonzept (Entwurf)

Status: Entwurf, nicht umgesetzt. Keine Architekturänderung ohne Freigabe.

## 1. Drei Mechanismen (belegt im Code)

| Mechanismus | Quelle | Grenzwert | Verwendet von |
|---|---|---|---|
| Bereichsstatus hell/dunkel | `secondary_states.dark_entity` (Zustand der Entität) | keiner, nur der Zustand | Dashboard, Bereichsstatus |
| Automatischer Schwellensensor | Bereichs-Helligkeitssensor bzw. Aggregat | `aggregates_illuminance_threshold` (Aggregation) | Dashboard, nur wenn als `dark_entity` gewählt |
| Lichtautomatik | globaler Helligkeitssensor | `turn_on_below`, `turn_off_above` (Licht-Funktion) | Lichtsteuerung |

Konsequenz: Der Bereichsstatus hängt nicht von den Lichtgrenzen ab. Ohne konfigurierte `dark_entity` ist ein Bereich immer `dark` (Standardannahme in `binary_sensor/presence.py`).

## 2. Korrigiert in dieser Phase

- `dashboard.py` las `dark_entity` auf oberster Ebene. Die Bereichslogik liest `secondary_states.dark_entity`. Folge: Die Konsistenzprüfung „Dunkelheitsquelle und Bereichsstatus widersprechen sich“ konnte nie auslösen. Behoben über `_dark_source_id`, identischer Pfad wie die Bereichslogik.
- Der bisherige Test `test_dashboard_brightness_consistency_uses_available_dark_source_only` hatte den falschen Pfad kodiert. Er setzt jetzt `secondary_states`.

## 3. Diagnoseanzeige (Konzept)

Die Anzeige soll die Ursache des Bereichsstatus nennen, ohne einen Lux-Grenzwert zu nennen, wenn der Status aus `dark_entity` stammt.

Unterscheidung, nur aus tatsächlichen Backend-Daten:

| Fall | Datengrundlage | Anzeige |
|---|---|---|
| Dunkel durch `dark_entity` | `secondary_states.dark_entity` gesetzt, Zustand `off` | „Dunkel: Entität X meldet aus“ |
| Hell durch `dark_entity` | gesetzt, Zustand `on` | „Hell: Entität X meldet ein“ |
| Standard „dunkel“ | keine `dark_entity` gesetzt | „Dunkel (Standard): keine Dunkelheitsentität konfiguriert“ |
| Entität nicht verfügbar | gesetzt, Zustand `unavailable`/`unknown` | „Unbekannt: Entität X nicht verfügbar; letzter gültiger Zustand bleibt“ |

Die Anzeige nennt keine Lux-Grenzen, weil der Bereichsstatus sie nicht verwendet.

## 4. Tatsächlich verfügbare Diagnosedaten (Payload, `dashboard.py` 743–788)

Vorhanden:
- Präsenz: verfügbar, besetzt.
- Helligkeitssensor: konfiguriert (ja/nein), verfügbar, Wert.
- Policy: Entscheidung (`TURN_ON`, `TURN_OFF`, `HOLD`, `NO_ACTION`) und Grund.
- Übersteuerung: Modus (`NONE`, `FORCE_ON`, `FORCE_OFF`).
- Vakanz: ausstehend, Fälligkeit.
- Zielentitäten: Anzahl gesamt und verfügbar.
- Bereichsstatus: `brightness_detail.dark_source` mit Zustand (Entitäts-ID nur für Administratoren).

Nicht vorhanden (würde neue Felder erfordern):
- Entitäts-ID des globalen Helligkeitssensors (nur Verfügbarkeit und Wert).
- Gespeicherte Ein- und Ausschaltgrenzen.
- Tatsächlich ausgeführte Aktion (Erfolg oder Fehler des Services).
- Unterdrückung durch Dedupe (`_last_dispatched_action`).
- Begründung einer Blockade durch Übersteuerung (der Modus ist sichtbar, der Grund nicht).

Ergänzungen dürfen keine Zustände erfinden: Jede Anzeige muss aus dem Backend-Zustand stammen.

## 5. Dedupe und Übersteuerung

Belegte Ereignisfolge (`tests/test_light_override_sequence.py`):
1. Automatisches Einschalten wird gesendet.
2. Manuelles Ausschalten setzt `FORCE_OFF`.
3. Solange der Bereich besetzt ist, wird ein erneutes Einschalten blockiert, unabhängig von Sensoränderungen.
4. Präsenz unbekannt löscht die Absicht nicht.
5. Bestätigte Leerung hebt die Absicht auf.

Befund: Keine unerwartete Dauerblockade im Code. Die Blockade bis zur Leerung ist beabsichtigte manuelle Absicht. Ob sie im Praxisfall als unerwartet erlebt wird, ist eine Produktfrage und nicht durch Code widerlegt.

Die Dedupe-Regel (`_last_dispatched_action`) bleibt unverändert. Sie wird bei `HOLD`, `NO_ACTION` und bei jeder Gegenaktion (zum Beispiel `TURN_OFF` bei Leerung) zurückgesetzt.

## 6. Architekturvarianten (Bewertung)

1. **Drei Mechanismen beibehalten, transparent darstellen.** Aufwand gering. Risiko: Benutzer muss drei Quellen verstehen. Rückwärtskompatibel, keine Migration. Empfohlen als Kurzfristschritt.
2. **Bereichssensor als optionalen Fallback für die Lichtautomatik.** Aufwand mittel. Risiko: Die Lichtautomatik wertet dann einen anderen Sensor aus als bisher; bestehende Konfigurationen mit globalem Sensor dürfen sich nicht ändern. Nur mit expliziter Priorität und ohne Änderung bestehender Werte.
3. **Gemeinsame Helligkeitsquelle mit expliziten Prioritäten** (globaler Sensor, Bereichssensor, Aggregat, `dark_entity`). Aufwand hoch. Risiko: Schaltverhalten ändert sich für bestehende Bereiche; braucht Migrationsstrategie und Freigabe.

Empfehlung: Variante 1 zuerst (Diagnose und Transparenz), dann Variante 2 nur mit expliziter Freigabe und Regressionstests für bestehende Bereiche.

## 7. Benötigte Laufzeitdaten

- Konfiguration: `features.light`, `secondary_states`, globale Optionen (`global_light_sensor`).
- Zustände zum Fehlerzeitpunkt: globaler Sensor (Wert, Zeitstempel), `dark_entity`, Präsenz, Zielentitäten.
- Dashboard-Payload `light.policy` (Entscheidung, Grund) und `override.mode`.
- Home-Assistant-Logs mit `Light policy dispatch failed`.
- Information, ob vor dem Fehler manuell ausgeschaltet wurde.

## 8. Umsetzungsstand (lokal)

- Implementiert: Korrektur des `secondary_states`-Pfads; Grund des Bereichsstatus im Detail; Diagnose der Lichtautomatik mit Sensor-ID, Grenzen, Entscheidung und Grund, Sperre, Dedupe, Präsenz, Lichtzielen und ausgelöster Aktion („nicht erfasst“, wenn kein Laufzeit-Eintrag existiert).
- Nicht geändert: Schaltlogik, Präsenz, Dedupe- und Übersteuerungsregeln, Persistenz, Schema.
- Ursprüngliche Praxisprobleme bleiben ungeklärt.
