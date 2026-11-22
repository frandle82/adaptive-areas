# Beta-CI: nachhaltige Modernisierung (Lösungsvorschlag)

Status: Vorschlag, nicht umgesetzt. Keine großflächige Umstellung der Testarchitektur ohne Freigabe.

## Ausgangslage (belegt)

- Job `test-beta` in `.github/workflows/pytest.yml` ist blockierend. Vorher war er über `continue-on-error: true` verdeckt (seit `5e781c6`).
- Der Job installiert `homeassistant==<neueste Beta>` und `pytest-homeassistant-custom-component` ohne Version.
- Für Home Assistant `2026.11.0b6` existiert kein passendes Harness. Die neueste Harness-Version `0.13.375` pinnt `homeassistant==2026.10.4`. pip fällt deshalb auf `0.2.1` zurück, das `pytest==6.2.2` festlegt. Diese pytest-Version bricht unter Python 3.14 beim Assertion-Rewriting ab.
- Das Harness `0.13.375` selbst ist gegen die Beta inkompatibel: `respx` lädt `httpx` vor der Aliasierung durch Home Assistant (`httpx2`), und das Harness importiert die private Funktion `_clear_logger_overwrites` aus `homeassistant.components.logger`, die in der Beta fehlt.
- Die Home-Assistant-Wheel enthält keine Test-Helfer (geprüft: kein `async_test_home_assistant` im Paket). Die Testinfrastruktur hängt daher vollständig am Harness.

## Ziele

1. Keine Fehlerunterdrückung. Ein Beta-Fehler ist ein roter Lauf.
2. Kein künstlich grüner Beta-Job und keine Stable-Version als Beta ausgeben.
3. Keine fragilen Shims für private Home-Assistant-APIs.
4. Reproduzierbare Abhängigkeiten (Pins mit Begründung und Ablaufdatum).
5. Geringe Kopplung an ein veraltetes Harness.

## Optionen

### Option 1: Harness-Release abwarten (kein Aufwand, Beta bleibt rot)

- Beta-Job rot lassen, bis ein Harness-Release Home Assistant 2026.11.x unterstützt.
- Risiko: Beta-Kompatibilität bleibt unbekannt. Der rote Job muss als `BLOCKED` gelten, nicht als bestanden.
- Aufwand: gering. Dokumentationspflicht im Release.

### Option 2: Eigene Test-Fixture-Basis (mittlerer bis hoher Aufwand)

- Eigene Implementierung der benötigten Harness-Funktionen (`hass`-Fixture, `async_test_home_assistant`, `MockConfigEntry`, Socket-/Timer-Fixtures) auf Basis der öffentlichen Home-Assistant-API.
- Vorteil: Kontrolle über Version und Import-Reihenfolge; kein Shim, sondern eine eigene, gepinnte Fixture-Schicht.
- Nachteil: Die Fixture-Schicht kopiert Verhalten aus dem Harness. Ohne Pflege entsteht Drift zu Home Assistant. Mehrere hundert Tests nutzen das `hass`-Fixture.
- Migrationsschritte:
  1. Inventur: welche Harness-Fixtures und -Helfer nutzen die Tests (`grep -rn "pytest_homeassistant_custom_component\|MockConfigEntry\|async_test_home_assistant"`).
  2. Eigene Fixture-Datei mit denselben Namen einführen, zunächst nur für Stable; Stable bleibt grün.
  3. Dieselbe Fixture-Datei gegen die Beta laufen lassen (eigener Tox-Env mit Beta, ohne Harness-Pin).
  4. Abweichungen zwischen Harness und Fixture-Schicht dokumentieren und testen.
  5. Harness-Abhängigkeit entfernen, sobald Stable und Beta mit der eigenen Schicht laufen.

### Option 3: Beta-Job auf eine Smoke-Teilmenge begrenzen (geringer Aufwand, begrenzte Aussage)

- Nur Tests ohne Harness-Abhängigkeit (reine Logik, `helpers/`, Presence-/Light-Policy-Funktionen) gegen die Beta.
- Vorteil: verifiziert Kernlogik gegen die Beta.
- Nachteil: deckt Config-Flow, Dashboard und Registry nicht ab. Muss als Teilprüfung ausgewiesen werden, nicht als vollständiger Beta-Lauf.
- Der Job bleibt blockierend, die Teilmenge ist klar benannt.

## Empfehlung

1. Sofort: Option 1 mit der bestehenden Dokumentation (`docs/TESTING.md`). Kein Test-Shim, kein `continue-on-error`.
2. Kurzfristig prüfen: Option 3 als zusätzlicher blockierender Job, damit Kernlogik gegen die Beta läuft.
3. Mittelfristig: Option 2 als eigenes Arbeitspaket mit Freigabe und Zeitplan.

## Risiken

- Option 2: Drift zwischen eigener Fixture-Schicht und Home Assistant; erhöhter Wartungsaufwand.
- Option 3: Falsche Sicherheit, wenn die Teilmenge als vollständig dargestellt wird.
- Alle Optionen: Die Beta-Abhängigkeit wächst mit jeder neuen Home-Assistant-Beta. Dazu braucht es eine Pflegeregel (wer prüft Harness-Releases, wie oft).

## Offene Entscheidungen

- Welche Option (1, 2 oder 3 kombiniert) wird umgesetzt?
- Wer pflegt die Harness-Abhängigkeit, und in welchem Rhythmus wird sie geprüft?
- Soll die Beta-Prüfung bei Release-Entscheidungen weiterhin eine dokumentierte Ausnahme erlauben?

## Nicht vorgeschlagen

- Beta-Job nicht blockierend machen.
- Stable als Beta ausgeben.
- Ältere pytest-Versionen festpinnen.
- Private Home-Assistant-APIs per Shim umbiegen.
