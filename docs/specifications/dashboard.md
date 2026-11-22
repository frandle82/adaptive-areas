# Dashboard-Spezifikation – Adaptive Areas

Normative Referenz für das Dashboard. Verbindlich nach Approval Gate 1 (siehe §16).
Status-Begriffe: Implemented (im Code verifiziert), Approved (freigegeben), Planned (geplant, nicht umgesetzt), In Progress, Verified (durch Tests oder Prüfung belegt).

Stand der Analyse: `main` @ 3b1bd6a. Remote `origin/main` @ b78964f enthält nur eine Versionsänderung in `manifest.json` (geprüft, ohne Auswirkung auf die Spezifikation).
Verified: Testsuite `.tox/ha-stable` (Home Assistant 2026.10.4) mit 563 bestandenen Tests. JSON-Validierung ohne Fehlerausgabe.
Not verified: Lint und pre-commit (nicht in einer Kopie ausgeführt), Sichtprüfung in einer echten Home-Assistant-Instanz.
Die lokale Langfassung in `.agents/knowledge/specs/` ist nicht Bestandteil dieser Spezifikation; alle normativen Aussagen stehen hier.

---

## 0. Produktdefinition

Adaptive Areas is a monitoring, diagnostics and administration dashboard for Home Assistant, combining read-only runtime monitoring with permission-controlled configuration management.

Drei Modi, klar getrennt:
- **Monitoring** (alle angemeldeten Nutzer, soweit die bestehende Leseberechtigung reicht)
- **Runtime-Analyse** (Administrator)
- **Administration** (Administrator, Schreibpfade)

---

## 1. Traceability Matrix

Legende Status: Impl. = Implemented · Teil = teilweise implementiert · Offen = Planned · Entfall = nur mit Freigabe. Die Begriffe entsprechen §0.

| # | Existing Requirement (Soll-Bild / Phase E / Code) | New Requirement (Konzept) | Konflikt | Entscheidung | Status | Acceptance Criteria |
|---|---|---|---|---|---|---|
| T1 | Admin-Schreibpfade: `create_area`, `update_area`, `delete_area`, `update_global_configuration` | Konzept „read-only“ | Ja | Schreibpfade bleiben, als Administration abgegrenzt | Impl. | Non-Admin erhält `forbidden` bei allen 4 Befehlen (Test, s. §3) |
| T2 | Navigation: Überblick, Bereiche, Lichtsteuerung, Klimasteuerung, Einstellungen | Monitoring, Runtime, Admin-Gruppen | Ja (Struktur) | Gruppierung als Navigation, Funktions-Tabs bleiben | Teil | Alle heutigen Ansichten erreichbar; keine Funktion entfällt |
| T3 | Lichtsteuerung nur über Funktions-Tab (Soll §Lichtsteuerung) | Lighting im Area-Detail | Doppelung | Ein Ort je Information: Detail verlinkt auf Lichtsteuerung | Offen | Keine doppelte Darstellung derselben Felder |
| T4 | Klima: genau 6 Felder, keine Sollwerte (Soll §Klimasteuerung) | Environment-Anzeige | keine | Sollwerte bleiben verboten | Offen | Keine Temperatur-Sollwerte im Frontend |
| T5 | Verbotene sichtbare Begriffe (Soll §Verboten) | Technische Begriffe nur in Admin-Diagnostik | keine | Übersetzte Anzeige; Keys nie sichtbar | Offen | Test: keine Keys/Enums im sichtbaren Text (DE/EN) |
| T6 | Eigenes EN/DE-Objekt im Panel (Ist) | Zentrale `dashboard_texts/*.json` (2026-11-22; vorher `translations/*.json`, siehe §8) | Ja | `adaptive_areas/get_dashboard_texts`, Fallback `en` (§8) | Offen | Test je Sprache; fehlende Schlüssel → EN |
| T7 | Keine Gerätesteuerung, keine generische Steuerung | Keine neuen Steuerpfade | keine | Nicht eingeführt | Impl. | Kein neuer Befehl mit Service-Aufruf |
| T8 | Area-Detail: Presence, Lights, Environment, Sources, Controls (Ist) | Area-Details gruppiert, Trace-Auszug | keine | Gruppierung, Trace-Auszug in Area-Detail | Teil | Gruppen gemäß §12 |
| T9 | Environment-Daten in Summary/Detail (Ist) | Environment-Ansicht | keine | Ansicht aus vorhandenen DTOs | Teil | Nur vorhandene Felder |
| T10 | Cleaning-Daten in Summary (Ist) | Cleaning-Ansicht | keine | Ansicht aus vorhandenen DTOs | Teil | Nur vorhandene Felder |
| T11 | Room Usage in Summary (Ist) | Room-Usage-Ansicht | keine | Ansicht aus vorhandenen DTOs | Teil | Nur vorhandene Felder |
| T12 | Diagnostics: `get_diagnostics` (admin) + native HA-Diagnose | Diagnostics-Ansicht | keine | Verweis auf native Diagnose, kein Duplikat | Teil | Kein doppeltes Diagnose-Panel |
| T13 | Decision Trace: Ringpuffer 20 je Area, nur native Diagnose (Ist) | Trace-Timeline + Befehl | Fehlt im Panel | `get_decision_trace` (§4) | Offen | Siehe §4 |
| T14 | Reason-Codes (Ist, teilweise) | Erweiterung | Keine | Nur Mapping vorhandener Gründe, §5 | Offen | Siehe §5 |
| T15 | README: „read-only“ | Admin-Verwaltung vorhanden | Ja | README nach Freigabe korrigieren | Offen | README konsistent mit Produktdefinition |
| T16 | ROADMAP Phase E: Soll-Bild als Referenz (`.agents`-Pfad) | Versionierte Referenz | Ja | Pfad auf `docs/specifications/dashboard.md` | Offen | Keine `.agents`-Referenz in versionierten Dateien |
| T17 | CURRENT_STATE: „visuelle Prüfung in echter HA-Instanz ausstehend“ | Sichtprüfung | Offen | Plan Paket 19 | Offen | Dokumentierter Prüfbericht |
| T18 | Light/Climate/Settings nur Admin (Ist, Phase E) | Admin-only für Runtime, Konfiguration | keine | Beibehalten | Impl. | Test positiv/negativ (§3) |
| T19 | Non-Admin: Overview und Area-Detail lesbar (Ist) | Beibehalten (Freigabe Gate 2) | keine | Beibehalten | Impl. | Test positiv (§3) |
| T20 | `controls` und `sources` mit Entity-IDs für alle Nutzer (Ist) | Rollenabhängige Aufbereitung | Ja, Datenschutz | Entscheidung E2 (§3.1) | Approved, Planned | Non-Admin-Negativtests auf Entity-Felder; Admin-Antworten unverändert |
| T21 | Presence-Quelle `presence_hold` (Ist) | Presence Hold sichtbar als Grund | keine | Mapping, keine Änderung der Logik | Offen | §5 |
| T22 | Keine Dirty-State-Infrastruktur (Phase E, Non-Goal) | Dirty-State bei Live-Updates erhalten | Ja | Mindestens: Eingaben nicht überschreiben | Offen | Test: Live-Update überschreibt Formular nicht |
| T23 | Fehler lokal und verständlich (Soll §Fehler) | Zustandsbehandlung | keine | Übersetzte Fehlerkeys | Teil | §7 |
| T24 | Mobile: Formulare untereinander (Soll §Responsive) | Responsive Shell | keine | übernommen | Offen | Browser-Prüfung 390/768/1280 px |

---

## 2. Informationsarchitektur und Navigation

Hauptnavigation (sichtbar je Rolle):

| Eintrag | Sichtbar für | Inhalt |
|---|---|---|
| Überblick | alle | Status, Kennzahlen, Area-Karten, Filter, Suche |
| Bereiche | alle | Area-Liste, Area-Detail (Gruppen) |
| Environment | alle, wenn Daten vorhanden | Messwertvergleich |
| Cleaning | alle, wenn Feature aktiv | Fälligkeit |
| Room Usage | alle, wenn Feature aktiv | Nutzung |
| Lichtsteuerung | Admin, wenn Feature aktiv | Licht-Runtime und Gruppen |
| Klimasteuerung | Admin, wenn Feature aktiv | Klima-Runtime |
| Decision Trace | Admin | Timeline |
| Diagnose | Admin | technische Übersicht, Verweis auf native Diagnose |
| Einstellungen | Admin | globale Optionen |

Regeln:
- Ein Eintrag erscheint nur, wenn Berechtigung und Feature/Daten vorliegen. Verschwindet ein aktiver Eintrag: Fallback auf Überblick (Soll §Navigation).
- Environment, Cleaning, Room Usage bleiben kontextbezogen, wenn sie nur in wenigen Areas aktiv sind: Die Navigation zeigt sie nur bei mindestens einer Area mit Daten.
- Keine Unteransichten über drei Ebenen. Area-Detail hat Abschnitte, keine Tabs in Tabs.
- Hauptnavigation ist mobil ein horizontal scrollbares Tab-Band mit Touch-Ziel ≥ 44 px.

