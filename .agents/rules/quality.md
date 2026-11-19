# Qualitäts- & Testregeln – Adaptive Areas

* **Ursachenanalyse & Anforderungskonsolidierung:** Vor jeder Codeänderung das betroffene Verhalten und die Ursache gründlich analysieren; bei Unklarheiten oder Edge Cases zuerst gezielte Fragen stellen (Skill `grill-me`) und relevante Notizen und Spezifikationen aus dem `.agents`-Ordner abrufen (Skill `knowledge`). Keine spekulativen Änderungen.
* **Fokussierte Änderungen:** Kleine, gezielte und nachvollziehbare Änderungen bevorzugen.
* **Rückwärtskompatibilität:** Vorhandene Konfigurationen, Entity IDs, Unique IDs und gespeicherte Datenstrukturen nicht ohne Breaking-Change-Auftrag und Migrationspfad (`migrations`) ändern.
* **Home-Assistant-Standards:** Bei Erweiterung/Refactoring strikt modernste HA-Entwicklungsstandards einhalten (`_attr_has_entity_name = True`, `translation_key`, `EntityDescription`, saubere Async-Resource-Safety, Issue Registry).
* **Testausführung:** Betroffene Tests vor Abschluss der Aufgabe ausführen (`pytest -q tests/test_<bereich>.py` bzw. `.tox/ha-stable/bin/pytest`).
* **Frontend- & Flow-Validierung:** Bei Änderungen an UI, Formularen oder Config/Options Flow visuelle Funktionsfähigkeit sicherstellen (Skill `playwright-interactive`).
* **Obligatorisches Review:** Vor Übergabe an Andreas einen gründlichen Diff-Review durchführen (Skill `code-reviewer`) und `scripts/lint` ausführen.
* **CI-Hygiene:** Bei CI-Fehlschlägen Logs gezielt untersuchen und lokal mit tox reproduzieren (Skill `gh-fix-ci`).
* **Transparente Berichterstattung:** Nicht ausgeführte Prüfungen ausdrücklich im Abschlussbericht nennen.
* **Ehrlichkeit:** Niemals behaupten, ein Test sei erfolgreich gewesen, wenn er nicht tatsächlich ausgeführt wurde.
