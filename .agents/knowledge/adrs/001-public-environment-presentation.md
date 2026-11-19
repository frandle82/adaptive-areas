# ADR 001 – Öffentliche Environment-Präsentation

- **Status:** Angenommen
- **Kontext:** Die Environment-Engine berechnet strukturierte Handlungsempfehlungen, während die Home-Assistant-Entity eine kompakte Nutzeransicht benötigt.
- **Entscheidung:** Die öffentliche Environment-Entity veröffentlicht nur qualitative Klimaattribute, `notices` und verwendete Sensoren. `recommendation` und `operation` sind keine öffentlichen Attribute. `recommended_action`, `secondary_actions` und `recommendation_reason_codes` bleiben intern für Diagnostics, Automationen und die Notice-Erzeugung erhalten.
- **Change-Key:** Der Engine-Publish-Key umfasst alle Daten, die die sichtbare Darstellung beeinflussen, insbesondere Reason-Codes, Mitigation-Codes, Coverage, dominanten Pollutant, Recommendation-Codes und verwendete Sensoren. Listen und Dictionaries werden stabil normalisiert.
- **Notice-Regeln:** Notices werden dedupliziert, priorisiert und auf drei Einträge begrenzt. Coverage-Hinweise erscheinen zuletzt; die fertige Reihenfolge wird nicht erneut alphabetisch sortiert.
- **Konsequenzen:** Änderungen an Außenluft-Mitigation, Coverage oder dominantem Pollutant lösen auch dann ein Entity-Update aus, wenn `air_quality` unverändert bleibt. Die interne Recommendation-Engine bleibt rückwärtskompatibel.