Component Hierarchy (konzeptionell, keine Dateinamen):

```
Panel Shell
├── Header (Titel, Rollen-Hinweis)
├── Navigation
└── View
    ├── Overview
    │   ├── KPI Row (KPI Card ×4)
    │   ├── Filter Bar (Chips, Suche)
    │   └── Area Grid
    │       └── Area Card ×n
    ├── Areas
    │   ├── Area List
    │   └── Area Detail
    │       ├── Presence Section
    │       ├── Secondary States Section
    │       ├── Sources Section
    │       ├── Environment Section
    │       ├── Cleaning Section
    │       ├── Room Usage Section
    │       ├── Trace Excerpt (Admin)
    │       └── Health Section
    ├── Environment / Cleaning / Room Usage (Monitoring-Ansichten)
    ├── Lighting / Climate (Admin)
    ├── Decision Trace (Admin)
    ├── Diagnostics (Admin)
    └── Settings / Area Editor (Admin)
```

---

## 3. Permission Matrix

Grundlage: `websocket.py` (12 registrierte Befehle, verifiziert in `async_register_websocket_commands`). Admin-Prüfung über Dekorator `require_admin`, serverseitig.

| WebSocket Command | Read/Write | Auth | Admin | Zugängliche Daten | Privacy | Vorhandene Tests | Zusätzlich nötig |
|---|---|---|---|---|---|---|---|
| `adaptive_areas/get_overview` | Read | ja | nein | Areas, Status, Lichtzählung, `controls` (entity_id, Name, Status), `sources`, Environment/Cleaning/Room-Usage-Teile | **Befund B1**: Entity-IDs für alle Nutzer | ja | Non-Admin-Positivtest; Negativtest auf Entity-Felder (nach Entscheidung) |
| `adaptive_areas/get_area` | Read | ja | nein | Detail inkl. `light_groups` mit `sources` (Entity-IDs und Status), `controls`, `sources`, Environment, Aggregates | **Befund B1** | ja | Non-Admin-Positivtest; Entity-Feld-Test nach Entscheidung |
| `adaptive_areas/get_diagnostics` | Read | ja | **ja** | Runtime-Issues, Aggregationen | intern | ja | Non-Admin-Negativtest |
| `adaptive_areas/get_area_configuration` | Read | ja | **ja** | vollständige Konfiguration | Konfiguration | ja | Non-Admin-Negativtest |
| `adaptive_areas/get_light_runtime_status` | Read | ja | **ja** | Licht-Runtime | Entity-Bezug | ja | Non-Admin-Negativtest |
| `adaptive_areas/get_climate_runtime_status` | Read | ja | **ja** | Klima-Runtime | Entity-Bezug | ja | Non-Admin-Negativtest |
| `adaptive_areas/get_global_configuration` | Read | ja | **ja** | Wetter-/Helligkeits-Entity | Entity-Bezug | ja | Non-Admin-Negativtest |
| `adaptive_areas/update_global_configuration` | Write | ja | **ja** | globale Optionen | Validierung | ja | Non-Admin-Negativtest |
| `adaptive_areas/create_area` | Write | ja | **ja** | neue Area | – | ja | Non-Admin-Negativtest |
| `adaptive_areas/update_area` | Write | ja | **ja** | Area-Konfiguration | Erhalt anderer Daten | ja | Non-Admin-Negativtest |
| `adaptive_areas/delete_area` | Write | ja | **ja** | Area löschen | irreversibel | ja | Non-Admin-Negativtest |
| `adaptive_areas/subscribe_updates` | Read (Stream) | ja | nein | Änderungs-Signal ohne Daten | keine Nutzdaten | ja | Abmeldung bei Verbindungsende |
| `adaptive_areas/get_decision_trace` (neu) | Read | ja | **ja** | Trace-DTO (§4) | Allowlist | – | Siehe §4 |

**B1 – Entscheidung (Approved):** Die Leseberechtigungen für Nicht-Administratoren bleiben erhalten. Die Daten werden serverseitig rollenabhängig aufbereitet (§3.1). Das Frontend ist keine Datenschutzgrenze.

**Befund (Ist, Implemented):** `build_overview` und `build_area_summary` enthalten `controls` (mit `entity_id`, Anzeigename, Status, `actions`) und `sources` (Entity-IDs mit Status). `build_area_detail` enthält zusätzlich Entity-IDs in `light_groups[].sources` und `presence.sources`. Diese Felder sind heute für alle angemeldeten Nutzer lesbar.

**Prüfauftrag vor Umsetzung:** Die Textsuche im Panel fand keine Anzeige von `controls` oder `sources` in der Übersicht. Die Verwendung ist vor der Änderung vollständig zu prüfen (Paket 4).

**Befund B2:** `get_overview` und `get_area` sind ohne Admin-Prüfung. Das ist beabsichtigt (Entscheidung E2).

### 3.1 Rollenabhängige Datenaufbereitung (Approved, Planned)

Die Aufbereitung erfolgt in `dashboard.py` pro Verbindung anhand des Benutzers. Der Befehl bleibt derselbe; die Antwort hängt von der Rolle ab. Gleiche Top-Level-Schlüssel bleiben erhalten, wo möglich.

| Feld | Admin | Nicht-Admin | Begründung |
|---|---|---|---|
| `id`, `name`, `type`, `occupied`, `active_states` | unverändert | unverändert | Freigegebene Monitoring-Daten |
| `presence.state` | additiv: Wert `unknown` ergänzt | additiv: Wert `unknown` ergänzt | Presence State |
| `counts.physical_occupied`, `counts.physical_clear`, `counts.physical_unknown` | neu (additiv) | neu (additiv) | Physische Bereiche, dieselbe Präsenzsemantik wie die Karten; Meta-Bereiche nicht gezählt |
| `occupied` (Boolean) | unverändert (Entscheidung der Automatik) | unverändert | Kein Nullable-Wert; unbekannt wird über `presence.state` angezeigt |
| `presence.sources` (Detail) | Liste mit Entity-IDs | `{"total": n, "active": m}` | Aggregierte Presence-Information |
| `brightness.state`, `illuminance` | unverändert | unverändert | Freigegebener Messwert |
| `brightness_detail.dark_source` | unverändert | entfällt | Sensor-Identität |
| `warning_count` | unverändert | unverändert | Health-Hinweis |
| `lights.on`, `lights.total` | unverändert | unverändert | Aggregat |
| `lights.groups[]` (id, name, on, total) | unverändert | entfällt | Geschützte Lighting-Daten |
| `light_groups[]` (Detail, mit `sources`) | unverändert | entfällt | Geschützte Lighting-Daten, Entity-IDs |
| `environment` | unverändert | unverändert | Freigegebene Monitoring-Messwerte |
| `room_usage`, `cleaning` | unverändert | unverändert | Freigegebene Monitoring-Daten |
| `aggregates` (Detail) | unverändert | unverändert | Aggregierte Messwerte |
| `enabled_features` | unverändert | unverändert | Allgemeiner funktionaler Zustand |
| `sources[]` (Summary, Detail) | Liste mit Entity-IDs und Status | `{"total": n, "available": m}` | Keine konkreten Quell-Identifikatoren |
| `controls[]` | unverändert | Schlüssel fehlt | Entity-IDs, Gerätenamen, Aktionen |

Regeln:
- Nicht-Admin: fehlende Schlüssel werden nicht als `0`, `false` oder leere Liste interpretiert. Das Frontend zeigt für Nicht-Admins keine Abschnitte, die auf entfernte Schlüssel angewiesen sind.
- Admin-Antworten bleiben byte-kompatibel zum heutigen Stand, außer einer ausdrücklich dokumentierten Änderung.
- `subscribe_updates` sendet nur ein Signal ohne Nutzdaten. Der anschließende Abruf läuft über den Befehl und damit über die Rolle der Verbindung.
- Clientseitiges Caching ist pro Verbindung und Benutzer. Ein Rollenwechsel erfordert eine neue Sitzung.
- Fehlermeldungen und Diagnosen dürfen keine Entity-IDs enthalten, die für Nicht-Admins sichtbar würden (Test: negative Tests auf Fehlertexte).
- Verbraucher: Prüfung aller Panel-Stellen und Tests in `tests/test_dashboard.py` vor der Umsetzung. Ergebnis wird in `CURRENT_STATE.md` dokumentiert.

Regeln:
- Navigation blendet Admin-Einträge für Nicht-Admins aus (Kosmetik). Serverseitige Prüfung bleibt die Grenze.
- Berechtigungstests: positiv (Admin erhält Daten) und negativ (Non-Admin erhält `unauthorized`/`forbidden` bei allen Admin-Befehlen) je Befehl.

---

## 4. Decision Trace API

### 4.1 Befehl

