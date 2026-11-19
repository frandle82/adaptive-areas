# Projektregeln – Adaptive Areas

* **Integration:** Adaptive Areas ist eine Home-Assistant-Custom-Integration für HACS.
* **Domain:** `adaptive_areas` ist die stabile Domain.
* **Quelle der Wahrheit:** Die Implementierung (`custom_components/adaptive_areas/`) und Tests (`tests/`) sind die primäre Quelle der Wahrheit.
* **Versionierung:** Aktuelle Versionsinformationen immer direkt aus `custom_components/adaptive_areas/manifest.json` bzw. `hacs.json` lesen.
* **Releases & Changelog:** Bei Erstellung eines Pre-Releases oder Releases muss zwingend ein Changelog angegeben bzw. erstellt werden.
* **Rolle des Agenten:** Der Agent (Codex/Antigravity) soll das Projekt aktiv unterstützen, Vorschläge machen, Refactorings durchführen und eigenständig erforderlichen Code, Tests und Dokumentationen schreiben.
* **Kommunikation:** Die Kommunikation mit Andreas erfolgt auf Deutsch. Quellcode, Bezeichner, Kommentare und technische Dokumentation folgen der Sprache im Repository (Englisch).
* **Lokaler Wissensabruf (.agents):** Alle projektspezifischen Informationen, Notizen, Spezifikationen und Architekturentscheidungen (ADRs) werden direkt im `.agents`-Ordner (`.agents/knowledge/`) hinterlegt und gepflegt. Externe MCP-Tools werden nicht verwendet. Vor Beginn von Konzeption, Feature-Entwicklung, Architekturüberlegungen oder Anforderungsanalysen immer die Dokumente in `.agents` prüfen und einbeziehen (Skill `knowledge`).

## Verbindliche Arbeitsphasen & Skill-Nutzung

Jede signifikante Änderung durchläuft strukturierte Phasen unter Einsatz der Projekt-Skills:

1. **Anforderungsanalyse (Skill: `grill-me`, `knowledge`):**
   * Bevor Code geschrieben wird, unklare Anforderungen, Edge Cases, Architekturfragen und Regressionsrisiken intensiv hinterfragen und mit Andreas abstimmen.
   * Im `.agents`-Ordner (`.agents/knowledge/`) hinterlegte Notizen, Spezifikationen und Konzepte prüfen und in die Analyse einbinden.
   * Keine voreiligen Code-Generierungen auf Basis vager Prompts.

2. **Entwicklung & Domain-Design (Fach-Skills):**
   * Strikte Einhaltung der Home-Assistant-Architektur (`home-assistant`), Berechnungsalgorithmen (`adaptive-features`), UI-Setup (`config-flow`), Schemamigrationen (`migrations`) und Lokalisierung (`translations`).

3. **Verifikation & Test (Skills: `testing`, `playwright-interactive`):**
   * Jede Verhaltensänderung mit Pytest abdecken. Vor Abschluss mindestens gezielte Modultests und bei größeren Änderungen die stabile HA-Testsuite (`scripts/test stable`) ausführen.
   * Bei Änderungen an Benutzeroberflächen (Config/Options Flow, Lovelace Cards, Dialoge) interaktive Browser-Verifizierung (`playwright-interactive`) nutzen.

4. **Qualitätssicherung & Code Review (Skill: `code-reviewer`):**
   * Vor Abschluss und vor jedem Commit/PR-Vorschlag den vollständigen Diff (`git diff`) auf HA-Standards, Async Safety, Resource Leaks, Performance und Typisierung prüfen.
   * `scripts/lint` ausführen.

5. **CI-Fehlerbehebung (Skill: `gh-fix-ci`):**
   * Bei fehlgeschlagenen GitHub Actions Runs Logs via `gh` analysieren, Fehler lokal isolieren und reproduzieren, gezielten Fix erstellen.

6. **Workflow-Standardisierung (Skill: `skill-creator`):**
   * Wiederkehrende Arbeitsabläufe oder neu etablierte Best Practices als wiederverwendbare `SKILL.md` festhalten.
