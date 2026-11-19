# Architekturüberblick – Adaptive Areas

## Domäne & Rolle
- **Domain:** `adaptive_areas`
- **Typ:** Home Assistant Custom Integration (HACS)
- **Zweck:** Intelligente Raum- und Bereichsautomatisierung (Präsenzerkennung, adaptive Beleuchtung, Klima, Lüftung, Medien, Sensor-Aggregate, Meta-Areas).

## Kernkomponenten & Struktur
1. **Config Flow (`config_flow.py`):**
   - Mehrstufige Menüstruktur für Bereichskonfiguration (`general`, `presence`, `lighting`, `climate`, `fan`, `cover`, `media_player`, `thresholds`, `room_usage`).
   - Jeder Bereich (Area) wird als separater Config Entry instanziiert.

2. **Koordination & Lifecycle (`__init__.py`):**
   - Async Setup der Plattformen über Config Entries.
   - Event-Listener für Entitätszustandsänderungen und Area-Registry-Updates.
   - Sicheres Entladen (`async_unload_entry`) aller Listener, Timer und Entitäten.

3. **Plattform-Entitäten (`base/`, `sensor/`, `binary_sensor/`, `switch/`):**
   - Basisklassen sichern HA-Konformität (`_attr_has_entity_name = True`, `translation_key`).
   - Aggregation und Berechnung in `base/adaptive.py` und spezialisierten Helper-Modulen.

4. **Meta-Areas:**
   - Zusammenfassung mehrerer physischer Bereiche (z. B. Etagen, Gesamtbereiche) mit hierarchischer Präsenz- und Sensoraggregation.