- Name: `adaptive_areas/get_decision_trace`
- Typ: Read-only, `require_admin`.
- Parameter:
  - `area_id` (Pflicht, `str`, muss existierende Area sein; sonst Fehler `area_not_found`, wie bei `get_area`).
  - `limit` (optional, `int`, Bereich 1–20, Standard 20). Die Validierung erfolgt über `vol.All(vol.Coerce(int), vol.Range(min=1, max=20))`.
- Keine Zeit-, Cursor- oder Typfilter in v1. Begründung: Der Puffer ist klein und in-memory; Filter nach Typ können im Frontend erfolgen.

### 4.2 Antwort-DTO (Allowlist)

| Feld | Typ | Quelle | Validierung |
|---|---|---|---|
| `timestamp` | `str` ISO-8601 UTC mit `Z` | `entry["timestamp"]` | Format prüfen, sonst Eintrag verwerfen |
| `feature` | `str` | `entry["feature"]` | Allowlist Feature-Namen (§4.3) |
| `trigger` | `str` | `entry["trigger"]` | Allowlist Trigger (§4.3) |
| `area_state` | `list[str]` | `entry["area_state"]` | nur bekannte Zustandsnamen, max. 10 |
| `decision` | `str` | `entry["decision"]` | Allowlist (§4.3) |
| `outcome` | `str` | `entry["outcome"]` | Allowlist: `observed`, `evaluated`, `considered`, `skipped`, `executed`, `failed`, `tracked` |
| `reason_codes` | `list[str]` | `entry["reason_codes"]` | Allowlist (§5), max. 5 |
| `target_count` | `int` ≥ 0 | `entry["target_count"]` | Obergrenze 1000 |
| `from` | `str \| null` | `entry.get("from")` | nur Zustandsnamen aus Allowlist, sonst `null` |
| `to` | `str \| null` | `entry.get("to")` | nur Zustandsnamen aus Allowlist, sonst `null` |
| `exception_class` | `str \| null` | `entry.get("exception_class")` | Regex `^[A-Za-z_][A-Za-z0-9_]{0,63}$`, sonst `null` |

Nicht im DTO: `area_id` als Feld (steht außen), jegliche Entity-ID, Name, Quelle, Attribut, Freitext.

Antwort: `{"area_id": "<id>", "entries": [ ... ], "capacity": 20}`. `capacity` ist eine Konstante aus dem Puffer, keine Berechnung.

### 4.3 Begründung der Validierung

Eine Feldliste allein reicht nicht. Die Inhalte sind heute teils freie Strings:
- `decision` ist in einigen Stellen dynamisch: `service` (switch_groups, fan_control) und `f"primary_{key}_source_…"` (environment). Ohne Allowlist könnte dort jeder Wert landen.
- `trigger` ist für Teile des Codes dynamisch (`trigger=trigger` in `light.py`, `fan_control.py`).
- `exception_class` ist der Klassenname einer Ausnahme. Drittanbieter-Ausnahmen können beliebige Namen liefern. Die Regex begrenzt Länge und Zeichen.
- `from`/`to` werden aus Zustandsnamen gebildet, aber nicht geprüft.

**Entscheidung:** Der Trace wird beim Export (`get_decision_trace`) validiert. Unbekannte Werte werden nicht angezeigt, sondern als `"other"` ersetzt. Das Frontend zeigt dann „Unbekannte Entscheidung“. Der Ringpuffer selbst bleibt unverändert. Die Validierung am Export verhindert keine Logik, sondern nur die Anzeige. Eine Validierung bei `record()` wäre eine Änderung der Instrumentierung und ist nicht nötig.

Allowlist-Quelle: eine Konstantenliste in einem Modul, das die bestehenden Werte abdeckt. Ein Test muss prüfen, dass jeder Aufruf von `trace_decision` nur Werte aus dieser Liste erzeugt (statische Suche über `custom_components/`).

### 4.4 Datenschutz

- Keine Entity-IDs, Namen, MAC-Adressen, BLE-IDs, Personenbezüge. Die Instrumentierung enthält laut Lesung keine solchen Werte; die Allowlist stellt das sicher.
- Keine neue Persistenz. Kein Export in eine Datei.
- Admin-only.

### 4.5 Frontend

- Timeline, neueste zuerst, mit Zeitstempel, Area, Feature (übersetzt), Trigger (übersetzt), Entscheidung, Ergebnis, Gründe.
- Fehlt `reason_codes` oder ist leer: „Keine Begründung aufgezeichnet.“
- Filter: Area, Feature, Ergebnis. Zeitbereich nicht in v1.
- Area-Detail zeigt die letzten 5 Einträge der Area als Auszug.
- Globale Ansicht: Nicht Bestandteil der ersten Version (Entscheidung E4). Die Architektur erlaubt eine spätere Erweiterung ohne neue Persistenz. Keine Simulation durch Einzelabfragen aller Areas.

---

## 5. Reason-Code-Erweiterung

### 5.1 Bestehende Gründe

Quelle: `binary_sensor/presence.py`.

- `_reason_for_source(entity_id)` ermittelt den Grund bereits aus dem Quelltyp:
  - Meta-Area-Kind: `meta_child_occupied`
  - `ble_tracker` im Entity-Namen: `ble_presence`
  - `wasp_in_a_box` im Entity-Namen: `wasp_presence`
  - `presence_hold` im Entity-Namen: `presence_source_on`
  - Gerätklasse `motion`: `motion_detected`
  - sonst: `presence_source_on`
- `_last_reason` wird öffentlich als Attribut `last_reason` ausgegeben (`ATTR_LAST_REASON`).
- Timeout: `clear_timeout_expired`.
- Sekundärzustände: `secondary_state_change`, `extended_state_entered`.

**Kernbefund:** Die Trace-Transitionen in `_trace_state_transitions` verwenden generische Gründe (`presence_detected`, `presence_cleared`), obwohl `self._pending_reason` zu dem Zeitpunkt den Quellgrund enthält. Die Trace-Methode wird in `_update_area_states` aufgerufen, bevor `_update_explanation` den `_pending_reason` verbraucht. Das muss im Test bestätigt werden.

### 5.2 Matrix

| # | Existing Decision | Existing Trigger | Existing Reason-Code | Proposed Reason-Code | Recording Location | Data Availability | Privacy Impact | Required Tests |
|---|---|---|---|---|---|---|---|---|
| R1 | `state_transition` (Occupied) | `state_recalculated` | `presence_detected` (generisch) | Ersetzen durch vorhandenen `_pending_reason` (`motion_detected`, `ble_presence`, `wasp_presence`, `presence_source_on`, `meta_child_occupied`) | `presence.py::_trace_state_transitions` | Ja, bereits berechnet | Keine: nur Konstanten | Quelle je Typ; Fallback ohne Quelle |
| R2 | `state_transition` (Clear) | `state_recalculated` | `presence_cleared` (generisch) | `clear_timeout_expired` (vorhanden) bzw. `meta_child_cleared` | wie R1 | Ja | keine | Timeout vs. Meta-Kind |
| R3 | `state_transition` Extended/Sleep/Accent | `state_recalculated` | teils generisch | vorhandene Codes `extended_state_entered`, `secondary_state_change`, `*_state_inactive` | wie R1 | Ja | keine | Je Zustand ein Test |
| R4 | `presence_started` (Room Usage) | `area_state_changed` | vorhandene Codes in `room_usage.py` | keine Änderung | `room_usage.py:211` | Ja | keine | Bestehende Tests |
| R5 | `play_media` (Media) | `play_media` | `eligible_area_active` | Keine Ergänzung; `media_active` ist vorhandenes Konzept, aber kein Code im Presence-Pfad | `area_aware_media_player.py` | Ja | keine | – |
| R6 | Presence über Medienplayer-Quelle | Presence-Update | `presence_source_on` (Default) | `media_active` **nur** bei Medienquelle, ergänzt in `_reason_for_source` | `presence.py::_reason_for_source` | Ja (Entity-Domain, kein Name) | keine Entity-ID im Ergebnis | Medienquelle mit/ohne Gerätklasse |
| R7 | Presence über Hold | Presence-Update | `presence_source_on` | `presence_hold_active` bei `presence_hold` im Entity-Namen | `_reason_for_source` | Ja | keine | Hold an/aus |
| R8 | Wasp in a Box (Tür) | Presence-Update | `wasp_presence` | Kein neuer Code; Tür-Verriegelung nur mit eigenem Trace-Aufruf in `wasp_in_a_box.py` | `wasp_in_a_box.py` (Ort noch nicht im Detail gelesen) | Teilweise, zu prüfen | keine | **Offen**: Ob der Zustand „Tür geschlossen hält Belegung“ im Code eindeutig erkennbar ist |
| R9 | Dunkel und belegt (Licht) | `presence_activity` / `area_state_changed` | `darkness_requirement_not_met` (vorhanden) | **Kein neuer Code**: `occupied_and_dark` wäre eine Kombination aus `occupied` und `dark_state_active` | `light.py` | Ja | keine | Bestehende Licht-Tests |
| R10 | Presence-Abschaltung | `state_recalculated` | `clear_timeout_expired` | **Kein neuer Code**: `presence_timeout_elapsed` = vorhanden | `presence.py` | Ja | keine | Timeout-Test |
| R11 | Area frei | `state_recalculated` | `presence_cleared` | **Kein neuer Code**: `area_cleared` = Dublette | `presence.py` | Ja | keine | – |
| R12 | Fan/Switch-Service fehlgeschlagen | `aggregate_sensor_changed` | `action_failed` (+ `exception_class`) | keine | `fan_control.py`, `switch/__init__.py` | Ja | `exception_class` als Klassenname, validiert | Fehlerpfad |

