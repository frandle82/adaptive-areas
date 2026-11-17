# CLAUDE.md – Adaptive Areas

Diese Datei gibt Claude Code Orientierung für die Arbeit in diesem Repository.
Alle Inhalte, Kommentare für Maintainer, Commit-Beschreibungen und Antworten an den Nutzer erfolgen **auf Deutsch**, sofern nicht anders angegeben (siehe „Sprache“).

## Projektüberblick

**Adaptive Areas** ist eine Home-Assistant-Custom-Integration (Verteilung über HACS), die Home-Assistant-Bereiche („Areas“) zu verlässlichen, anwesenheitsbewussten Zonen macht. Sie erkennt, ob ein Raum belegt oder frei ist, und steuert daraufhin Licht, Klima, Lüfter und Medien automatisch.

- Repository: `frandle82/adaptive-areas` (Lizenz: MIT)
- Integration: `custom_components/adaptive_areas`
- Basiert auf [Magic Areas](https://github.com/jseidl/magic-areas); die ursprünglichen Urheberrechts- und Lizenzhinweise bleiben in `LICENSE` erhalten und dürfen nicht entfernt werden.

## Aufgaben der Integration (Fachlogik)

Bei Änderungen immer prüfen, welche dieser Aufgaben betroffen sind.

### Anwesenheit (Presence)
- Erkennung pro Area aus mehreren Quellen: Bewegungsmelder, Media Player, Device Tracker, BLE-Beacons u. a.
- **Smarte Timeouts:** konfigurierbare Zeit bis zum Löschen der Anwesenheit nach der letzten Bewegung; erneute Bewegung setzt den Timer zurück (keine abrupten Abschaltungen).
- **Presence Hold:** Schalter, um die Anwesenheit manuell zu erzwingen (unzuverlässige Sensoren, Gäste).
- **Wasp in a Box:** Kombination aus Bewegungs- und Tür-/Garagensensoren, damit Licht nicht ausgeht, solange jemand im Raum ist.
- **BLE-Tracker-Integration:** textbasierte BLE-Sensoren (ESPresense, Bermuda, Room Assistant) werden in nutzbare Anwesenheitssensoren umgewandelt.

### Sekundäre Zustände
- `dark` / `bright` (Lichtsensor oder Sonne)
- `sleep` (beliebige Entität)
- `extended` (Raum länger als eine festgelegte Zeit belegt)
- `accented` (Anwesenheit durch Unterhaltung, z. B. Media Player)

### Meta-Areas und Hierarchien
- Areas sind **interior** oder **exterior** und Etagen zugeordnet.
- Virtuelle Meta-Areas (Interior, Exterior, Global, Etagen) bündeln Anwesenheit und Zustände; Logik und sekundäre Zustände werden vererbt bzw. automatisch berechnet.

### Smarte Steuerung
- **Licht-Gruppen** nach Zweck (overhead, task, accent, sleep), steuerbar nach Anwesenheitszustand; optional nur im Dunkeln oder nach `extended`.
- **Klima:** Area-Zustände auf Climate-Presets abbilden (z. B. `eco` bei leerem Raum, `comfort` bei Anwesenheit/Schlaf).
- **Lüfter-Gruppen:** automatisch erzeugte `fan`-Gruppe je Area, gesteuert über Aggregatwerte (Temperatur, Luftfeuchte, CO₂).
- **Area-bewusster Media Player:** Medien/TTS nur in aktuell belegten Räumen.
- **Sensor-Aggregate:** `sensor`/`binary_sensor` der Area nach `device_class` und `unit_of_measurement`.
- **Health-Sensor:** aggregierte Binärsensoren für `gas`, `smoke`, `moisture`, `problem`, `safety`.

### Optionale Module
- **Area Climate** (standardmäßig deaktiviert): Thermik, Feuchte, Schimmelrisiko, Luftqualität, Lüftung, Kühlung, Außenluft-Eignung. Fehlende Dimensionen bleiben `unknown` und werden nicht geschätzt. Außenbereiche liefern nur reduzierte Referenzwerte.
- **Cleaning Tracker:** je Area ein „fällig“-Binärsensor mit gedeckeltem Score, Fälligkeitsstufe, Restzeit und Überfälligkeitsdetails. Steuert **niemals** Geräte.

### Diagnose
- Native HA-Diagnose, Repairs, System Health und ein datenschutzfreundlicher **Decision Trace** der letzten Entscheidungen zur Fehlersuche.

## Repository-Struktur

| Pfad | Inhalt |
| --- | --- |
| `custom_components/adaptive_areas/` | Quellcode der Integration, inkl. `translations/` |
| `tests/` | Testsuite |
| `docs/` | Dokumentation (Quelle in `docs/source/`, u. a. `concepts/`, `features/`, `how-to/`) |
| `design/adaptive_areas/` | Designunterlagen |
| `config/` | Konfiguration für die Entwicklungsumgebung |
| `scripts/` | Hilfsskripte (u. a. `scripts/commit`) |
| `assets/images/` | Bilder |
| `.github/` | Workflows (Validierung, Release) |
| `.devcontainer.json`, `.vscode/` | Entwicklungsumgebung |
| `hacs.json`, `info.md` | HACS-Metadaten |
| `pyproject.toml`, `setup.cfg`, `tox.ini`, `.pre-commit-config.yaml` | Build-, Lint- und Test-Konfiguration |
| `requirements*.txt` | Abhängigkeiten (Laufzeit, Test, Doku) |

> Hinweis: Diese Übersicht stammt aus der README und Dateiliste. Die genauen Befehle und Werkzeugversionen stehen in `tox.ini`, `pyproject.toml`, `setup.cfg` und `.pre-commit-config.yaml` – dort nachsehen, bevor Befehle angenommen werden.

## Entwicklungs-Workflow

### Commits
- **Conventional Commits** sind Pflicht: `typ(bereich): beschreibung`.
- Geänderte Dateien zuerst stagen, dann mit dem Skript committen:
  ```bash
  scripts/commit "type(scope): description"
  ```
  Das Skript validiert die Nachricht. Nicht mit rohem `git commit` umgehen.
- Release-Entwürfe werden automatisch gepflegt; Releases (Draft, Pre-Release, final) erstellen Maintainer über den GitHub-Actions-Workflow **Create Release**.
- Details: `CONTRIBUTING.md`.

### Tests und Qualität
- Tests liegen in `tests/`; Testabhängigkeiten in `requirements-test.txt`, Doku-Abhängigkeiten in `requirements-docs.txt`.
- Vor jedem Commit `pre-commit` (siehe `.pre-commit-config.yaml`) und die Tests über `tox` bzw. die dort definierten Umgebungen ausführen.
- Neue oder geänderte Fachlogik (Anwesenheit, Zustände, Meta-Areas, Steuerung) braucht Tests, insbesondere für Randfälle: Timeouts, mehrere Sensorquellen, Türen/Wasp-in-a-Box, fehlende Daten.

### Dokumentation
- Dokumentation liegt unter `docs/source/`. Neue oder geänderte Funktionen dort beschreiben (Konzepte in `concepts/`, Funktionen in `features/`, Anleitungen in `how-to/`).
- `CHANGELOG.md` und README-Funktionslisten konsistent halten.

## Konventionen für Änderungen

1. **Home-Assistant-Standards einhalten:** Config Flow und Options Flow für Einstellungen, `entity_id` statt `device_id`, native HA-Mechanismen (Repairs, Diagnostics, System Health) nutzen.
2. **Unbekannt bleibt unbekannt:** fehlende Sensordaten nicht raten oder auf Standardwerte setzen; Zustand `unknown` bzw. `unavailable` sauber behandeln.
3. **Keine unbeabsichtigte Gerätesteuerung:** Module, die nur informieren (z. B. Cleaning Tracker), steuern keine Geräte.
4. **Datenschutz:** Der Decision Trace darf keine personenbezogenen oder sensiblen Daten enthalten.
5. **Rückwärtskompatibilität:** bestehende Konfigurationseinträge nicht brechen; bei Änderungen am Datenmodell Migrationen vorsehen.
6. **Kleine, fokussierte Änderungen:** pro Commit ein Thema; keine unabhängigen Refactorings mit Funktionsänderungen mischen.
7. **Lizenz und Attribution:** Hinweise auf Magic Areas und die MIT-Lizenz unverändert lassen.

## Übersetzungen

- Volle Übersetzungsunterstützung, auch für Entitätsnamen.
- Übersetzungsdateien liegen in `custom_components/adaptive_areas/translations/`.
- Neue Texte (Config Flow, Entitäten, Repairs) immer als Übersetzungsschlüssel anlegen, nie hart codieren. Mindestens Englisch pflegen; deutsche Texte ergänzen.

## Sprache

- Kommunikation mit dem Nutzer, Erklärungen, Pläne und Reviews: **Deutsch**.
- Die Projektdokumentation und die Übersetzungsbasis sind überwiegend englisch. Bei Änderungen an bestehenden englischen Dokumenten die dortige Sprache beibehalten, außer es wird ausdrücklich anders verlangt.
- Code, Bezeichner und Commit-Typen (Conventional Commits) bleiben englisch, damit Tooling und Konventionen funktionieren.