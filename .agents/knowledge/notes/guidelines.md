# Richtlinien & Randfälle – Adaptive Areas

## Home Assistant Konventionen
- **Entity Naming:** Stets `_attr_has_entity_name = True` und `translation_key` verwenden. Niemals feste englische oder deutsche Strings hartcodieren.
- **Lokalisierung:** Übersetzungsdateien unter `custom_components/adaptive_areas/translations/` (`en.json`, `de.json`) synchron halten.
- **Async Safety:** Niemals blockierende I/O in der Event-Loop. Alle Callbacks, Listener und Dispatch-Verbindungen beim Unload lückenlos abmelden.

## Resilienz & Randfälle
- Sensoren können `None`, `STATE_UNAVAILABLE` oder `STATE_UNKNOWN` liefern. Berechnungen müssen defensiv damit umgehen und dürfen keine Exceptions werfen.
- Bei Bereichsumbenennungen oder Entitätslöschungen in Home Assistant dürfen keine Geisterzustände entstehen.