**Konsequenzen:**
- **Öffentliche Attribute (Entscheidung E5):** `last_reason` bleibt unverändert. Neue Gründe (`media_active`, `presence_hold_active`) werden ausschließlich im Trace erfasst, über eine separate Zuordnung, die nicht in `_reason_for_source` liegt. Nur Gründe, die zum Entscheidungszeitpunkt eindeutig bekannt sind, werden erfasst.
- Die fachliche Logik (Zustände, Timer, Entscheidungen) bleibt unverändert. Die Instrumentierung darf keine Entscheidung auslösen (Test: gleiche Zustandsfolge mit und ohne Trace).

**Ergebnis der Prüfung:** Von den acht vorgeschlagenen Codes sind fünf bereits als Konzept vorhanden (`motion_detected`, `ble_presence`, `presence_timeout_elapsed` = `clear_timeout_expired`, `area_cleared` = Dublette, `occupied_and_dark` = Kombination). Neu wären nur `media_active` und `presence_hold_active`. `door_interlock_active` ist Wasp-spezifisch und braucht eine Prüfung.

**Trigger statt Reason:** Für „welche Quelle“ eignet sich das Feld `trigger` oder ein Quelltyp besser als ein weiterer Reason-Code, wenn die Quelle mehrere Gründe betrifft. Der Trace kann mehrere `reason_codes` je Eintrag tragen (Liste), daher ist die Mehrquellen-Darstellung ohne Erfindung möglich (z. B. `motion_detected` und `ble_presence` im selben Ereignis, wenn beide aktiv waren). Aktuell wird nur ein Grund je Transition gespeichert. Mehrquellen-Darstellung setzt voraus, dass alle aktiven Quellen tatsächlich bekannt sind (Test).

---

## 6. Data Mapping

| View | UI-Komponente | WS-Befehl | DTO-Feld | Typ | Verfügbarkeit | Berechtigung | Fehlend | Übersetzungsschlüssel | Status |
|---|---|---|---|---|---|---|---|---|---|
| Überblick | KPI „Physische Areas“ | `get_overview` | Zählung ohne Meta (`type == "area"`) | int | immer | alle | 0 ist gültig, `unknown` nicht | `kpi.areas` | Vorhanden (Zählung neu im Frontend, siehe Risiko) |
| Überblick | Etagen-Gruppierung | `get_overview` | `floor_id`, `floor_name` (Schritt 4.3) | str/null | immer | alle | `null` → „Ohne Etage“; ID ohne Name → „Etage unbekannt“ | `floor.*` | Vorhanden (additiv) |
| Überblick | Meta-Mitglieder | `get_overview` | `members` (nur Meta-Bereiche, Schritt 4.3) | list[str] | immer für Meta | alle | nicht geladene Kinder fehlen | `meta.*` | Vorhanden (additiv) |
| Umgebung/Reinigung | Reinigungsstand | `get_overview` | `cleaning` (`cleaning_state`, `due`, `remaining_minutes_to_due`) | obj/null | optional (Feature `room_usage`) | alle | `null` → „Keine Reinigungsdaten“; Feature aus → ausgeblendet | `cleaning.*` | Vorhanden (Schritt 4.4) |
| Raumnutzung | Anwesenheit seit Reinigung, aktuelle Belegung | `get_overview` | `room_usage` (`presence_minutes_since_cleaning`, `current_occupancy_duration_seconds`) | obj/null | optional (Feature `room_usage`) | alle | `null` → „Keine Nutzungsdaten“ | `roomusage.*` | Vorhanden (Schritt 4.4) |
| Überblick | KPI „Belegt“ | `get_overview` | `occupied` | bool | immer | alle | – | `kpi.occupied` | Vorhanden |
| Überblick | Area Card Name | `get_overview` | `name` | str | immer | alle | – | – | Vorhanden |
| Überblick | Presence-Text | `get_overview` | `presence.state` | enum | immer | alle | – | `presence.occupied`/`clear` | Vorhanden |
| Überblick | Helligkeit | `get_overview` | `brightness.state`, `illuminance` | enum, str | optional | alle | `null` → „Keine Daten“ | `brightness.*` | Vorhanden |
| Überblick | Licht-Zähler | `get_overview` | `lights.on`, `lights.total` | int | optional | alle | `total = 0` → Ausblenden | `lights.count` | Vorhanden |
| Überblick | Warnungen | `get_overview` | `warning_count` | int | immer | alle | – | `kpi.warnings` | Vorhanden |
| Überblick | Secondary States | `get_overview` | `active_states` | list[str] | immer | alle | leer → nichts | `state.*` | Vorhanden |
| Area-Detail | Presence-Quellen | `get_area` | `presence.sources` | list | immer | alle | – | `source.*` | Vorhanden (Befund B1 bei Entity-IDs) |
| Area-Detail | Helligkeit | `get_area` | `brightness_detail.dark_source` | obj | optional | alle | `null` | `brightness.*` | Vorhanden |
| Area-Detail | Licht-Gruppen | `get_area` | `light_groups[]` | list | optional | alle (Befund B1) | leer → ausblenden | `lightgroup.*` | Vorhanden |
| Area-Detail | Aggregate | `get_area` | `aggregates` | list | optional | alle | leer → ausblenden | `aggregate.*` | Vorhanden |
| Area-Detail | Environment | `get_area` | `environment` | obj | optional | alle | `null` → ausblenden | `env.*` | Vorhanden |
| Area-Detail | Sources | `get_area` | `sources[]` | list | immer | alle (Befund B1) | – | `source.*` | Vorhanden |
| Area-Detail | Controls | `get_area` | `controls[]` | list | immer | alle (Befund B1) | – | `control.*` | Vorhanden |
| Environment | Messwertkarte | `get_area` | `environment.*` | obj | optional | alle | `null` = „Keine Daten“ | `env.*` | Vorhanden; Felder noch zu prüfen |
| Cleaning | Fälligkeit | `get_overview` / `get_area` | `cleaning.cleaning_state`, `due`, `remaining_minutes_to_due` | str/bool/int | optional | alle | `null` → ausblenden | `cleaning.*` | Vorhanden |
| Room Usage | Nutzung | `get_overview` / `get_area` | `room_usage` (Felder im Code zu prüfen) | obj | optional | alle | `null` → ausblenden | `roomusage.*` | Vorhanden; Felder noch zu prüfen |
| Lichtsteuerung | Runtime | `get_light_runtime_status` | Entscheidung, Override, Präsenz, Verfügbarkeit | enum | optional | Admin | Fehler → lokale Meldung | `light.runtime.*` | Vorhanden |
| Klimasteuerung | Runtime | `get_climate_runtime_status` | Automatik, Bereichszustand, Entscheidung, `current_preset`, `configured_preset` | enum/str | optional | Admin | Fehler → lokale Meldung | `climate.runtime.*` | Vorhanden |
| Diagnose | Issues, Aggregation | `get_diagnostics` | Dashboard-Diagnose | obj | immer | Admin | – | `diag.*` | Vorhanden |
| Decision Trace | Timeline | `get_decision_trace` | §4.2 | obj | optional | Admin | leer → „Keine Einträge“ | `trace.*` | **Neu** |
| Einstellungen | Felder | `get_global_configuration` | Wetter-/Helligkeits-Entity | str | immer | Admin | veraltete ID bleibt sichtbar | `settings.*` | Vorhanden |
| Area-Editor | Formular | `get_area_configuration` / `update_area` | Konfigurationsfelder | obj | immer | Admin | Validierung serverseitig | `area.*` | Vorhanden |
| Live | Aktualisierung | `subscribe_updates` | Signal | – | immer | alle | Verbindung verloren | `status.*` | Vorhanden |

Keine neuen DTO-Felder außer `get_decision_trace` und der unten beschriebenen additiven Erweiterung des Überblicks (Schritt 4.3).

