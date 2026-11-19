# Adaptive Areas – Lokale Wissensbasis (.agents/knowledge)

Zentrale Wissens- und Kontextablage für KI-Coding-Agenten im Projekt `adaptive-areas`.

Dieses Verzeichnis dient als zentrale Wissens- und Kontextablage. Externe Notizsysteme und MCP-Abfragen werden nicht verwendet. Sämtliche architektonischen Entscheidungen, Systemspezifikationen, Konzepte und Randfälle werden ausschließlich hier gepflegt und abgerufen.

## Verzeichnisstruktur

```text
.agents/knowledge/
├── README.md                  # Dieser Überblick & Verzeichnisindex
├── architecture/              # Systemarchitektur, Datenfluss, Lifecycle & Entities
│   └── overview.md            # Grundarchitektur, Domain-Modell & Komponenten
├── specs/                     # Feature-Spezifikationen, Optionen & Schwellenwerte
│   └── features.md            # Beleuchtung, Präsenz, Wasp-in-a-Box, Aggregate etc.
├── adrs/                      # Architectural Decision Records (ADRs)
└── notes/                     # Technische Notizen, Randfälle & HA-Eigenheiten
    └── guidelines.md          # Best Practices & Implementierungsrichtlinien
```

## Arbeitsweise für Agenten

1. **Lokaler Wissensabruf:** Vor Feature-Entwicklung, Refactorings oder Anforderungsanalysen (`grill-me`) zuerst die entsprechenden Dateien in `architecture/`, `specs/`, `adrs/` oder `notes/` einsehen.
2. **Keine externen MCP-Aufrufe:** Es werden keine MCP-Tools für Notizen oder Wissensdatenbanken angesprochen.
3. **Wissenspflege:** Werden im Rahmen von Aufgaben neue Architekturentscheidungen getroffen oder Spezifikationen mit Andreas abgestimmt, werden diese direkt in den entsprechenden Dateien unter `.agents/knowledge/` aktualisiert oder als neues ADR unter `adrs/` festgehalten.