**Diagnose-Erweiterung (Schritt 5.4, 2026-11-20):** Jede Quelle in Bereichs- und Diagnose-DTOs trägt `status` (`available`, `unavailable`, `unknown`, `missing`). `get_diagnostics` liefert zusätzlich `unknown_source_count` und `data_complete` (false bei unbekannten Quellen oder fehlgeschlagener Bereichsdiagnose). Unbekannte Quellen sind Hinweise mit Schweregrad `info`, keine Warnungen. `warning_count` zählt nur Schweregrad `warning`. Bedeutungsänderung: `unavailable_source_count` zählt keine unbekannten Quellen mehr (vorher doppelt gezählt als Störung).

**Additive Erweiterung des Überblicks (Schritt 4.3, 2026-11-20):** Jede Bereichszusammenfassung in `get_overview` und in den Aktualisierungsereignissen enthält `floor_id` (Etagen-ID des Bereichs oder `null`) und `floor_name` (Name aus der Home-Assistant-Etagenregistrierung, `null` bei fehlender Etage oder unbekannter Etage). Meta-Bereiche enthalten zusätzlich `members`: die IDs der geladenen physischen Bereiche, die sie aggregieren. Nicht geladene Kinder werden ausgelassen, nicht erfunden. Nicht-Administratoren erhalten dieselben Felder; es handelt sich um Bereichs- und Etagenkennungen, keine Entitäts-IDs. Keine Speicher- oder Konfigurationsänderung. Bestehende Felder bleiben unverändert (rückwärtskompatibel). Die Gruppierung nach Etagen in §13.1 wird damit umgesetzt; ohne Etage ausgewiesene Bereiche stehen in einer eigenen Gruppe „Ohne Etage“, unbekannte Etagen als „Etage unbekannt“.

---

## 7. State Matrix

| Zustand | Anzeige | Quelle | Gilt für | Test |
|---|---|---|---|---|
| Initial Loading | Spinner (`ha-spinner`), Text „Lädt…“ | Client | alle | Render-Test |
| Refreshing | bestehende Daten bleiben, kleiner Hinweis | Client | alle | Scroll/Filter bleiben |
| Loaded | Inhalt | Backend | alle | Render-Test |
| Empty (keine Areas) | Hinweis „Keine Adaptive Areas konfiguriert“ | `overview` leer | alle | Render-Test |
| Empty (keine Lichtbereiche) | Hinweis auf Bereiche → Funktionen | Feature-Liste | Admin | Render-Test |
| Empty (keine Klimabereiche) | Hinweis wie oben | Feature-Liste | Admin | Render-Test |
| Unknown | „Unbekannt“ | Zustand `unknown` | alle | Render-Test; nie `0`/`false` |
| Unavailable | „Nicht verfügbar“ | Zustand `unavailable` | alle | Render-Test |
| Partial Data | Teilwerte mit „Keine Daten“ je Feld | `null` je Feld | alle | Render-Test |
| Feature disabled | ausgeblendet | `enabled_features` | alle | Render-Test |
| Feature aktiv, Daten fehlen | sichtbarer Hinweis „Keine Daten“ | Backend | alle | Render-Test |
| No issues | „Keine Auffälligkeiten“ | `warning_count == 0` | alle | Render-Test |
| Connection lost | Banner „Verbindung unterbrochen. Daten können veraltet sein.“ plus Zeitpunkt | Client | alle | Simulierter Verbindungsabbruch |
| Error (Befehl) | lokale Meldung, Retry-Button | Backend-Fehler | alle | Fehlerpfad-Test |
| Permission denied | Admin-Einträge ausgeblendet; falls direkt aufgerufen: „Nur für Administratoren“ | Berechtigung | Non-Admin | Negativtest |
| Admin Save läuft | Button deaktiviert, Spinner | Client | Admin | Render-Test |
| Admin Save fehlgeschlagen | Fehlermeldung, Eingaben bleiben | Backend | Admin | Test: Eingabe bleibt |
| Admin Save erfolgreich | Erfolgsmeldung erst nach Backend-Bestätigung | Backend | Admin | Test: keine Meldung vor Bestätigung |
| Dirty-State + Live-Update | Formular wird nicht überschrieben; Hinweis „Neue Daten verfügbar“ | Client | Admin | Test: Live-Update überschreibt Eingabe nicht |
| Löschen | Bestätigungsdialog | Client | Admin | Test: ohne Bestätigung kein Befehl |

---

## 8. Localization

### 8.1 Ziel

Eine Quelle: `custom_components/adaptive_areas/translations/*.json`. Das Panel nutzt keine zweite Quelle.

### 8.2 Native Weg

- Ursprünglicher Befehl: `frontend/get_translations` mit `language`, `category`, `integration`. **Überholt (2026-11-22):** Hassfest lehnt die Kategorie `dashboard` in `translations/*.json` ab. Die Texte stehen jetzt in `custom_components/adaptive_areas/dashboard_texts/{en,de}.json`, geladen über `adaptive_areas/get_dashboard_texts` (Antwort mit `resources`, flache Schlüssel `component.adaptive_areas.dashboard.*`, Englisch als Fallback, Fehler `dashboard_texts_unavailable`). Umgesetzt in `dashboard_texts.py`; Tests `tests/test_dashboard_texts.py`.
- Verifiziert in HA 2026.10.4 (`homeassistant/components/frontend/__init__.py`): Befehl vorhanden, keine Admin-Pflicht, liefert `resources`.
- **Offen (vor Umsetzung zu testen):**
  - Welche Kategorie die Schlüssel der Integration liefert (`component`?) und wie die Schlüssel verschachtelt sind.
  - Mindestversion: `hacs.json` nennt `homeassistant: 2026.8.0`. Ob der Befehl in 2026.8.0 existiert, ist nicht geprüft.
  - Verhalten bei Sprachwechsel und Fallback.
  - Caching: einmal je Sprache, bei Sprachwechsel neu.

### 8.3 Entscheidungsvorlage

| Option | Vorteil | Nachteil | Empfehlung |
|---|---|---|---|
| A: `frontend/get_translations` | Keine neue Schnittstelle, native Quelle | Mindestversion und Schlüsselmodell noch zu prüfen | **Empfohlen**, nach Tests |
| B: eigener Befehl `adaptive_areas/get_translations` liest `translations/*.json` serverseitig | Vollständige Kontrolle | Neue Schnittstelle, Pflege, Caching im Backend | Fallback, wenn A nicht passt |
| C: Build-Schritt erzeugt JS-Datei | Keine Laufzeitabhängigkeit | Build-Kette, doppelte Dateien | Nicht empfohlen |
| D: eigenes EN/DE-Objekt bleiben | Keine Änderung | Doppelte Quelle, AGENTS.md-Verstoß | Nicht empfohlen |

Entscheidung E7 (bedingt freigegeben): Option A nur nach Nachweis der Mindestversion 2026.8.0 und des Schlüsselmodells. Ohne Nachweis gilt Option B als Vorlage für eine neue Freigabe, nicht als Ausweichlösung.

### 8.4 Anforderungen

- Fallback: fehlt ein Schlüssel, Englisch; fehlt auch der, zeige den Schlüssel nicht, sondern „Text nicht verfügbar“ und logge im Test.
- Zahlen, Datum und Zeit: über `Intl` mit der Sprache aus `hass.language`.
- Singular und Plural: über getrennte Schlüssel (`*_one`, `*_other`), kein String-Konkatenieren.
- Keine fest codierten nutzersichtbaren Texte. Test: statische Suche nach Umlauten und ASCII-Wörtern in Template-Strings.
- Keine Entity- oder Enum-Werte im sichtbaren Text.

---

## 9. Rendering-Architektur

### 9.1 Ist (Code-Befund)

- Das Panel setzt `this.innerHTML` bei jedem Render. Das zerstört DOM-Knoten, Fokus, Scrollposition und ungespeicherte Eingaben.
- `escape(` wird 59-mal verwendet. Ob jede dynamische Stelle erfasst ist, ist nicht geprüft.

### 9.2 Prinzipien

- Vanilla JavaScript, keine neue Abhängigkeit, keine Build-Kette.
- Dynamische Inhalte über `textContent` oder `createElement`. `innerHTML` nur für statische Gerüste ohne Daten.
- Stabile Shell: einmal aufbauen, danach gezielt aktualisieren.
- Zustand in einem Objekt, Änderung über eine Funktion, die nur betroffene Knoten aktualisiert.
- Listen mit Schlüsseln (Area-ID) wiederverwenden, nicht neu erzeugen.

### 9.3 Migrationsschritte (inkrementell)

1. Regressionstests für bestehende Funktionen (Filter, Dirty-State, Navigation, Speichern, Scroll). Muss vor dem Umbau grün sein.
2. Shell und Navigation: einmaliger Aufbau, View-Wechsel per Sichtbarkeit.
3. State: ein Zustandsobjekt, Ereignisse aus `subscribe_updates` aktualisieren nur betroffene Area-Karten.
4. Komponenten: Area Card, KPI, Metric, Source-Liste als Funktionen, die DOM-Knoten erzeugen.
5. Gezielte Aktualisierung von Karten und KPI bei Live-Updates.
6. Migration der übrigen Ansichten.
7. Erneute Regressionstests und Browser-Prüfung.

### 9.4 Messung

Vor Schritt 5 wird die Rendering-Häufigkeit gemessen (Anzahl Renders je Update-Ereignis, mit Konsolen-Zähler im Harness). Ohne Messwert wird keine Optimierung behauptet.

### 9.5 Sicherheit

- Test: dynamische Strings mit `<img onerror=…>`, Anführungszeichen und Umlauten in Area-Namen, Entity-Namen und Trace-Gründen. Erwartung: als Text angezeigt, kein Markup ausgeführt.
- Keine Verlass auf die Anzahl von `escape(`-Aufrufen.

---

## 10. Theme Specification

- Farben: nur über HA-Theme-Variablen (`--primary-color`, `--secondary-text-color`, `--card-background-color`, `--divider-color`, `--error-color`, `--success-color`, `--warning-color`, `--info-color`, `--disabled-text-color`). Keine Hex-Werte im Panel.
- Semantik (Designreferenz, übersetzt auf Theme-Variablen):
  - Primary: `--primary-color` (Navigation, Auswahl)
  - Erfolg: `--success-color` (belegt/gesund, nur wenn Quelle bestätigt)
  - Neutral: `--disabled-text-color` (frei/inaktiv)
  - Warnung: `--warning-color`
  - Kritisch: `--error-color`
  - Sleep: Theme-Variable, falls im Theme vorhanden; sonst `--primary-color`. Keine fest codierte Violett-Farbe.
- Informationen niemals nur über Farbe: jeder Status hat Text und Symbol (MDI).
- Spacing: 4/8/12/16/24/32 px.
- Radius: `--ha-card-border-radius`, Standard 12 px.
- Schatten: keine oder minimal (HA-Standard).
- Dark Mode und Custom-Themes: nur über Variablen, keine eigene Dark-Palette.
- Typografie: HA-Schrift (`font-family: inherit`), tabellarische Ziffern (`font-variant-numeric: tabular-nums`) für Messwerte.
- Icons: `ha-icon` mit MDI-Namen, keine Icon-Bibliothek.
- Animationen: nur Fortschritt und Zustandswechsel; unter `prefers-reduced-motion: reduce` ohne Übergänge.
- Theme-Audit (Ist): ~8 Variablen-Verwendungen, keine Hex-Werte gefunden. Die Abstände und Schriftgrößen sind nicht geprüft.

---

## 11. Accessibility (WCAG 2.2 AA)

- Tastatur: alle Karten und Filter erreichbar, Enter/Space aktiviert. Area-Karte als `button` oder `a` mit Name.
- Fokus: sichtbarer Rahmen (`:focus-visible`), keine Entfernung ohne Ersatz.
- Name: jede Karte hat einen zugänglichen Namen mit Area-Name und Status („Wohnzimmer, belegt“).
- Semantik: Überschriften-Hierarchie h1 (Titel), h2 (Abschnitt), h3 (Karte). Listen als `ul`, Tabellen als `table` mit `th`.
- Kontrast: Text ≥ 4.5:1, nicht-Text ≥ 3:1. Prüfung mit Theme-Variablen im Browser-Test.
- Touch-Ziele: ≥ 44 × 44 px.
- Nicht nur Farbe: Status mit Text.
- Live-Bereiche: `aria-live="polite"` für Aktualisierungen und Speicher-Status, nicht für jede Kennzahl.
- Reduced Motion: siehe §10.
- Vergrößerte Schrift: Layout bleibt bei 200 % Zoom nutzbar (kein horizontaler Scroll außer Tabs).

---

## 12. Responsive Layout

| Breite | Overview | Area-Detail | Navigation |
|---|---|---|---|
| ≥ 1200 px | 3–4 Spalten Karten | zweispaltig (Gruppen links, Auszug rechts) | Tab-Leiste |
| 768–1199 px | 2 Spalten | einspaltig, Abschnitte untereinander | Tab-Leiste, scrollbar |
| < 768 px | 1 Spalte | einspaltig | Tab-Leiste, scrollbar, Touch ≥ 44 px |

Kein horizontales Scrollen außer der Tab-Leiste. Lange Namen: Zeilenumbruch, `overflow-wrap: anywhere`.

---

## 13. Wireframes (Struktur, keine Pixelvorgabe)

Notation: Layout-Skizzen, Light/Dark nur über Theme-Variablen.

**13.1 Overview, Desktop (Admin und Nicht-Admin, gleiche Struktur)**
```
Adaptive Areas                                     Überblick | Bereiche | Environment | ...
Monitoring · Stand 12:04 (aktualisiert)

[ Areas 12 ]  [ Belegt 4 ]  [ Hinweise 1 ]  [ Auffälligkeiten 2 ]

Filter: [Alle] [Belegt] [Frei] [Unbekannt] [Nicht verfügbar] [Auffälligkeiten]     Suche [______]

Erdgeschoss
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ Wohnzimmer  ●  │ │ Küche          │ │ Flur           │
│ Belegt         │ │ Frei           │ │ Keine Daten    │
│ 22,4 °C 48 % … │ │ 21,0 °C 52 %   │ │                │
│ Hell · Erweitert│ │                │ │                │
└────────────────┘ └────────────────┘ └────────────────┘
Obergeschoss
┌────────────────┐ ┌────────────────┐
│ Schlafzimmer ● │ │ Büro           │
...
```

**13.2 Overview, Tablet (768 px)**
```
[ Areas 12 ] [ Belegt 4 ]      [ Hinweise 1 ] [ Auffälligkeiten 2 ]
Filter (scrollbar) ──────────────────────────────
Erdgeschoss
┌──────────────────┐ ┌──────────────────┐
│ Wohnzimmer  ●    │ │ Küche            │
└──────────────────┘ └──────────────────┘
```

**13.3 Overview, Smartphone (390 px)**
```
Adaptive Areas
[Überblick][Bereiche][Environment]→
[ Areas 12 ] [ Belegt 4 ]
[ Hinweise 1 ] [ Auffälligkeiten 2 ]
Filter (scrollbar) →
Erdgeschoss
┌──────────────────────────┐
│ Wohnzimmer            ●  │
│ Belegt                   │
│ 22,4 °C · 48 % · 620 ppm │
│ Hell · Erweitert         │
└──────────────────────────┘
┌──────────────────────────┐
│ Küche                    │
...
```

**13.4 Area-Detail, Desktop**
```
← Bereiche / Wohnzimmer                                 Erdgeschoss
┌ Präsenz ───────────────────┐  ┌ Auszug Entscheidungen (Admin) ──┐
│ Belegt seit 12:01          │  │ 12:01 Belegt · Bewegung erkannt  │
│ Quellen: 3 von 3 verfügbar │  │ 11:42 Frei · Zeitgeber abgelaufen│
└────────────────────────────┘  │ [Alle Entscheidungen anzeigen]    │
┌ Sekundärzustände ──────────┐  └──────────────────────────────────┘
│ Hell · Erweitert           │  ┌ Umwelt ─────────────────────────┐
└────────────────────────────┘  │ 22,4 °C · 48 % · 620 ppm         │
┌ Licht (Admin) ─────────────┐  │ Keine Daten für Feuchte Außen    │
│ 3 von 5 Leuchten an        │  └──────────────────────────────────┘
│ [Zur Lichtsteuerung]       │
└────────────────────────────┘
┌ Reinigung ────────────────┐
│ Fällig in 2 h              │
└────────────────────────────┘
```

**13.5 Area-Detail, Smartphone**
```
← Wohnzimmer
Präsenz: Belegt seit 12:01
Quellen: 3 von 3 verfügbar
[Sekundärzustände] Hell · Erweitert
Umwelt: 22,4 °C · 48 % · 620 ppm
Licht (Admin): 3 von 5 an → [Lichtsteuerung]
Reinigung: Fällig in 2 h
Entscheidungen (Admin): 2 Einträge → [Alle]
```

**13.6 Environment (Monitoring)**
```
Umwelt                                      [Innen] [Außen]
┌ Temperatur ──────────────────────────────────────────────┐
│ Wohnzimmer  22,4 °C  ▓▓▓▓▓▓░░  Küche 21,0 °C  ▓▓▓▓░░░░  │
│ Außen (nur Referenz) 14,2 °C                              │
└──────────────────────────────────────────────────────────┘
┌ Luftfeuchte ─────────────────────────────────────────────┐
│ ...                                                       │
└──────────────────────────────────────────────────────────┘
Hinweis: Unbekannt = „Keine Daten“, nicht 0.
```
Messwerte und Balken aus vorhandenen Werten. Keine Bewertung im Frontend; Klassifizierung nur aus Backend-Feldern.

**13.7 Cleaning (Monitoring)**
```
Reinigung                                              Priorität
Überfällig         Küche          seit 2 h
Fällig heute       Büro           in 3 h
Nicht fällig       Flur           in 2 Tagen
Keine Daten        Gäste-WC       –
```

**13.8 Room Usage (Monitoring)**
```
Raumnutzung
Wohnzimmer     Belegt  seit 12:01    Heute: 3 h 12 min
Küche          Frei                   Heute: 1 h 40 min
```
Felder für Dauer und Zähler werden vor Umsetzung im Code bestätigt (§6).

**13.9 Lighting (Admin)**
```
Lichtsteuerung · Wohnzimmer
┌ Automatik ───────────────────────────────────────────┐
│ Einschalten bei höchstens [ 50 ] lx                  │
│ Ausschalten bei mindestens [ 120 ] lx                │
│ Ausschalten nach Abwesenheit [ 300 ] Sekunden        │
│ Zwischen beiden Werten bleibt der aktuelle Zustand.  │
└──────────────────────────────────────────────────────┘
┌ Aktueller Status (nur Anzeige) ──────────────────────┐
│ Entscheidung: Zustand beibehalten                    │
│ Manueller Eingriff: keiner                           │
│ Anwesenheit: Belegt                                  │
└──────────────────────────────────────────────────────┘
┌ Lichtgruppen ────────────────────────────────────────┐
│ Deckenleuchten · Bei Belegung · 2 von 3 an           │
│ Schlaflichter  · Im Schlafzustand · 0 von 2 an       │
│ Akzent         · Im Akzentzustand · 0 von 1 an       │
│ Arbeitslicht   · Bei Belegung · 1 von 2 an           │
└──────────────────────────────────────────────────────┘
```

**13.10 Climate (Admin)**
```
Klimasteuerung · Wohnzimmer
Thermostat        [Friendly Name ▾] (Fallback: Entity-ID)
Preset Frei       [ ▾ ]
Preset Belegt     [ ▾ ]
Preset Schlaf     [ ▾ ]
Preset Erweitert  [ ▾ ]
Belegungsschwelle [ 5 ] Minuten
[Speichern] [Abbrechen]

┌ Aktueller Status (nur Anzeige) ─────────────────────┐
│ Automatik: Aktiv · Verfügbar                        │
│ Bereichszustand: Belegt                             │
│ Entscheidung: Belegung                              │
│ Aktuelles Preset: Komfort · Gewähltes Preset: Komfort│
└──────────────────────────────────────────────────────┘
```

**13.11 Decision Trace (Admin)**
```
Entscheidungen                     Area [Alle ▾]  Feature [Alle ▾]  Ergebnis [Alle ▾]
12:01  Wohnzimmer · Belegung
       Feature: Lichtgruppen · Trigger: Zustandsänderung
       Entscheidung: Einschalten · Ergebnis: ausgeführt
       Grund: Bereichszustand erfüllt, Aktion ausgeführt

11:42  Küche · Frei
       Feature: Präsenz · Trigger: Neuberechnung
       Ergebnis: beobachtet
       Grund: Zeitgeber abgelaufen

11:20  Flur · Belegung
       Feature: Lichtgruppen · Ergebnis: übersprungen
       Keine Begründung aufgezeichnet.
[ Mehr laden ]   (bis 20 Einträge je Area)
```
Beispielsätze sind Designreferenz. Die tatsächlichen Texte entstehen aus den Allowlisten (§4, §5).

**13.12 Diagnostics (Admin)**
```
Diagnose
┌ Integration ─────────────────────────────────────────┐
│ Version X.Y.Z (aus Manifest, nicht fest codiert)     │
│ Konfigurierte Areas: 12                              │
│ Laufzeit: Verfügbar                                  │
└──────────────────────────────────────────────────────┘
┌ Auffälligkeiten ─────────────────────────────────────┐
│ Warnung (Sicherheit): 1                              │
│ Technischer Fehler: 0                                │
│ Fehlende Daten: 2 Quellen nicht verfügbar            │
│ Normalbetrieb: 9 Areas                               │
└──────────────────────────────────────────────────────┘
[Native Integrationsdiagnose öffnen]   (Verweis, keine Duplizierung)
```

**13.13 Settings (Admin)**
```
Einstellungen
Wetter-Entity       [ Friendly Name ▾ ]   (veraltet: bleibt sichtbar, mit Hinweis)
Helligkeitssensor   [ Friendly Name ▾ ]
[Speichern]  Änderungen nicht gespeichert: Hinweis bei Abweichung
```
Speichern erhält andere Global Options (Phase-E-Regel).

**13.14 Area Editor (Admin)**
```
Bereich bearbeiten: Wohnzimmer
┌ Allgemein ──────────────────────────┐
│ Name [ Wohnzimmer ]                  │
│ Typ  Innen ▾                         │
│ Etage [ Erdgeschoss ▾ ]              │
└──────────────────────────────────────┘
┌ Anwesenheitsverfolgung ─────────────┐
│ Quellen (Auswahl, Friendly Names)    │
│ Timeout [ 300 ] Sekunden             │
└──────────────────────────────────────┘
┌ Erweiterte Statusverfolgung ────────┐
│ ...                                  │
└──────────────────────────────────────┘
┌ Funktionen (nur ein/aus) ───────────┐
│ [x] Lichtautomatik   [ ] Klima ...   │
└──────────────────────────────────────┘
[Speichern] [Abbrechen]   ·   Löschen (getrennt, mit Bestätigung)
```

Hinweis: Die Felder des Area-Editors werden vor der Umsetzung gegen `get_area_configuration` und Phase-E-Regeln geprüft.

**Dark Mode:** identische Struktur; nur Theme-Variablen ändern sich.

---

## 14. Implementierungsplan

Reihenfolge nach Abhängigkeiten. Komplexität relativ (S/M/L). Regressionsrisiko (N/M/H).

| # | Paket | Objective | Scope | Dependencies | Affected Files (Vorschlag) | Acceptance Criteria | Required Tests | Risks | Complexity | Regression |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Baseline | Ausgangsstand festhalten | Tests, Lint (nicht ändernd), JSON | – | keine | Ergebnisse protokolliert | – | pre-commit kann Dateien ändern → nur mit `--files` ohne Schreiben oder in Kopie | S | N |
| 2 | Spezifikation | Konsolidierte Doku | `docs/specifications/dashboard.md`, Verweise in ROADMAP, CURRENT_STATE, DECISIONS, README-Hinweis | 1, Freigabe | 4 Dateien | Keine `.agents`-Referenz; Traceability vollständig | Link-/Pfadprüfung | Doppelpflege | S | N |
| 3 | Permission-Tests | Negativ- und Positivtests je Befehl | `tests/test_dashboard.py` | 1 | Tests | Alle 12 Befehle geprüft | Pytest | Test-Harness-Aufwand | S | N |
| 4 | Befund B1 (Non-Admin-Aufbereitung nach §3.1) | Approved. Prüfauftrag zu `controls`/`sources` zuerst. | Admin-Antworten unverändert testen | Planned | Entfall nur für `controls`/Entity-Felder bei Nicht-Admin | M | M |
| 5 | Theme-Foundation | Hex-frei, Variablen | Panel-CSS | 2 | Panel-JS | Keine Hex-Werte; Light/Dark prüfen | Browser-Prüfung | Visuelle Regression | M | M |
| 6 | Übersetzung | `adaptive_areas/get_dashboard_texts` (2026-11-22) | Panel, `dashboard_texts/*.json` | 2, Nachweis | Panel-JS | Keine EN/DE-Duplizierung; Test je Sprache | Schlüssel-Test (alle Schlüssel in en.json, de.json) | Mindestversion | M | M |
| 7 | Render-Regressionstests | Bestehende Funktionen sichern | Tests | 3 | Tests | Filter, Dirty-State, Speichern, Navigation | Browser-Harness + Pytest | Harness-Umfang | M | N |
| 8 | Render-Umbau: Shell | Stabile Shell | Panel-JS | 5, 6, 7 | Panel-JS | Keine Neuaufbau-Renders bei Live-Update | Render-Zähler | Großer Diff | M | H |
| 9 | Render-Umbau: State und Karten | Gezielte Updates | Panel-JS | 8 | Panel-JS | Messwert verbessert; Scroll/Fokus/Filter erhalten | Render-Zähler, Browser | Fehler bei Live-Updates | M | H |
| 10 | Responsive Shell | Layout Phone/Tablet/Desktop | Panel-CSS | 8 | Panel-JS | Keine horizontale Scroll-Leiste außer Tabs | Browser-Breakpoints | – | M | L |
| 11 | Overview und Area-Karten | KPI, Filter, Suche, Gruppierung nach Floors | Panel-JS | 9, 10 | Panel-JS | Meta-Areas nicht doppelt gezählt | Frontend-Tests + Pytest (Zählung) | Zählregel im Frontend | M | M |
| 12 | Area-Detail | Gruppen laut §13.4 | Panel-JS | 11 | Panel-JS | Keine leeren Karten | Browser | – | M | M |
| 13 | Environment, Cleaning, Room Usage | Ansichten aus DTOs | Panel-JS | 12 | Panel-JS | Nur vorhandene Felder | Browser | Felder Room Usage prüfen | M | L |
| 14 | Lighting, Climate | Funktionserhalt | Panel-JS | 9 | Panel-JS | Alle Phase-E-Regeln erfüllt | Phase-E-Regressionstests (Ist) | hoch | M | H |
| 15 | Administration | Dirty-State, Löschen mit Bestätigung | Panel-JS | 9 | Panel-JS | Eingaben bleiben; Bestätigung | Browser + Pytest | hoch | M | H |
| 16 | Decision Trace Backend | `get_decision_trace` | `websocket.py`, `dashboard.py`, `helpers/decision_trace.py` | 3 | 3 Dateien | §4 vollständig | Pytest: Allowlist, Limits, Admin, unbekannte Werte | Befund Allowlist | M | L |
| 17 | Reason-Codes | R1, R2, R6, R7 | `binary_sensor/presence.py` | 16 | 1 Datei | `last_reason` unverändert; Trace enthält Quellgrund | Pytest: Trace vs. Attribut, Fehlerfreiheit ohne Trace | Attribut-Drift | M | M |
| 18 | Decision Trace Frontend | Timeline, Area-Auszug | Panel-JS | 16, 9 | Panel-JS | §4.5 | Browser + Pytest | – | M | L |
| 19 | Diagnose-Ansicht | Verweis, Kategorien | Panel-JS | 9 | Panel-JS | Keine Duplizierung nativer Diagnose | Browser | – | S | L |
| 20 | Zustandsbehandlung | Connection lost, Partial, Errors | Panel-JS | 9 | Panel-JS | §7 | Simulierter Abbruch | – | S | L |
| 21 | Accessibility | Tastatur, Namen, Fokus | Panel-JS, CSS | 11–15 | Panel | §11 | Browser-Tastatur | – | M | L |
| 22 | Performance | Messung, dann Optimierung | Panel-JS | 9 | Panel-JS | Messung dokumentiert | Render-Zähler | – | S | L |
| 23 | Browser-Validierung | Sichtprüfung | – | 20 | Screenshots | Light/Dark, Breakpoints, Admin/Non-Admin | Browser-Harness | Keine echte HA-Instanz verfügbar | M | – |
| 24 | Doku und Changelog | README, Nutzerdoku, CHANGELOG | `docs/source/`, `README.md`, `CHANGELOG.md` | alle | Doku | Konsistenz | Link-Prüfung | – | S | N |

Priorität:
- **Must Have:** 1–9, 11–15, 16–17, 19–21, 23–24. (Decision Trace, Environment, Cleaning, Room Usage, Diagnose, Administration sind Must; siehe Vorgabe.)
- **Should Have:** Area-Suche (Teil von 11), erweiterte Filter, Trace-Kontext (Teil von 18), Bereichsvergleich.
- **Nice to Have:** Trends (nur mit bestehenden Daten; keine neue Persistenz).

Hinweis zur Reihenfolge: Die Must-Have-Funktionen werden in Blöcken umgesetzt, nicht gleichzeitig. Ein Block endet mit grünen Tests und Browser-Prüfung.

---

## 15. Teststrategie

### 15.1 Baseline (Stand heute)

- `.tox/ha-stable` (HA 2026.10.4): **563 passed** (Verified, Stand 3b1bd6a). `docs/TESTING.md` wird auf diesen Stand korrigiert.
- Dashboard-Tests: 39 passed.
- JSON-Validierung (`scripts/validate_json.py`): keine Fehlerausgabe.
- Nicht ausgeführt: `scripts/lint` und `pre-commit` (Begründung: Hooks können Dateien schreiben; Freigabe nötig oder Kopie), Browser-Harness (nicht in dieser Phase), HA 2026.8.x-Suite.

### 15.2 Pflichtfälle (aus Briefing)

| Fall | Test-Art | Status |
|---|---|---|
| Leere Installation | Pytest + Browser | offen |
| Einzelne Area | Pytest + Browser | offen |
| Viele Areas | Browser (Performance) | offen |
| Occupied und Clear | Pytest | teilweise |
| Unknown und Unavailable | Pytest + Browser | offen |
| Floors und Meta-Areas | Pytest (Zählung) | offen |
| Fehlende Sensorwerte | Pytest | teilweise |
| Deaktivierte Features | Pytest + Browser | offen |
| Environment-Warnungen | Pytest | teilweise |
| Health Issues | Pytest | teilweise |
| Cleaning Due | Pytest | teilweise |
| Decision-Trace-Ereignisse | Pytest | offen |
| Admin-Rechte | Pytest (pos./neg.) | offen (Paket 3) |
| WebSocket-Fehler | Pytest | offen |
| Verbindungsverlust | Browser | offen |
| Dynamische Aktualisierung | Browser | offen |
| Responsive | Browser | offen |
| Light/Dark/Custom-Theme | Browser | offen |
| Tastatur | Browser | offen |
| Übersetzungen | Pytest (Schlüssel) | offen |
| Lange Namen | Browser | offen |
| XSS in dynamischen Feldern | Browser + Unit | offen |

---

## 16. Entscheidungen (Approval Gate 1, freigegeben)

| # | Thema | Entscheidung | Status |
|---|---|---|---|
| E1 | Spezifikationsort | Diese Datei unter `docs/specifications/`. Die Langfassung bleibt lokal in `.agents/`, ohne normative Abhängigkeit. | Approved, Implemented (Dokumentation) |
| E2 | Non-Admin-Daten (B1) | Rollenabhängige serverseitige Aufbereitung nach §3.1. Keine pauschale Entfernung ganzer Bereiche. | Approved, Planned |
| E3 | Trace-Sichtbarkeit | Admin-only. | Approved, Planned |
| E4 | Globale Trace-Übersicht | Nicht in v1. Architektur erlaubt spätere Erweiterung. | Approved (zurückgestellt) |
| E5 | Reason-Codes | Trace-only. `last_reason` unverändert. Vorhandene Codes wiederverwenden, neue nur bei eindeutig bekanntem Grund. | Approved, Planned |
| E6 | Trace-Serialisierung | Feld- und Wert-Allowlist, neutraler Fallback. Unterscheidung: Unknown, Not recorded, Unsupported value, Other. Rohwerte nie über Fallback offenlegen. | Approved, Planned |
| E7 | Übersetzung | `frontend/get_translations` bedingt freigegeben. Nachweis der Mindestversion 2026.8.0 vor Umsetzung. Keine Anhebung der Mindestversion. | Approved (bedingt), In Progress (Nachweis offen) |
| E8 | Rendering | Gezielte DOM-Updates als Ziel. Umsetzung erst nach Approval Gate 2 und Regressionstests. Kein Rewrite. | Approved (konzeptionell) |
| E9 | Visueller Prototyp | Isoliert in `prototypes/dashboard/` (außerhalb von `custom_components/`), nur Mock-Daten, keine Abhängigkeiten, keine externen Ressourcen. | Delivered for review (Verified: Headless-Chrome-Screenshots, siehe `prototypes/dashboard/README.md`); Approval Gate 2 ausstehend |
| E10 | Dokumentation | `ROADMAP.md`, `CURRENT_STATE.md`, `DECISIONS.md`, `TESTING.md` verlinken oder korrigieren diese Spezifikation. | Approved, In Progress |

Nicht freigegeben (bis Approval Gate 2 bzw. gesonderter Freigabe): produktive Frontend-Änderungen, produktive Backend-Änderungen, Änderungen an bestehenden WebSocket-Befehlen außer §3.1, neue produktive Abhängigkeiten, Commits, Pushes, Releases, Versionsänderungen.


## 17. Risiken

- Render-Umbau: hohes Regressionsrisiko. Schutz: Tests vor dem Umbau, inkrementell.
- Übersetzungsbefehl: Mindestversion (`hacs.json` 2026.8.0) nicht geprüft.
- Trace: Mehrquellen-Darstellung nur, wenn alle aktiven Quellen bekannt sind (Test).
- `last_reason`-Drift, falls Trace und Attribut vermischt werden.
- Befund B1: Datenschutz für Nicht-Admins. Entscheidung approved; Umsetzung Planned (Paket 4).
- Keine echte HA-Instanz für Sichtprüfung verfügbar.
- Dokumentation (`TESTING.md`) nennt veraltete Testzahl.

---

## 18. Compatibility

- Keine Änderung an Config Entries, Entity-IDs, Unique IDs oder gespeicherten Schemas.
- Keine Migration.
- `last_reason`-Werte bleiben unverändert (Entscheidung E5 in §16).
- Bestehende WebSocket-Befehle bleiben in Name, Parametern und Grundstruktur erhalten. Änderungen für Nicht-Admins gemäß §3.1 sind freigegeben; sie sind in `CURRENT_STATE.md` und im Changelog zu dokumentieren.
