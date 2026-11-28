# Handover – Dashboard redesign (Phase 5)

Status: Schritt 3 **technisch abgenommen** (unabhängige Prüfung des Prüfarchivs v3, 2026-11-20: ZIP und Manifest bestätigt, 124/124 Browser-Prüfungen unter Chromium, Harness-Korrektur bestätigt, Bewertung 9,0/10; die 584 Python-Tests wurden dort mangels Home Assistant nicht erneut ausgeführt). Schritt 4 (Monitoring) abgeschlossen; Schritt 5 (Analyse) abgeschlossen; Schritt 6 im Implementierungsstand abgeschlossen; Review-Korrekturen V01–V03 bearbeitet, Fortsetzung siehe „Fortsetzungspunkt“.

## Fortsetzungspunkt (Phase J.3, deterministischer Lifecycle, 2026-11-28)

- Branch `fix/light-manual-override-lifecycle`, nur lokale Commits; kein Push, kein PR, keine Version.
- RC.4 hat die HAOS-Abnahme nicht bestanden; die exakte Template-Leuchte funktioniert im Test schon unter RC.4; die HAOS-Ursache ist nicht bewiesen.
- Umgesetzt: Übersteuerung nur noch Laufzeitzustand (kein Restore bei Neustart oder Reload, Reload beendet sie bewusst); Initialentscheidung erst bei vorhandenen Eingaben, einmal pro Setup, ohne Wiederholung; Meta-Präsenz beendet ausstehende Auswertung und Timer beim Unload.
- Tests: `tests/test_light_lifecycle.py` (L01–L36), `tests/test_light_template_helper.py`.
- PR-Entwurf, RC.5-Release-Notes und HAOS-Abnahmeplan: siehe Abschlussbericht Phase J.3 (nicht versioniert); vor RC.5 echte GitHub-CI abwarten.

## Fortsetzungspunkt (Phase J.2, exakte Template-Leuchte, 2026-11-27)

- Testleuchte auf HAOS ist ein Template-Helfer auf `input_boolean.licht`. Nachgebaut mit nativen Integrationen (`tests/test_light_template_helper.py`, ConfigEntry über den echten Config Flow und YAML). RC.4 schaltet damit in allen Szenarien korrekt; der HAOS-Fehler ist mit dieser Kette nicht reproduzierbar.
- Behoben: Licht-Listener liefen in Executor-Threads (keine Callbacks) – jetzt im Event-Loop. Trace: Befehl an nicht verfügbare Gruppe heißt `group_unavailable` statt „ausgeführt“. Ursprungsklassen umbenannt (`origin_user_account`, `origin_parent_context`, `origin_unattributed`). Panel zeigt je Lichtgruppe Zustand, Automatik, Übersteuerung und letzte Entscheidung.
- Wahrscheinlichster HAOS-Pfad (nicht bewiesen): eine echte frühere Bedienung von Helfer oder Lampe bei belegtem Bereich setzt die Übersteuerung; auf einem echten System bleibt sie über jeden Neustart und jedes Neuladen (z. B. Speichern eines Bereichs, Gerätezuordnung) erhalten, bis CLEAR eintritt. Mit erweiterter Anwesenheit kann das lange dauern.
- Offene Entscheidungen: Lebensdauer gespeicherter Übersteuerung; verlorenes EIN vor dem HA-Start (siehe DECISIONS.md).
- Benötigte HAOS-Daten mit dem Branch-Stand: Ereignisprotokoll des Arbeitszimmers (Eintrag „Manuelle Übersteuerung begonnen“ mit Auslöser und Ursprung, oder „wiederhergestellt“), Gruppenzeilen der Lichtdiagnose, Logbuch von `input_boolean.licht` und `light.test_leuchte` zum Beginn, Zeitpunkte von Neustarts/Neuladen.
- Graphify nicht aktualisiert (Graph auf `020d90b`).

## Fortsetzungspunkt (Phase J, HAOS-Regression RC.4, 2026-11-27)

- RC.4 ist veröffentlicht (`7f9593f`). Die HAOS-Abnahme ist fehlgeschlagen: Arbeitszimmer schaltet bei DARK nicht ein, Dashboard meldet „Manuell gesetzt (native Lichtgruppe)“ ohne manuelle Bedienung. Der ursprüngliche Lichtfehler ist nicht nachweislich behoben; 1.7.0 bleibt gesperrt.
- Branch `fix/light-manual-override-lifecycle` (von `7f9593f`), nur lokale Commits. Kein Push, kein PR, keine Version, kein Tag.
- Behoben (nachgewiesen): Trace-Begründungen der Lichtentscheidungen gingen in der DTO-Allowlist verloren („Keine Begründung aufgezeichnet“). Neu: Beginn, Ende und Wiederherstellung einer Übersteuerung stehen im Trace, mit Ursprungsklasse (Benutzer / Automation / nicht zuordenbar).
- Nicht nachgewiesen: die Ursache der HAOS-Übersteuerung. Mit HA-eigener Context-Weitergabe erzeugt RC.4 in keiner reproduzierten Kette eine falsche Übersteuerung. Nachgewiesene Mechanismen, die sie erklären können: (1) Geräterückmeldung später als 5 s nach dem eigenen Befehl (HA-Context-Fenster); (2) eine gespeicherte Übersteuerung überlebt Neustart/Reload je nach Thread-Wettlauf und hält dann bis zum nächsten CLEAR. Beide sind offene Entscheidungen in [DECISIONS.md](DECISIONS.md).
- Benötigte HAOS-Daten (nach Installation des Branch-Stands nur mit Freigabe; ohne Zugangsdaten):
  1. HAOS- und Home-Assistant-Core-Version.
  2. Integration und Gerätetyp von `light.test_leuchte` (z. B. Zigbee2MQTT, ZHA, Hue, Tuya, ESPHome, `switch_as_x`, Template), Übergangszeit (`transition`).
  3. Diagnoseexport der GlobalEntry (enthält `decision_trace`).
  4. Entity-IDs der Akzentgruppe, der ALL-Gruppe und des Lichtsteuerungsschalters; Zustand und Attribute (`manual_override`, `controlling`) beider Gruppen und der Lampe.
  5. Dashboard-Ereignisprotokoll nach erneutem Auftreten mit dem Branch-Stand: Eintrag „Manuelle Übersteuerung begonnen“ und dessen Ursprung.
  6. Logbuch-/Verlaufseintrag der Lampe zum Zeitpunkt des Beginns (wer hat geschaltet, „ausgelöst durch“).
  7. Andere Automationen, Szenen, Sprachassistenten oder Integrationen (z. B. Adaptive Lighting, HomeKit), die dieselbe Lampe schalten.
  8. Log mit `custom_components.adaptive_areas.light: debug` um einen Helligkeitswechsel.
- Graphify: nicht aktualisiert, weil die Ursache nicht nachgewiesen ist (Graph steht auf `020d90b`, HEAD weicht ab).

## Fortsetzungspunkt (Phase H, Merge-Vorbereitung, 2026-11-27)

- PR #2 (`fix/global-entry-lifecycle`). Squash-Merge vorgesehen, Titel `fix: correct global entry identity and lifecycle`. Kein Merge, keine Version, kein Tag, kein Release.
- Phase H: ungültige gespeicherte Bereichskonfigurationen werden ausdrücklich abgewiesen; Registry-Bereinigung erst am Ende eines erfolgreichen Setups; Identität nicht geladener, konfigurierter Bereiche reserviert; kein Rückfall auf fremde Entitäten an Standard-IDs. Meta-ALL mit fremder Entität an einer Standard-ID und umbenannten Kindgruppen ohne Codeänderung belegt.
- Stable-CI-Hänger: Ursache war der Testaufbau von R05 (siehe [TESTING.md](TESTING.md)), behoben.
- Beta-Job: `homeassistant==2026.12.0b2` gegen `pytest-homeassistant-custom-component==0.13.375` (pinnt 2026.10.4), Installationsabbruch vor Testbeginn; für RC.4 freigegebene Ausnahme.
- HAOS-Abnahme zusätzlich: ein Testbereich mit ungültiger Konfiguration ist nicht vorgesehen; nach Löschung eines Testbereichs bei fehlerhaftem Setup bleiben Entitäten bis zum nächsten erfolgreichen Setup erhalten.

## Fortsetzungspunkt (Phase G, RC.4-Vorbereitung, 2026-11-26)

- Branch `fix/global-entry-lifecycle`; Pull Request nach `main` (Squash-Merge vorgesehen, nicht ausgeführt). Keine Versionsänderung, kein Tag, kein Release.
- Phase G: Meta-Area-ALL beim ersten Setup, Identität bei fehlenden Einzeleinträgen, weitere Schutzbedingungen der Bereinigung, R26 mit nativem Group-Helper, Fehlermeldung bei Bereichs-ID einer Etage. Entscheidung: keine Schema-Migration für RC.4. Wetter-Entität: ohne Laufzeitverbraucher, zurückgestellt.
- Release Notes RC.4: `CHANGELOG.md` „Unreleased“.
- Graphify: vollständiger isolierter Neuaufbau auf `d008bee` (Code-AST, semantische Extraktion von 69 Dokumenten und 11 Bildern, 9 lokale Knowledge-Dateien getrennt ausgewiesen), Konsistenz geprüft (eindeutige IDs, keine hängenden Kanten in `graph.json`, keine Datei mit verlorener semantischer Abdeckung) und übernommen. Sicherung des alten Graphen mit Prüfsummen unter `graphify-out/2026-11-26-before-phase-g-101482c/`. `graphify-out/` bleibt unversioniert; nichts im Repository hängt davon ab. Community-Namen sind aus dominantem Modul und zentralem Knoten abgeleitet.
- HAOS-Abnahme (Installation erst nach Freigabe; destruktive Schritte nur mit eigens angelegtem Testbereich):
  1. Vollständiges HAOS-Backup.
  2. Diagnoseexport der GlobalEntry.
  3. Liste der Entity-IDs, Unique-IDs und Geräte von Adaptive Areas sichern.
  4. Verwaiste und `unavailable` Entitäten notieren.
  5. RC.4 installieren.
  6. HA vollständig neu starten.
  7. Automatische Registry-Bereinigung prüfen: Log „removing … entities of removed Area“; nur Entitäten bereits gelöschter Bereiche dürfen fehlen.
  8. Alle EG- und OG-Bereiche: Entitäten vollständig, keine `_2`.
  9. Meta-Area-ALL-Gruppen (Etagen, Interior, Global) vorhanden, Mitglieder = Gruppen der Kindbereiche; ein neu angelegter Testbereich mit Etage erzeugt die Etagen-ALL-Gruppe ohne zweiten Reload.
  10. Dashboard Licht-Status: `control_switch` zeigt den tatsächlichen Schalter.
  11. Arbeitszimmer: DARK → ON (genau ein Einschalten).
  12. Arbeitszimmer: BRIGHT → OFF.
  13. Arbeitszimmer: DARK → ON.
  14. Mehrere Reloads ohne Gerätezuordnung, Schritte 11–13 wiederholen.
  15. Vollständiger Neustart, Schritte 11–13 wiederholen.
  16. Testbereich umbenennen: Entity-IDs unverändert.
  17. Testbereich löschen und erneut anlegen: Entitäten und Gerät entfernt, danach dieselben IDs.
  18. Automationen mit Adaptive-Areas-Entitäten unverändert funktionsfähig.
  19. Area Climate mit Area Health: Health-Sensor auslösen → `health_alert`.
  20. Übrige Punkte des Plans aus Phase E/F (unten).

## Fortsetzungspunkt (Phase F, 2026-11-26)

- Branch `fix/global-entry-lifecycle`, lokal, nicht gepusht. Die ersten beiden Commits des Branches (`280616a`, `866b50a`) sind einzeln nicht grün (bekannt, unverändert); alle späteren Commits sind einzeln grün. Squash-Merge empfohlen, nicht ausgeführt.
- Phase F: Health-Eingang von Area Climate, stabile Slugs bei Umbenennung, Slug-Kollisionen, Schutzbedingungen der Bereinigung, Options Flow der GlobalEntry. Offene Entscheidung: Bereich und Etage mit identischer ID (gemeinsamer Schlüsselraum in `options[areas]`).
- Qualitätssicherung auf `90d14e4`: Backend 1030 bestanden (RC.3: 995), Coverage 91 %, Frontend-Harness 404/404, `pre-commit run --all-files` in sauberem Worktree bestanden (keine Hook-Änderung), JSON-Validierung und `git diff --check` sauber. Nicht ausgeführt: Hassfest und HACS (kein Docker lokal; laufen in `validation.yaml`), MkDocs-Build (`mkdocs` nicht installiert), Beta-Suite (siehe [TESTING.md](TESTING.md)).
- Graphify: isolierter Code-Graph (AST, ohne semantische Dokumentenschicht, kein Gemini-Schlüssel) auf `90d14e4` im Scratchpad erzeugt, enthält alle neuen Identitäts- und Lifecycle-Funktionen. Nicht nach `graphify-out/` übernommen, weil der bestehende Graph (`101482c`) eine semantische Schicht enthält, die sonst verloren ginge. Vollständiger Neuaufbau mit semantischer Extraktion: Freigabe offen.
- HAOS-Praxistest (zuerst mit einem eigens angelegten Testbereich; keine produktiven Bereiche löschen):
  1. Vollständiges HA-Backup. Diagnose der GlobalEntry exportieren.
  2. Liste aller `adaptive_areas`-Entitäten mit Entity-ID und Unique-ID sichern (Einstellungen → Entitäten, Filter Integration; oder `.storage/core.entity_registry` aus dem Backup). Bereiche und Etagen mit EG/OG-Namensteilen und gleichnamige Bereiche/Etagen notieren.
  3. Update einspielen, HA vollständig neu starten. Entitätsliste vergleichen: keine geänderten Entity-/Unique-IDs, keine neuen `_2`; nur Entitäten bereits gelöschter Bereiche dürfen fehlen (im Log: „removing … entities of removed Area“). Die Liste der entfernten Entitäten prüfen.
  4. Je Bereich mit Lichtgruppe: Dashboard Licht-Status → `control_switch` zeigt den tatsächlichen Schalter und `enabled`. Anwesenheit, Lux BRIGHT → DARK: genau ein Einschalten; DARK → BRIGHT (`dark_on_bright_off`): genau ein Ausschalten; erneut DARK: ein Einschalten (Logbuch/Traces). Keine Gerätezuordnung.
  5. Integration zweimal neu laden und HA einmal neu starten; Schritt 4 jeweils wiederholen.
  6. Testbereich umbenennen (HA-Bereich), danach Reload und Neustart: Entity-IDs unverändert, Gerätename neu.
  7. Testbereich im Panel löschen: Gerät und Entitäten weg; Lampen, Sensoren und Fremd-Entitäten unverändert. Testbereich neu anlegen: dieselben Entity-IDs, keine Duplikate.
  8. Area Climate mit Area Health: Health-Sensor des Bereichs auslösen (z. B. Wasser-Sensor) → Area-Climate-Hinweis `health_alert`.
  9. Ergebnisse und Abweichungen mit Diagnose-Export dokumentieren.

## Fortsetzungspunkt (GlobalEntry-Lebenszyklus nach RC.3, 2026-11-26)

- Branch `fix/global-entry-lifecycle` (lokal, nicht gepusht). Keine Versionsänderung, kein Tag, kein Release.
- Ursache des Praxisfehlers (automatisiert reproduziert, nicht auf HAOS bestätigt): Eigentümerzuordnung über Namensteile der Unique-ID. Details: [CURRENT_STATE.md](CURRENT_STATE.md), Regeln: [ARCHITECTURE.md](ARCHITECTURE.md) „Area identity and lifecycle“.
- Tests: `tests/test_global_entry_lifecycle.py`, 13 davon schlagen auf RC.3 fehl.
- Graphify: Graph auf `101482c`, Code danach wesentlich geändert (neues Modul `helpers/entity_identity.py`). Aktualisierung vorgeschlagen, nicht ausgeführt.
- HAOS-Praxistest:
  1. Vor dem Update: Diagnose der GlobalEntry exportieren; Liste der `adaptive_areas`-Entitäten mit Zustand `unavailable` notieren.
  2. Update einspielen, HA neu starten. Prüfen: keine Entität eines Bereichs „… OG/EG“ fehlt; verwaiste Entitäten gelöschter Bereiche sind entfernt; keine neuen `_2`-Entitäten.
  3. Je Bereich mit Lichtgruppe: Schalter „Light control“ an; Anwesenheit auslösen; Lux unter `turn_on_below` → genau ein Einschalten der Gruppe; Lux über `turn_off_above` (Modus `dark_on_bright_off`/`turn_off`) → genau ein Ausschalten. Ohne Gerätezuordnung.
  4. Integration zweimal neu laden, Schritt 3 wiederholen.
  5. Einen Testbereich anlegen und löschen: Entitäten und Gerät verschwinden aus Einstellungen → Entitäten/Geräte, andere Bereiche unverändert.
  6. Dashboard Licht-Status: `control_switch` zeigt den tatsächlichen Schalter.
  7. Optional: einen Lichtsteuerungsschalter umbenennen und Schritt 3 wiederholen.

## Fortsetzungspunkt (Phase 8.1, 2026-11-25)

- Commits: 7738c9e (translation keys), 400a8a4 (mode matrix and meta lifecycle), c4ebf07 (docs), 5d99d98 (dynamic group membership). Keine Versionsänderung, kein Release, kein Push.
- Dynamische Gruppenmitgliedschaft ist abgedeckt: `tests/test_light_dynamic_membership.py` (8 Tests).
- Graphify: isolierte Neuerstellung nur mit AST-Code, ohne semantische Dokumentschicht (siehe Abschlussbericht). Der bestehende Graph in `graphify-out/` bleibt unverändert, Übernahme nicht freigegeben.
- Release-Ablauf für RC.3: CHANGELOG „Unreleased“ in „1.7.0-rc.3 - <Datum>“ umbenennen (Commit), dann Workflow „Create Release“ mit `1.7.0-rc.3` und Typ `prerelease`. Der Workflow ändert nur das Manifest und pusht einen `chore(release)`-Commit nach `main`. Hassfest und HACS laufen in `validation.yaml` und sind lokal nicht ausgeführt.

## Fortsetzungspunkt (Light-Architektur, 2026-11-25, Phase 5 und 6)

- Light-Refactoring in Phasen: 21722ff (Repairs), 811e18f (Policy-Pfad entfernt), a7c3a55 (Kontextregister), c06b180 (Gruppenbefehle nativ).
- Phase 5: Meta-Area-Helligkeit wird aus den Kindbereichen abgeleitet (DARK bei einem DARK-Kind, BRIGHT nur wenn alle Kinder BRIGHT, sonst UNKNOWN). Details und Tests: [CURRENT_STATE.md](CURRENT_STATE.md).
- Phase 6 (Helligkeitsschwellen, Commit 9d032d2): Variante B, siehe [DECISIONS.md](DECISIONS.md).
- Phase 7 (Regression, RC.3-Vorbereitung): Modus- und Upgrade-Matrix bestanden; beide Produktentscheidungen (UNKNOWN je Modus, Meta-Area-Aggregation) sind verbindlich und abgeschlossen, siehe [DECISIONS.md](DECISIONS.md). RC.3-Praxistest: [RC3_PRACTICAL_TEST_PLAN.md](RC3_PRACTICAL_TEST_PLAN.md).
- Keine Änderung an `_decision_previous`, `_all_target_lights_on`, `_supersede_pending`, `_failed_action`, Ownership-Prüfung oder Kontextregister.
- Graphify-Graph ist veraltet (built_at_commit cd14275); nicht neu erzeugt.

## Fortsetzungspunkt (aktuell, 2026-11-22, rc.14)

- Präsenzdiagnose: `presence.evaluation` in der nativen Diagnose (Home Assistant: Einstellungen → Geräte & Dienste → Adaptive Areas → Bereich → Diagnose herunterladen). Keine Entity-IDs im Export. Details: [CURRENT_STATE.md](CURRENT_STATE.md).
- Gate-Semantik: `DECIDED / CLOSED` (siehe [DECISIONS.md](DECISIONS.md)).
- Ursache des Statusfehlers auf der Testinstanz: `UNRESOLVED`. Nächster Schritt: Diagnose-Export des betroffenen Bereichs auslesen und die Quellen mit `reason` und `status` auswerten.
- Offen und nicht Teil dieses Releases: Formularüberarbeitung, Entitätsauswahl. (Prozent-Hysterese: Entscheidung 2026-11-22, siehe unten.)

## Vorheriger Fortsetzungspunkt (historisch, 2026-11-21)


**Git-Stand (2026-11-21):** Lokaler Entwicklungscommit `222036a` auf `main`: `feat(dashboard): implement intelligence center and native translations` (60 Dateien: Dashboard-Panel, Backend-DTOs, Übersetzungen, Tests, Harness mit Fixtures, Spezifikation, Entscheidungen, Prüfanleitung, Prototyp). Der Commit ist **nicht gepusht**. Sicherungsbranch `backup/pre-push-222036a` zeigt auf denselben Commit. `origin/main` enthält den Release-Bot-Commit `b78964f chore(release): 1.6.19-rc.11` (nur `manifest.json`, Version); `main` und `origin/main` sind **nicht abgeglichen** (`[ahead 1, behind 1]`). Kein Release, kein Tag, keine Versionsänderung.

**Zuletzt erfolgreich ausgeführt (vor dem Commit, auf dem committeten Stand):** Browser-Suite 294/294, Python-Suite 635 bestanden, ruff und black im Prüfmodus sauber, `pre-commit` alle Hooks bestanden. Die nachträgliche Dokumentationsaktualisierung enthält keinen Code und wurde nicht erneut getestet.

**Lokal bewusst uncommittet (nicht Teil des Commits, unverändert erhalten):** `m68-tests.cjs` (einmaliges Patch-Skript mit einem festen lokalen Pfad) und `tests/frontend/measure-after-step2.json`, `measure-phaseE.json`, `measure-step2.json`, `measure-step3.json` (Messausgaben früherer Schritte, nicht referenziert).

**Noch offen, nicht als bestanden ausgewiesen:** reale Integrationstests gemäß `docs/specifications/real-integration-test-plan.md`: Laufzeit in Home Assistant 2026.8.0 und einer aktuellen Version, Panel-Registrierung, natives `frontend/get_translations` und DE/EN-Fallback, Sprachwechsel, Admin-/Non-Admin-Berechtigungen im echten Frontend, WebSocket-Reconnect und Subscriptions, echter Browser-Zoom bei 200 %, reale Theme-Kontraste, Beta-Suite (eine lokale Umgebung `.tox/ha-beta` ist vorhanden, die Suite ist nicht ausgeführt), reale Leistungsmessungen.

Stand 2026-11-20 (Review-Korrekturen nach Abnahme von Schritt 6, historisch):

- **V01 (Übersetzungen):** Die festen deutschen Bezeichnungen im englischen Bereichseditor sind durch EN/DE-Schlüssel ersetzt (`fLabel*`, `areaEditTitle`). Offen: Dashboard-, Trace- und Diagnosetexte außerhalb des Editors; Prüfung der nativen Home-Assistant-Übersetzungsintegration (V10) noch nicht erfolgt.
- **V02 (Entitätskennzeichnung):** erledigt. Gespeicherte Werte werden nach ihrem Zustand gekennzeichnet: nicht gefunden (fehlt in den Zuständen, bleibt ausgewählt), außerhalb dieses Bereichs und bereichsübergreifend zulässig, nicht verfügbar. Die falsche Bereichswarnung beim Thermostat ist entfernt (Prüfungen V02a/V02b, G2 angepasst). Nicht umgesetzt: getrennte Kennzeichnung „vorhanden“ und „fehlende Registry“ als eigener Text (fehlende Registry wird weiter über `fxRegistryMissing` gemeldet).
- **V03 (doppelte Bereichsüberschrift):** erledigt. Die Überschrift des Editors trägt den Bereichsnamen, der zusätzliche Namensabsatz entfällt.
- **V04 (mobiler Kopf):** erledigt. Ursache: Auf Mobilbreite stapelt der Breakpoint den Kopf per `flex-direction: column`; dadurch wurde `flex: 1 1 220px` des Titelblocks zur Höhe und erzeugte einen leeren Block von rund 150 px. Behoben im Breakpoint (Kopf als Zeile, kleinere Überschrift und Marke). Gemessen mit dem Harness (390 px), kein Emulationsartefakt.
- **V05 (mobile Navigation):** teilweise. Navigation per CSS verdichtet (Abstände, Schaltflächen). Nicht umgesetzt: einklappbare Navigation mit aktivem Reiter in der Zusammenfassung.
- **V11 (Fixtures):** teilweise. Neue Backend-Fixtures `get_overview.multi.{admin,user}.json` aus den echten Handlern über `_setup_integration_all_areas_with_meta` (drei Etagen, Meta-Bereiche, Mitglieder). Im Browser-Harness über die Option `multi` eingebunden; Prüfung V11a. Offen: Präsenzzustände, Umweltmesswerte, Licht- und Klimaautomatik, Warnungen, technische Störungen, Vollständigkeit und deaktivierte Features in den Fixtures.
- **V06 (Übersicht):** teilweise. Umgesetzt: KPI-Hervorhebung, Etagengliederung, mobile KPI-Dichte, Präsenzsymbole (●/○/?), getrennte Kartenmarkierungen für Hinweise (`!`), technische Störungen (`×`), unbekannt (`?`), veraltet und keine Hinweise (`✓`). Fixtures: `get_overview.multi.*` (drei Etagen, Meta-Bereiche) und `get_overview.presence.*` (anwesend, abwesend, nicht verfügbar, unbekannt; echte Handler, nur Testentitäten). Prüfungen V06a–V06e, 225 Browser-Prüfungen bestanden.
- **V06-P1 (erledigt, Freigabe 2026-11-20):** `presence.state` kennt den additiven Wert `unknown`, wenn ein Bereich ohne verfügbare Präsenzquelle nicht durch die Automatik belegt ist; Meta-Bereiche nur dann frei, wenn alle geladenen Mitglieder frei sind. `occupied` bleibt Boolean und die Automatik unverändert. Frontend: `_presenceOf` (Boolean zuerst, `unknown` aus `presence.state`), Zähler und Filter nutzen dies. Tests: `tests/test_dashboard_presence_state.py` (9 Prüfungen), Gegenprobe mit dem alten `dashboard.py`: 5 Fehlschläge. Browser V06f. Offen: `counts.occupied` (`_recount` und Backend) zählt weiterhin nach `is_occupied()` über alle Bereiche einschließlich Meta; Konsistenz mit den Karten-Zählern noch zu prüfen. Ein gültiger Hold bei fehlenden Quellen bleibt belegt; ob ein veralteter `occupied`-Zustand ohne Quelle von einem Hold unterscheidbar ist, ist in den vorhandenen Daten nicht eindeutig erkennbar und bleibt dokumentiert.
- **Zähler (erledigt):** `counts.occupied` bleibt unverändert (öffentlicher Vertrag, Automatiksemantik über alle Bereiche einschließlich Meta-Bereiche, in der Oberfläche nicht angezeigt). Neu und additiv: `counts.physical_occupied`, `physical_clear`, `physical_unknown` (nur physische Bereiche, dieselbe Semantik wie die Karten, Meta ausgeschlossen); `_recount` im Frontend pflegt sie nach Live-Updates. Prüfungen: `test_physical_counts_*`, `test_unknown_area_is_not_counted_as_clear`, `test_counts_are_identical_for_admin_and_non_admin`; Gegenprobe: Meta-Bereiche dürfen nicht in den physischen Zählern erscheinen.
- **V06 offen:** Fixtures für Umweltwerte (verfügbar und fehlend), aktive und deaktivierte Features, veraltete Daten und Warnungen; Vorher-Nachher-Screenshots mit gemessener Containerbreite (hell und dunkel, Desktop und Mobil); Kartenhierarchie und Mobildichte abnehmen.
- **V07–V10:** offen. **V05:** offen (einklappbare mobile Navigation).
- **V07–V10:** offen (Progressive Disclosure im Editor, Trace- und Diagnose-Differenzierung, Übersetzungsprüfungen).
- **Schritt 7 (Bereinigung) und Phase 6 (QA):** offen.

- **Konsistenzprüfung `_recount` (erledigt):** `_recount` läuft nur in `_update`, nach dem Ersetzen eines bereits geladenen Bereichs. `_update` verwirft verspätete Antworten über die Sitzungsprüfung (`session`). Live-Updates fügen keine Bereiche hinzu und entfernen keine, daher entstehen keine zusätzlich vollständig wirkenden Kennzahlen. Nach einem Rollenwechsel wird die Übersicht neu geladen; die Kennzahlen werden dabei aus der neuen Liste berechnet. Veraltete Daten werden über die Kennzeichnung „möglicherweise veraltet“ dargestellt, die Kennzahlen behalten den letzten bekannten Stand.

- **Umwelt-Fixtures (erledigt):** Freigegebene Korrektur in `dashboard.py`, `_environment()`: Die Umwelt-Entität wird übernommen, wenn sie einen der Werte `comfort`, `humidity`, `air_quality`, `mould_risk` oder `notices` trägt (`_ENVIRONMENT_MARKERS`). Die Umwelt- und Automatiklogik ist unverändert. Der Regressionstest `test_valid_environment_without_notices_reaches_dashboard` läuft ohne xfail. Fixtures (echte Handler, Admin und Non-Admin): `get_overview.environment_valid.*` (vollständige Werte), `environment_partial.*` (Feuchtesensor nicht verfügbar, mit Hinweis), `environment_disabled.*` (Funktion deaktiviert). Browser-Prüfungen V06g, V06h, V06i. Ergebnis: Browser-Suite 232 von 232, Python-Tests 611 bestanden.
- **Offen:** Die vier Abnahme-Screenshots für V06 mit einer gemeinsamen Fixture und gemessenen Containerbreiten; die Unterscheidung „nicht relevant“ gegenüber „unbekannt“ und „nicht verfügbar“ bei Umweltdaten ist im Backend-Vertrag nicht eindeutig; V05 vollständig; V07 bis V11, Schritt 7, Phase 6, Archiv.

- **V06-Abnahme (erledigt mit dokumentierten Grenzen):** Gemeinsame Fixture `get_overview.acceptance.{admin,user}.json` (echte Handler: drei Etagen, Meta-Bereiche, alle Präsenzzustände; ohne Umweltfunktion, weil das Setup keine Umweltsensoren enthält). Abnahme-Runner: Screenshots unter `scratchpad/v06-acceptance/` (Desktop 1440 px, Container 1328 px; Mobil 390 px, Container 358 px; hell und dunkel), Messwerte in `measurements.json`: kein horizontaler Überlauf, alle Etagen, 8 Karten. Korrigierte Befunde: (1) Singular bei einer Quelle oder einem Hinweis („1 Unavailable source“, „1 Notice“), Prüfungen S16, S16c, B06d angepasst; (2) auf Mobil wurde „master_bedroom“ mitten im Wort getrennt, Kopfzeile der Karte bricht jetzt um, Name bleibt ganz. Vergleich mit `scratchpad/v04-before`: Etagen als Gliederung, Präsenzsymbole und Textlabel, getrennte Kartenmarkierungen, KPI-Hervorhebung bei Befunden, mobil kompaktere Kopfzeile. Nicht eindeutig unterscheidbar im Vertrag: „nicht relevant“ gegenüber „unbekannt“ und „nicht verfügbar“ bei Umweltdaten; Umweltwerte fehlen in dieser Fixture (eigene Fixture `environment_valid|partial|disabled` in Browser-Prüfungen V06g–V06i).

- **V05 (erledigt, mit Befund):** Kompakte, einklappbare Navigation im Browser-Harness: Schalter „Views · <aktive Ansicht>“ (`aria-expanded`, `aria-controls`), Umschaltung über Container-Abfrage (Containerbreite ≤ 680 px, nicht Viewport). Gemessen: Container 288/358/398 px kompakt, 736/992/1328 px volle Navigation; kein horizontaler Überlauf, keine Überlappung. Tastatur mit echten Tasteneingaben (Enter, Leertaste, Escape); Escape schließt, Fokus geht an den Schalter; eingeklappte Ansichten sind nicht fokussierbar; Ansichtswechsel schließt das Menü. Keine WebSocket-Anfragen durch Öffnen oder Schließen; Entwurf bleibt erhalten. Nach asynchronem Neuaufbau der Ansicht bleibt der Fokus erhalten (Gegenprobe: ohne diese Korrektur schlägt V05h fehl). Prüfungen V05a–V05k. Befund: `_setTab` hat keine eigene Dirty-Guard-Prüfung (Bestand; Ansichtswechsel setzt `editing` auf null). Nicht durch V05 geändert und nicht testweise nachgewiesen; zu prüfen. Screenshots: `scratchpad/v05-shots/`.

- **Dirty Guard beim Ansichtswechsel (bestätigter Datenverlust, behoben):** Reproduktion (Prüfungen DG1–DG5, vor der Korrektur DG2, DG3a, DG4, DG4b fehlgeschlagen): Eine ungespeicherte Änderung im Bereichseditor ging beim Ansichtswechsel ohne Rückfrage verloren, weil `_setTab` den Editor schloss und `_openArea` den Entwurf beim erneuten Öffnen durch das Original ersetzte. Korrektur mit einer einzigen Prüfung und einer einzigen Bestätigung: `_areaDirty` (Vergleich ohne leere Werte, Entwurf gegen Original), `_confirmAreaLeave` (`window.confirm` mit `confirmDiscardArea`). Verwendet in `_setTab` (liefert `true`/`false`), Reiter-Klick, `_openConfigArea`, `_openArea` und Hinzufügen. Abbruch behält Ansicht, Fokus und Entwurf; bestätigtes Verwerfen wechselt die Ansicht; keine Schreibanfragen. Die Bestätigung wird im Harness durch einen Aufzeichner ersetzt, die Logik ist echt. Nicht geprüft: die native Dialogdarstellung im Browser.

- **V07 (abgeschlossen mit dokumentierten Grenzen, 2026-11-21):** Zusätzlich geprüft: (a) verspätete Antwort: Eine Speicherantwort für den nicht mehr gezeigten Bereich ändert weder Ansicht noch Editor und zeigt keinen Fehler, auch nicht beim erneuten Öffnen (V07g). Gegenprobe: ohne den Schutz (`_isCurrent` nach der Antwort) schlägt V07g fehl; die Datei wurde danach byte-identisch wiederhergestellt. (b) Touch über echte DevTools-Touch-Ereignisse: Öffnen und Schließen eines Abschnitts, genau eine Speicheranfrage per Touch (V07h, V07h2). (c) 200 % Zoom: Näherung über CSS-`zoom` = 2 bei 1280 px Viewport; keine Abschnittstitel abgeschnitten, Speichern und Abbrechen sichtbar, kein horizontaler Überlauf (V07i). Nicht identisch mit dem Browser-Zoom; echter Browser-Zoom nicht automatisiert. (d) Visuelle Hierarchie: erweiterte Abschnitte zurückgenommen, Grundlegendes hervorgehoben, Hilfetexte sekundär. Screenshots: `scratchpad/v07-shots/` (1440, 390, 320 px; hell und dunkel). Prüfungen: Browser-Suite 260 von 260, Python 615 bestanden.

- **V08 (Decision Trace, abgeschlossen mit dokumentierten Grenzen, 2026-11-21):** Darstellung je Eintrag: Zeitpunkt und Feature oben, Entscheidung → Ergebnis als Zusammenfassung, Auslöser, Übergang, Zustände, Begründung und Zielanzahl als Liste; fehlende Werte neutral als „Unbekannt“ (kursiv, gedämpft), nie als erfundene Entscheidung oder Zuordnung. Produktfehler behoben: Ein fehlender Entscheidungswert wurde als „Other“ angezeigt (Rückfallwert der Zuordnung); jetzt nur bei vorhandenem Wert zugeordnet (V08d). Verspätete Antworten: Gegenprobe ohne Schutz (`_live` bei Trace-Ergebnissen) lässt B09b, R03d und V08f fehlschlagen; die Datei ist danach byte-identisch wiederhergestellt. Fokus des Bereichsfilters bleibt bei Neuaufbau erhalten (V08g). Berechtigung: Der Trace ist nur für Admins in der Navigation; das Backend-Kommando ist mit `require_admin` gesichert (Tests in `tests/test_dashboard_permissions.py`). Keine neuen Felder, keine Logikänderung, Allowlist unverändert. Prüfungen V08a–V08g. Screenshots: `scratchpad/v08-shots/` (1440 px, Container 1328 px; 390 px, Container 358 px; hell und dunkel), keine Überläufe. Grenzen: Der Felder `exception_class` wird bewusst nicht angezeigt (interne Klasse, im bisherigen Stand ebenfalls nicht). Kein echter Browser-Zoom.

- **V09 (Diagnose, abgeschlossen mit dokumentierten Grenzen, 2026-11-21):** Gruppen Status, Technische Befunde, Datenverfügbarkeit (nicht verfügbare Quellen, unbekannter Zustand, Vollständigkeit) und Details; jeder technische Befund mit Schweregrad, Text und Bereichsname (aus der Übersicht, keine Entitäts-IDs). Hinweise werden nicht doppelt gezählt (V09c). Bewertungslogik unverändert. Neue Fixture `get_diagnostics.acceptance.admin.json` aus dem echten Handler (16 nicht verfügbare Quellen). Prüfungen V09a–V09g; Gegenprobe ohne Schutz der verspäteten Antwort schlägt V09g fehl (Datei danach byte-identisch). Behoben: Lange Befundzeilen liefen auf 320 px über (jetzt umbrechend). Screenshots `scratchpad/v09-shots/` (1440 px, Container 1328 px; 390 px, Container 358 px; hell und dunkel), keine Überläufe. Grenzen: Nicht-Admins haben keinen Zugriff (Backend `require_admin`, Navigation ausgeblendet). Kein Export-Funktion vorhanden, daher keine geprüft. Der Schweregrad `info` für unbekannte Quellen wird als Information dargestellt, nicht als Befund.

- **V10 (Übersetzungen, abgeschlossen mit dokumentierten Grenzen, 2026-11-21):** Sprachquelle: `hass.language` (de, sonst EN), eigene Tabellen `EN`/`DE` im Panel. Die native Übersetzungsintegration (`frontend/get_translations`) ist nicht umgesetzt; die Spezifikation (E7) bleibt bedingt und unverifiziert. Die deklarierte Mindestversion (`hacs.json`: 2026.8.0) wurde in dieser Umgebung nicht gegen eine Installation geprüft; keine Kompatibilität wird behauptet. Befunde und Behebungen: (1) Ein fehlender deutscher Schlüssel fiel still auf Englisch zurück (`navViews`, `navMonitoring`) — behoben; (2) weitere deutsche Texte waren englisch oder gleich (`traceFeature`, `diagMeta`, `presenceLabel`, `presets`, `fan_groups`, `cover_groups`, `media_player_groups`) — behoben; (3) Sprachwechsel erzeugte kein Neurendern, Panel blieb bis zur nächsten Aktualisierung in alter Sprache — behoben (`hass`-Setter rendert bei Sprachwechsel; Entwurf, Fokus und Abschnitt bleiben); (4) Abschnittszustand war an den übersetzten Titel gebunden — jetzt Position und Gruppe. Prüfungen: `tests/test_frontend_translations.py` (jeder EN-Schlüssel hat eine eigene DE-Übersetzung, keine unbegründete Gleichheit); Browser V10a–V10d (sichtbare Texte beider Sprachen über alle Ansichten, Editor und Non-Admin; Sprachwechsel mit Entwurf). Gegenprobe: ohne Neurendern schlägt V10d fehl; Datei danach byte-identisch. Verbleibend: Bereichs- und Meta-Namen (`Interior`, `Exterior`) stammen aus den Backend-Daten und sind bewusst nicht übersetzt; Produktname und Untertitel bleiben. Screenshots `scratchpad/v10-shots/` (DE und EN; Desktop 1440 px, Container 1328 px; Mobil 390 px, Container 358 px; hell und dunkel): keine Überläufe. Nicht geprüft: Live-Umschaltung der Sprache durch Home Assistant selbst (nur über den Setter simuliert).

- **V11 (Fixtures, weitgehend abgedeckt, 2026-11-21):** Backend-Fixtures aus echten Handlern: Übersicht Admin/Non-Admin (Etagen, Meta-Bereiche, Präsenz belegt/frei/unbekannt, nicht verfügbare Quellen), Präsenz, Umwelt (gültig, teilweise, deaktiviert), Abnahme-Übersicht, Diagnose mit 16 nicht verfügbaren Quellen, Decision Trace (Bestand und leer), Bereichs- und Feature-Konfiguration. Ergänzt: `get_decision_trace.empty.admin.json`. Offen: deaktivierte oder nicht verfügbare Feature-Zustände in Fixtures sowie unbekannte Quellen aus dem Backend (in Harness-Optionen, nicht als Backend-Fixture); beides als Grenze dokumentiert.
- **E7 (Übersetzung über `frontend/get_translations`, teilweise geklärt):** Nachweis der Mindestversion statisch geführt: Das Paket `homeassistant==2026.8.0` (Wheel nur heruntergeladen, nicht installiert) enthält `frontend/get_translations` mit `language`, `category`, `integration`, `config_flow`, und `async_get_translations`. Schlüsselmodell: Antwort `resources[domain][category]`, verschachtelt; der Lader liest die gesamte Datei `translations/<sprache>.json` je Domäne, ohne Kategoriefilter. Offen und nicht implementiert: Die rund 400 EN/DE-Texte liegen noch im Panel-JavaScript. Eine Umstellung verlagert sie in `translations/en.json` und `de.json` (eigene Kategorie), lädt sie über den Befehl, flacht die Struktur ab und regelt Rückfall und Fehlerfall. Das ist eigenständige Arbeit mit Migrationsentscheidung und ist nicht in dieser Sitzung erledigt. Ob der Befehl im echten Panel-Betrieb mit `hass.language` und Rückfall wie gewünscht arbeitet, ist ohne laufende Home-Assistant-Instanz nicht geprüft. Kompatibilität mit 2026.8.0 wird damit nur für das Vorhandensein des Befehls belegt, nicht für das Panel.

- **E7 (umgesetzt, 2026-11-21; Laufzeit in Home Assistant nicht geprüft):** Alle Dashboard-Texte (`EN`/`DE`-Tabellen, `TRACE_MAP`) stehen in `translations/en.json` und `de.json` unter der Kategorie `dashboard` (Schlüsselzahl je Sprache identisch, Platzhalter abgeglichen, Ereignisbezeichnungen unter `trace_map`). Das Panel lädt sie über `frontend/get_translations` (Parameter `language`, `category`, `integration`) und liest `resources` mit flachen Schlüsseln `component.adaptive_areas.dashboard.*`. Fallback Englisch liefert Home Assistant selbst; die Harness-Antwort bildet das nach. Feste deutsche Bezeichnungen der Ausstattungsmerkmale entfernt (`featureLabels`). Ladezustand: Ladeanzeige bis die Texte da sind; bei vollständigem Ladefehler eine Fehlermeldung ohne Navigation (zweisprachig fest, keine Übersetzung). Keine Anfrage bei wiederholten `hass`-Aktualisierungen; Sprachwechsel zeigt nur die geladene Sprache; verspätete andere Sprachen werden nicht angezeigt. Prüfungen: Python `tests/test_frontend_translations.py` (Schlüsselabdeckung, Platzhalter, Backend-Schlüssel erhalten, keine alten Tabellen); Browser E7a–E7d sowie V10a–V10d, V08, V09 und alle bisherigen Prüfungen (282/282, Python 623/623). **Nicht geprüft:** Verhalten mit einer laufenden Home-Assistant-Instanz, Kompatibilität mit 2026.8.0 zur Laufzeit, und das Caching/Verhalten von HA bei Sprachwechsel über die echte Oberfläche.

- **Schritt 7 (erledigt):** 29 nachweislich ungenutzte Dashboard-Übersetzungsschlüssel (beide Sprachen, Referenzsuche ohne Treffer) und eine ungenutzte Methode (`_climateTargets`) entfernt; zwei statische Prüfungen auf den live Pfad (`_scopedOptions`) umgestellt. Keine CSS-Klasse ungenutzt (dynamische `flag-${kind}`). Keine öffentlichen Backend-Kommandos oder Konfigurationsfelder berührt.
- **Phase 6 (teilweise, 2026-11-21):** Regressionen (Stand Abschluss 2026-11-21): Python 635/635, Browser 294/294. Sicherheit: `tests/test_websocket_admin_only.py` (alle zehn Admin-Kommandos lehnen Nicht-Admins ab, echtes Backend); Harness prüft keine Rollen. Responsivität: 112 Messungen (320–1440 px, DE/EN, hell/dunkel, vier Ansichten), kein Dokumentüberlauf; bei 320 px überlappten Bereichskarten den Container um 8 px (behoben); Kontrast: zwei Textpaare unter 4,5:1 (behoben), 20 Paare geprüft (Harness-Palette). Lint: ruff und black im Prüfmodus bestanden. Archiv `~/adaptive-areas-final-review.zip` mit Manifest (SHA-256, 372 Dateien), Ergebnissen und README-REVIEW.md mit den Grenzen. **Offen (nicht in dieser Umgebung prüfbar):** Lauf in einer echten Home-Assistant-Instanz, Laufzeitkompatibilität 2026.8.0 und aktuelle Version, echter Browser-Zoom 200 %, Beta-Suite, reale Leistungsmessung, Kontrast mit echten HA-Themes.

- **Abschlussprüfung 2026-11-21:** Dirty-Vergleich des Bereichseditors geprüft (`_normalizedArea`/`_areaDirty`). Bestätigter Fehler: Ein aktiviertes Feature ohne Einstellungen (`features.<name> = {}`) wurde nicht als Änderung erkannt, weil leere Objekte verworfen wurden; Rückfrage und Schutz griffen nicht (Gegenprobe DG7h). Behoben: Leere Feature-Einträge bleiben erkennbar; Listen werden als Mengen verglichen (Reihenfolge der Auswahl war ein Fehlalarm, DG7i); fehlende und leere Werte bleiben gleichwertig (DG7f). Prüfungen DG6–DG7k (DG7j/DG7k: echte Mehrfachauswahl, Reihenfolge und Hinzufügen/Entfernen); Browser 294/294. Git (nur lesend): lokal `main` auf `3b1bd6a`, `origin/main` (bekannt, nicht abgerufen) einen Commit voraus: `b78964f chore(release): 1.6.19-rc.11`, ändert nur `manifest.json` (Version). Kein Dashboard-Bezug. Reale Integrationstests: Anleitung `docs/specifications/real-integration-test-plan.md`, Status nicht ausgeführt.

**Nächster Schritt: Die Prüfanleitung `docs/specifications/real-integration-test-plan.md` in einer Home-Assistant-Instanz 2026.8.0 und einer aktuellen Version ausführen und die Ergebnistabelle füllen; danach echter Browser-Zoom und reale Theme-Kontraste.**

Historische Aussage zum Stand 2026-11-20 (vor dem Commit `222036a`). Approval Gate 3 bleibt für weitere Git- und Release-Aktionen geschlossen. Die nicht atomare Schreiblücke zwischen Serverprüfung und Schreibvorgang bleibt dokumentiert; die drei Lüfterlisten bleiben ausgeschlossen.

### Vorheriger Stand (Referenz)

Stand 2026-11-20: Schritte 4 bis 6 im Implementierungsstand abgeschlossen (Archiv und Screenshots offen). Vorher: 6.1 und Abschnitt 11 erledigt; 6.2 geprüft; 6.3 begonnen (acht von zwölf Feldern); 6.4 bis 6.8 offen. Schritt 7 und Phase 6 offen.

### Schritt 6 – Stand

- **6.1 und Abschnitt 11:** erledigt (siehe `dashboard-migration-matrix.md` §13). Der Semantik-Prüfpunkt zu `unavailable_source_count` ist geschlossen: einziger Verbraucher ist `get_diagnostics`.
- **Umwelt-Vokabular (Auftrag 1):** Für acht der zwölf Felder gibt es Bezeichnungen, Beschreibungen und Optionen in `translations/en.json` und `de.json` (Konfigurationsablauf „feature_conf_environment“). Die Raumkategorie hat sechs Optionen (`RoomCategory`). Übernommen wurden nur diese Texte; keine Einheiten oder Schwellenwerte erfunden.
- **Schritt 6.6 (2026-11-20):** keine weiteren Feature-Konfigurationen nötig; die übrigen Features sind nur Schalter. Dokumentiert in der Matrix §16.
- **Schritt 6.7 (2026-11-20):** Konfigurationsvollständigkeit und Speichersemantik in der Matrix §16 belegt (Merge-Tests, Null-Werte, leere Eingaben, entfernte Schlüssel). Domänenfilter der globalen Felder: bereits umgesetzt und getestet (GL1). Navigation nach dem Speichern: ausdrücklich getestet (N1). Terminologie korrigiert: Die Schwellen sind Beleuchtungsstärken in lx; „Thermistor-Schwellen“ im früheren Bericht war falsch. Negative Gegenproben für die neuen administrativen Tests stehen noch aus.
- **Schritt 6.7 Gegenproben (2026-11-20):** sieben gezielte Mutationen in einer isolierten Kopie, alle von der vorgesehenen Prüfung erkannt (Matrix §17). M4 bezieht sich auf den alten Speicherpfad, der in 6.8 entfällt; dessen Anforderung deckt jetzt M68a–d und L3/L4, K4/K5 ab.
- **Schritt 6.8 Ablösung (2026-11-20):** Die editierbaren Licht- und Klimaformulare in den Analyse-Ansichten sind entfernt; die Ansichten zeigen gespeicherte Werte nur lesend und verlinken in den Bereichseditor. Keine Speicherpfade mehr außer dem zentralen Editor. Prüfungen AV1–AV6, M68a–d. Die R05-Prüfungen sind auf die zentrale Entsprechung abgebildet (Matrix §17).
- **Fehler aus dem Abschluss behoben:** Analyse-Lichttab lädt jetzt beim Öffnen die Laufzeitdaten.
- **Offen:** Prüfarchiv `adaptive-areas-step6-review.zip` mit Screenshots der produktiven Oberfläche (noch nicht erstellt). Allgemeine Frontend-Bereinigung bleibt Schritt 7.
- **Schritt 6.4 Licht (2026-11-20):** im zentralen Editor integriert: Schwellen und Verzögerung (`features.light`) sowie vier Lichtgruppen mit Lichtern, Aktivierung, Blockierung und Helligkeit. Gespeicherte Auswahl wird angezeigt; ein fehlender Wert zeigt eine neutrale Platzhalteroption, die nicht geschrieben wird. Konfliktbehandlung über das Bereichsmodell. Test L1–L4.
- **Schritt 6.5 Klima (2026-11-20):** im zentralen Editor integriert: Thermostat, vier Presets, Belegungsschwelle (0 gültig). Thermostat nur nach Domäne `climate` angeboten. Test K1–K5.
- **Bestätigter Fehler behoben:** Das bestehende Lichtformular übernahm im Konfliktfall die Serverkonfiguration; eine zweite Speicherung schrieb danach. Jetzt schreibt eine erneute Speicherung nicht; nur der Bereichseditor mit ausdrücklicher Bestätigung kann überschreiben (R05 Tests angepasst).
- **Bestätigter Fehler behoben:** Stored activation and brightness of light groups were displayed as the first option; saving would have changed them. Jetzt ausgewählt.
- **Offen:** Bestehende Licht- und Klimaformulare bleiben bis 6.8. 6.6 weitere Features, 6.7 Migrationsprüfung und negative Gegenproben, Prüfarchiv mit Screenshots. Domänenfilter globale Wetter-Entität und Helligkeitssensor.
- **Stand Schritt 6.3 (2026-11-20):**
  - Feuchtedauer integriert: Label „Mindestdauer erhöhter Luftfeuchtigkeit (min)“, belegt durch `environment.py` (Minuten, Umrechnung mit 60).
  - Passive Kühlung: Label „Temperaturdifferenz für passive Kühlung (K)“, belegt durch den Vergleich `outdoor <= temperature - delta`.
  - Entitätsfilter über die vorhandenen Home-Assistant-Registries: Bereichsbezogene Felder nur für Entitäten des Bereichs (direkt oder über das Gerät), Außenquellen bereichsübergreifend. Gespeicherte Werte außerhalb bleiben erhalten und sind gekennzeichnet.
  - **Blocker: Lüfter** (Lüftungs-, Umluft-, ausgeschlossene Ventilatoren). Kein Laufzeitverbraucher im Repository; die Funktion ist im Code nicht bestimmbar. Nicht integriert, bis der Eigentümer die Funktion festlegt. Die Felder bleiben beim Speichern erhalten.
  - Tests G1–G5 (Browser), die Umrechnung und Feldwerte sind dokumentiert in `dashboard-migration-matrix.md` §14.
- **6.2 Globale Einstellungen:** Das Backend kennt nur zwei globale Optionen (Wetter-Entität, Helligkeitssensor). Entwurf, Konfliktbestätigung, Sperre gegen Mehrfachübermittlung, Rollen- und Sitzungsschutz sind vorhanden und getestet (S17, S18, B05, B02). Ergänzung der Gruppierung entfällt, weil es keine weiteren Optionen gibt.
- **6.3 Zentraler Bereichseditor (begonnen):**
  - Im Bereichsformular gibt es jetzt den Abschnitt „Raumklima“ mit Raumkategorie, Bereichs-Temperatursensor, Bereichs-Feuchtesensor, Außentemperatur, Außenfeuchte, Oberflächentemperatur, relevanten Fenstern und der passiven Kühlung.
  - Eine nicht angebotene gespeicherte Raumkategorie wird nicht stillschweigend ersetzt (Platzhalteroption).
  - Eine leere Zahleneingabe behält den gespeicherten Wert; ein leerer Sensor wird ausdrücklich als leer gesendet.
  - Entwurf, Konflikt und Sperre laufen über das bestehende Bereichsentwurfsmodell.
  - Fehler behoben: Nach erfolgreichem Speichern blieb das Formular stehen, die Bereichsliste erschien nicht. Das war ein Fehler aus R04 und betraf jede Bereichsspeicherung.
  - Offen: die vier Felder ohne Bezeichnung (Lüfter, Feuchtedauer); die Sensorauswahl zeigt alle Entitäten, nicht nur die des Home-Assistant-Bereichs wie in der Spezifikation.
  - Tests F1–F4 (Browser).
- **6.4 und 6.5 Licht und Klima:** Noch nicht in den zentralen Editor übernommen. Die bisherigen Formulare bestehen weiter. Die Überschreibbestätigung für normales Erneutspeichern ist dort noch nicht umgesetzt.
- **6.6 bis 6.8:** offen. Die Ablösung der bisherigen Formulare erfolgt erst nach nachgewiesener Gleichwertigkeit.
- **Prüfarchiv und Screenshots:** `adaptive-areas-step6-review.zip` erst nach Abschluss von Schritt 6.

### Offene Punkte für Phase 6

- Native Tastatur (Enter, Leertaste, Tabulator): O14 prüft nur Fokussierbarkeit und Aktivierung mit Fokus. Offen.
- Responsive, Kontrast, 200 % Zoom: nicht gemessen.
- Minimal unterstützte Home-Assistant-Version, native Übersetzungsintegration, Pre-Commit, Performance-Vergleich, Tests in einer echten Home-Assistant-Instanz, Sicherheits- und Migrationsprüfung.
- Beta-Suite lokal nicht ausführbar.

### Nächste Schritte

1. Fachliche Klärung der drei offenen Umweltfelder (siehe oben).
2. 6.3 abschließen: Sensorauswahl auf den Home-Assistant-Bereich einschränken (nach Entscheidung), vier fehlende Felder ergänzen.
3. 6.4 und 6.5: Licht- und Klimaformulare in den zentralen Editor, mit Konfliktbestätigung wie bei Bereichen.
4. 6.7 Migrationsprüfung und negative Gegenproben, 6.8 Ablösung, Prüfarchiv mit Screenshots.

Keine Commits, Pushes, Tags, Releases oder Versionsänderungen. Approval Gate 3 bleibt geschlossen.

## Abgenommener Stand Schritt 3 (Referenz)

Technisch abgenommen am 2026-11-20 (Prüfarchiv v3). Keine Commits, Pushes, Tags, Releases, Versionsänderungen, keine Git-Synchronisation.

## Gemeinsame Mechanismen (bei weiterer Arbeit erhalten)

- **Guard für asynchrone Operationen:** `_guard(check)` erfasst Sitzung, Rolle und eine operationsspezifische Bedingung; `_isCurrent(guard)` wird nach jedem `await` und in `catch` geprüft; `_begin(key, guard)` / `_end(key, guard)` vergeben die Zuständigkeit für ein Ladeflag, sodass nur die jüngste Anfrage ihr Flag zurücksetzt. `_live(key, guard)` = aktuell **und** Besitzer der Anfrage; nur damit werden Ergebnisse, Fehler und abschließende Renderings übernommen (R03). Verwendet von `_loadGlobalSettings`, `_loadLightRuntime`, `_loadClimateRuntime`, `_loadTrace`, `_loadDiagnostics`, `_refresh`, `_saveGlobalSettings`, `_save`, `_delete`, `_saveFeatures` (Licht- und Klimakonfiguration), `_areasChanged`.
- **Subscription-Generation:** `_link.subGen`, unabhängig von der Sitzungsnummer; `_subscribe` bindet den Callback an Generation und Rolle, `_detach` erhöht die Generation. Alte Callbacks verarbeiten nichts, auch kein `areas_changed` (R01). Das Backend liest die Rolle bei jedem Ereignis.
- **Schreibsperren:** `_drafts.area.saving` (Bereichsformular), `_requests.areaDelete`, `_requests.lightForm`, `_requests.climateForm` (R04, R05).
- **Bereinigung:** `_discardAdminData` verwirft bei Wechsel zu Nicht-Admin alle administrativen Daten, Entwürfe, Konflikte, Auswahlzustände und Zuständigkeiten (`_owners`).
- **Zustand:** ausschließlich in `_link`, `_data`, `_ui`, `_drafts`, `_requests`, `_errors` (plus `_hass`, `_owners` und zwei Bindungsmarker). Browser-Check B09a erkennt neue verstreute Felder.

## Review-Befunde

| ID | Befund | Ursache (bestätigt) | Korrektur | Tests | Stand |
|---|---|---|---|---|---|
| B01 | Subscription nach Wiederverbindung | Callback an alte Sitzungsnummer gebunden | Callback ohne Sitzungsbindung | B01a–c | behoben, Re-Review ausstehend |
| B02 | Sitzungsschutz asynchroner Admin-Operationen | keine Prüfung nach `await`; ältere `finally` setzten neuere Flags zurück | gemeinsamer Guard (s. o.); `_save` und `_delete` rufen `_refresh` mit Sitzung; doppelte Prüfzeile entfernt; Licht-Guard an Aufrufkontext gebunden (Editor bzw. Licht-Tab) | B02a–e | behoben, Re-Review ausstehend |
| B03 | Unvollständige Bereinigung | Bereichsentwurf, Konflikte, Auswahl blieben erhalten | `_discardAdminData` vollständig | B03, B02c/d | behoben, Re-Review ausstehend |
| B04 | Kein echtes Bereichsentwurfsmodell | Formular aus `item.options`; `_ui.editing` war das Konfigurationsobjekt selbst; „Serverwerte übernehmen“ veränderte `_data.config` | `_drafts.area.draft`; Formular rendert daraus; `input`/`change` schreiben in den Entwurf; `_ui.editing` nur `{area_id, name, create}`; Abbrechen verwirft den Entwurf | B04a–f | behoben, Re-Review ausstehend |
| B05 | Keine frische Serverprüfung vor Schreiben | Konflikt nur nach Wiederverbindung erkannt | Vor jedem regulären Schreiben wird der Serverstand gelesen; Schreiben nur bei Gleichheit mit dem Entwurfsursprung; Überschreiben nur für den bestätigten Konflikt; fehlgeschlagene Prüfung oder gelöschter Bereich → kein Schreiben | B05a–h | behoben, Re-Review ausstehend |
| B06/B07 | „Keine Hinweise“ bei fehlenden, unbekannten oder veralteten Daten | fehlende Werte als 0 gezählt; `stale` nie angezeigt; **zusätzlich:** `sources.unavailable` existiert im Backend nicht, technische Probleme waren dadurch immer 0 | Unbekannt statt 0; „Möglicherweise veraltet“ bei Offline oder fehlgeschlagenem Neuladen; nicht verfügbare Quellen aus `sources.total − sources.available` | B06a–d, B07a–b, B10c–d; S16 auf echte Backend-Form umgestellt | behoben, Re-Review ausstehend |
| B08 | Fehlende `enabled_features` als deaktiviert | Rückfall auf eine leere Liste | Zustand `unknown`, „Aktivierung unbekannt“; ebenso fehlende `active_states` und `occupied` → „Unbekannt“ | B08a–d | behoben, Re-Review ausstehend |
| B09 | Zustand außerhalb der Teilzustände | `_trace`, `_diagnostics`, `_pendingRender`, `_lightAreaId`, `_climateAreaId` | nach `_data` bzw. `_ui`; Trace und Diagnose nutzen den Guard; doppelte Rücksetzungen entfernt | B09a–b | behoben, Re-Review ausstehend |
| B10 | Neue/entfernte Bereiche über Subscription | Entitätsindex nur beim Abonnieren gebaut; **zusätzlich:** eine Entität konnte nur einem Bereich zugeordnet sein (Kind- und Meta-Bereich) | Dispatcher-Signal `SIGNAL_AREAS_CHANGED` nach Setup/Unload; Subscription baut Index neu und sendet datenfreies `{"areas_changed": true}`; Index Entität → Liste von Bereichen; Panel lädt Überblick (Admin: auch Konfiguration) geschützt neu, Rendern während Bearbeitung aufgeschoben | Python `tests/test_dashboard_subscription.py` (3); Browser B10a–f | behoben, Re-Review ausstehend |
| B11 | Dokumentation | widersprüchliche Stände | `CURRENT_STATE.md`, `ARCHITECTURE.md`, `TESTING.md`, Non-Admin-Review, Migrationsmatrix (Befehlszählung 12 genutzt / 1 ungenutzt) aktualisiert | Review der Dokumente | behoben, Re-Review ausstehend |

Stand B01–B11 nach dem Re-Review: grundsätzlich bestätigt; die Restpunkte stehen in der folgenden Tabelle.

### Restbefunde aus dem Re-Review

| ID | Befund | Ursache (bestätigt) | Korrektur | Tests | Stand |
|---|---|---|---|---|---|
| R01 | Subscription ohne Gültigkeitsprüfung | Callback nach B01 ungebunden; alte Callbacks lösten nach Rollenwechsel, Neuabonnieren oder Entfernen des Panels weiter `areas_changed`-Neuladen aus; **serverseitig** wurde die Rolle einmalig beim Abonnieren gelesen, Home Assistant ändert `connection.user` bei Gruppenänderung aber in place und hält die Verbindung offen, ein entzogener Admin bekam weiter Entitäts-IDs | Subscription-Generation `_link.subGen`, Callback an Generation und Rolle gebunden, `_detach` invalidiert; Backend liest die Rolle bei jedem Ereignis | Browser R01a–d (alte Callbacks ausdrücklich nach der Abmeldung aufgerufen); Python `test_subscription_reads_the_role_for_every_event` | behoben, Prüfung ausstehend |
| R02 | Globaler Ladezugriff ohne gemeinsamen Guard | nur Sitzungsprüfung, Fehler und `finally` ungeschützt | `_guard`/`_live`/`_begin`/`_end`; Erfolg, Fehler und Abschluss geschützt; Render nur bei aktueller Anfrage | R02a–b | behoben, Prüfung ausstehend |
| R03 | Ergebnisse und Fehler nicht an Anfrageidentität gebunden | Besitz nur beim Zurücksetzen des Flags geprüft | `_live` für Daten, Fehler und Render bei Licht- und Klima-Laufzeit; ebenso Trace, Diagnose und `_refresh` | R03a–d (zwei Anfragen desselben Bereichs, umgekehrte Antwortreihenfolge; auch verspäteter Fehler) | behoben, Prüfung ausstehend |
| R04 | Keine Mehrfachsendesperre für Bereichsschreibvorgänge | kein Speicherstatus; Löschen ohne Fehlerbehandlung (unbehandelte Ausnahme) | `_drafts.area.saving` mit Besitz, deaktivierter Submit, Render nur bei aktueller Anfrage; Löschen mit Sperre, Guard, übersetzter Fehlermeldung | R04a–c | behoben, Prüfung ausstehend |
| R05 | Licht- und Klimakonfiguration umgehen Schutz und Konfliktprüfung | eigene Schreibpfade ohne Guard, `_refresh()` ohne Sitzung; Licht ohne jede Fehlerbehandlung; **bestehender Fehler seit Phase E:** Klima-Speichern scheiterte immer mit `TypeError` (Submit-Handler übergab das Panel statt des Formulars); Schwellwert-Fehlermeldung erschien wörtlich als `${this._t.thresholdInvalid}` | gemeinsamer Pfad `_saveFeatures`: Serverprüfung der Bereichs-Features vor dem Schreiben, bei Abweichung kein Schreiben, Eingaben bleiben, Konfliktmeldung, erneutes Speichern wendet die Eingaben auf den aktuellen Serverstand an; Sperre; Guard; Fehler ohne Neu-Rendern im Formular angezeigt; Konfigurationsmöglichkeiten unverändert | R05a–g | behoben, Prüfung ausstehend |

Harness-Befund (Wartebedingung `stage` unter Chromium): Ursache im Testaufbau gefunden. Der Runner navigierte per `file://` zur Harness-Seite und wertete Navigationsfehler nicht aus; ein Chromium ohne Dateizugriff (zum Beispiel ein Sandbox-Paket oder ein Archiv unter `/tmp`) zeigt dann eine Fehlerseite, und `stage` erscheint nie. Zusätzlich konnte `readyState === "complete"` noch von `about:blank` erfüllt werden. Korrektur nur im Testaufbau: Das Markup wird per `Page.setDocumentContent` gesetzt (kein Dateizugriff, keine Navigation); bei Nichtbereitschaft meldet der Runner URL, Zustand und Seiteninhalt. Lokal ist nur Chrome verfügbar; ein Lauf unter Chromium wurde nicht ausgeführt.

## Gegenprobe mit fehlerhaften Implementierungen (2026-11-20)

Methode: isolierte Kopien außerhalb des Repositorys (Scratchpad). Je Befund ein Runner, der nur die Vorbereitung und den jeweiligen Befundblock aus `tests/frontend/run.mjs` enthält. Lauf gegen die gesicherte Panel-Datei unmittelbar vor der Korrektur (B01: Panel aus dem ersten Prüfarchiv, also der begutachtete Stand) und als Kontrolle gegen das aktuelle Panel. In der isolierten Kopie werfen Auswertungsfehler keine Ausnahme, sondern lassen den nächsten Check scheitern; ein Fehlschlag kann dadurch nie als bestanden gelten. Backend B10: `websocket.py` (alte Subscription) und `__init__.py` (HEAD, ohne Signal) in einer isolierten Repository-Kopie. Der produktive Working Tree wurde nicht verändert.

| Befund | Fehlerhafter Stand | Korrigiert | Scheitern mit fehlerhaftem Stand (Ursache) |
|---|---|---|---|
| B01 | 3/4 | 4/4 | B01c: Update nach Wiederverbindung wird verworfen (Karte unverändert) |
| B02 | 1/6 | 6/6 | B02a/e: verspätete Lichtantwort für Bereich A überschreibt Bereich B; B02b: ältere Klimaantwort gewinnt, Flag während der neueren Anfrage falsch; **B02c: nach Rollenwechsel landen Admin-Laufzeitdaten beim Nicht-Admin**; **B02d: verspätete Speicherantwort stellt nach Rollenwechsel Admin-Werte als Original und Entwurf wieder her** |
| B03 | 1/2 | 2/2 | Bereichsentwurf, Konflikte (global und Bereich) und Auswahl bleiben nach Rollenwechsel erhalten |
| B04 | 1/7 | 7/7 | Kein Entwurf vorhanden; Eingaben gehen bei Fehler und Neu-Rendern verloren; „Serverwerte übernehmen“ verändert `_data.config` (`clear_timeout` 77 in der geladenen Konfiguration), `_ui.editing` ist das vollständige Konfigurationsobjekt |
| B05 | 3/9 | 9/9 | Schreiben trotz geänderten Serverstands ohne Wiederverbindung (global und Bereich), Überschreiben über einen neueren Konflikt hinweg, Schreiben trotz fehlgeschlagener Prüfung bzw. gelöschtem Bereich |
| B06/B07 | 2/7 | 7/7 | „Keine Hinweise“ bei fehlenden, unvollständigen, unbekannten und offline veralteten Daten; nicht verfügbare Quellen nicht erkannt |
| B08 | 2/5 | 5/5 | Fehlende `enabled_features` → `area-off`/„Nicht aktiviert“; fehlende `active_states` → „Nein“; fehlendes `occupied` → „Nicht belegt“ |
| B09 | 1/3 | 3/3 | Verstreute Felder `_trace`, `_diagnostics`, `_pendingRender`; verspätete Trace-Antwort überschreibt den aktuellen Bereich (Ergebnis leer) |
| B10 (Browser) | 2/7 | 7/7 | Neue und entfernte Bereiche erscheinen bzw. verschwinden nicht; kein Veraltet-Hinweis bei fehlgeschlagenem Neuladen; kein aufgeschobenes Rendern |
| B10 (Backend) | 0/3 | 3/3 | Kein `areas_changed`-Ereignis; geteilte Entität aktualisiert nur die Meta-Bereiche, nicht den Kindbereich `kitchen` |

Die Checks, die auch mit dem fehlerhaften Stand bestehen, prüfen Positivpfade oder Invarianten, die schon vorher galten: B01a/b (Zahl der Subscriptions und Listener), B05c/f (bestätigtes Überschreiben schreibt), B07b, B08d, B10d, „no JavaScript errors“.

### Stichprobe R01–R05 (2026-11-20)

Gleiches Verfahren; fehlerhafter Stand ist die Panel-Sicherung vor R01–R05, Backend R01 mit einmalig gelesener Rolle. Die Werkzeuge sind in `review/mutation/tools/make-isolated-runner.cjs` zusammengefasst.

| Befund | Fehlerhafter Stand | Korrigiert | Scheitern mit fehlerhaftem Stand (Ursache) |
|---|---|---|---|
| R01 (Browser) | 2/5 | 5/5 | alte Callbacks lösen nach Rollenwechsel, Neuabonnieren und Entfernen des Panels Neuladeaufrufe aus (`get_overview`, `get_area_configuration`) |
| R01 (Backend) | 3/4 | 4/4 | nach Entzug der Admin-Rechte enthalten die Ereignisse weiter `controls` |
| R02 | 2/3 | 3/3 | verspäteter Ladefehler nach Rollenwechsel wird als `loadError` übernommen |
| R03 | 1/5 | 5/5 | ältere Antwort (Licht, Klima, Trace) bzw. älterer Fehler überschreibt die neuere |
| R04 | 1/4 | 4/4 | drei Schreibvorgänge bei Mehrfachsenden; zwei Löschaufrufe, keine Meldung, unbehandelte Ausnahme |
| R05 | 1/8 | 8/8 | Licht schreibt trotz Konflikt und zeigt keinen Fehler; Klima-Speichern scheitert mit `TypeError` |

Auch mit dem fehlerhaften Stand bestehen R01b, R02b, R04b und R05c: Die bisherige Sitzungsprüfung deckte diese Fälle bereits ab.

Hinweis zur Methode: Zwei Läufe hingen zunächst. Ursache war ein Fehler in der isolierten Testkopie (der Ersatzwert nach einem Auswertungsfehler wurde als Promise behandelt), nicht im Produktcode. Er wurde korrigiert und alle Paare wurden neu ausgeführt. Die Protokolle liegen im Prüfarchiv unter `review/mutation/`.

## Verifiziert (2026-11-20)

- Browser-Harness: 213 von 213 (`node tests/frontend/run.mjs`; 124 aus Schritt 3, 16 für 4.1, 12 für 4.2, 10 für 4.3/4.4).
- Python, Home Assistant 2026.10.4: 594 bestanden (586 vorher plus 2 für Etage und Mitglieder) (`.tox/ha-stable/bin/python -m pytest -q`; 584 aus Schritt 3 plus 2 für die Umgebungsschwärzung).
- Lint im Prüfmodus (ruff 0.16.2, black aus dem pre-commit-Cache, `scripts/validate_json.py`, `git diff --check`) für alle geänderten Python- und JSON-Dateien: sauber.
- Nicht ausgeführt: Beta-Suite (die lokale Umgebung `.tox/ha-beta` enthält HA 2026.8.0b6 und eine pytest-Version, die unter Python 3.14 an `ast.Str` scheitert; ein Neuaufbau braucht Netzwerkzugriff); `pre-commit` selbst (die Hooks reparieren Dateien automatisch); Browserlauf unter Chromium (lokal nur Chrome); Prüfung in einer echten Home-Assistant-Instanz.

## Bekannte technische Grenzen

- Keine atomare Konflikterkennung im Backend: Zwischen der Serverprüfung direkt vor dem Schreiben und dem Schreiben selbst kann eine Änderung unerkannt bleiben.
- Eine verspätete, serverseitig erfolgreiche Speicherung nach Sitzungs- oder Rollenwechsel wird nicht in den Entwurf übernommen; sie erscheint nach der Neusynchronisierung als Serverstand bzw. Konflikt.
- Schlägt das Neuladen nach `areas_changed` fehl, bleiben die Karten als „möglicherweise veraltet“ markiert, bis ein späteres Neuladen oder eine Wiederverbindung gelingt.
- Globale Feature-Zustände existieren im Backend nicht und werden nicht abgeleitet. Klimadaten sind nicht im Überblick enthalten (Zustand „Daten unbekannt“).
- Architekturrelevante Neuerung (in `docs/ARCHITECTURE.md` beschrieben, in `docs/DECISIONS.md` als bestätigt eingetragen): internes Dispatcher-Signal und zusätzlicher datenfreier Ereignistyp in `subscribe_updates` (additiv, kein Storage- oder Schemawechsel).
- Licht- und Klimakonfiguration haben kein Entwurfsmodell wie das Bereichsformular. Eingaben bleiben bei Fehlern und Konflikten erhalten, weil dann nicht neu gerendert wird. Ein vollständiges Neu-Rendern durch Strukturereignisse oder Wiederverbindung setzt diese Formulare aber auf den Serverstand zurück. Die Verlagerung in die zentrale Bereichsadministration ist Teil der freigegebenen Migration.
- Die Konfliktprüfung der Licht- und Klimaformulare vergleicht nur die Features des Bereichs, weil nur diese gesendet und im Backend zusammengeführt werden. Das „erneute Speichern nach Konflikt“ ist die bewusste Bestätigung und gilt nur für den gemeldeten Serverstand.

## Nächster konkreter Schritt

Siehe „Fortsetzungspunkt“ oben (Schritt 4.2). Zu erhaltende Vorgaben aus der Abnahme: Licht- und Klimaformulare werden in Schritt 6 vollständig in das zentrale Entwurfs- und Konfliktmodell überführt; dort darf ein erneutes normales Speichern keine ausdrückliche Überschreibbestätigung ersetzen. Die Race Condition zwischen Serverprüfung und Schreiben bleibt dokumentiert; keine neue atomare Backend-Schnittstelle.

## Prüfungen ausführen

- Browser: `node tests/frontend/run.mjs` (gegen eine andere Panel-Datei: `--panel=<pfad>`, nur in einer isolierten Kopie verwenden)
- Fixtures aus dem Backend: `ADAPTIVE_AREAS_WRITE_FIXTURES=1 .tox/ha-stable/bin/pytest tests/test_frontend_fixtures.py`
- Python: `.tox/ha-stable/bin/pytest -q tests`

## Bereichsverwaltung: Übergabe (2026-11-22, Release-Candidate 1.6.19-rc.13)

- Stand: Entitätslisten eingeklappt; Präsenz-Domänen als Checkbox-Dropdown mit genau `binary_sensor`, `device_tracker`, `media_player`, `remote`; gespeicherte Altwerte bleiben sichtbar und werden nicht gelöscht.
- Backend: `area_config.py` lehnt eine Domäne nur ab, wenn ein Speichern sie neu hinzufügt. Bereits gespeicherte Werte bleiben, bewusstes Entfernen ist erlaubt. Tests: `tests/test_presence_domain_selection.py`.
- **DECIDED / CLOSED (verbindlich, keine offene Frage):** Gespeicherte, nicht unterstützte Präsenzdomänen bleiben erhalten (keine automatische Löschung, keine Migration, keine Bereinigung beim Speichern). Eine leere Präsenzdomänenauswahl ist ausdrücklich erlaubt (keine Pflichtauswahl, keine blockierende Validierung, keine automatische Ergänzung). Festgelegt in `docs/DECISIONS.md` und `docs/specifications/dashboard-migration-matrix.md`.
- Warnung bei fehlender Quelle: erscheint nur bei `presence.total == 0`. Dieser Wert zählt bereits Presence Hold, BLE und Wasp in a Box, wenn die Funktion aktiv ist.
- Lux-Felder: kompakt (höchstens 9 rem), getestet mit BR11.
- Nicht geprüft: reale Home-Assistant-Instanz (Dropdown, eingeklappte Listen, Speichern mit echtem Präsenzsensor), 200-%-Zoom, geöffnetes Domänen-Dropdown bei langen IDs.
- Tests: Python 660 passed; Browser 333/333 passed; Ruff und Black sauber (isoliert in `.tox/lint`); pre-commit nicht ausgeführt.
- Graph `graphify-out/` gehört zu HEAD `45a0911` und ist für diese Änderungen veraltet; nicht neu erzeugt.

## Übersetzungen: Hassfest-Korrektur (2026-11-22)

- Ursache: Hassfest meldete `[TRANSLATIONS] Invalid translations/en.json: not a valid option at 'dashboard'`. Die Kategorie `dashboard` lag in `translations/en.json` und `de.json`. Der Fehler bestand bereits auf `326a978` (geplanter Validate-Lauf vom 04:04).
- Lösung: Die 365 Dashboard-Texte stehen in `custom_components/adaptive_areas/dashboard_texts/{en,de}.json`. Der Befehl `adaptive_areas/get_dashboard_texts` liefert sie an das Panel (`dashboard_texts.py`, `websocket.py`). Das Panel übernimmt das bisherige flache Schlüsselformat. Englisch bleibt der Fallback. Die Integrationsdateien enthalten nur noch Hassfest-Kategorien.
- Die Entscheidung steht als **DECIDED / CLOSED** in `docs/DECISIONS.md`. Der ältere E7-Eintrag ist als ersetzt markiert.
- Lokal nicht prüfbar: der Hassfest-Lauf selbst. Docker und das Hassfest-Skript sind nicht verfügbar. Maßgeblich bleibt der GitHub-Validate-Workflow.

## Anwesenheitsquellen: Korrektur Teil 1 (2026-11-22, Arbeitsstand, ungebunden)

- Festgelegt: „Entitäten in die Analyse einschließen“ ist optional. Die automatische Erkennung geeigneter Anwesenheitsquellen (Zuordnung zum Bereich, Domäne, Geräteklasse) funktioniert unabhängig davon.
- Nachgewiesene Ursachen (Backend, `helpers/sources.py`):
  1. `physical_presence_source_ids` las die Geräteklassen mit Default `[]`. Fehlte der Schlüssel, wurden keine Binärsensoren automatisch erkannt. Jetzt Default `DEFAULT_PRESENCE_DEVICE_SENSOR_CLASS` (motion, occupancy, presence).
  2. Entitäten aus `loaded_entity_ids` umgingen `exclude_entities`. Ausschluss gewinnt jetzt vor Einschluss.
- Tests: `tests/test_presence_source_detection.py` (neu, 10 Fälle inkl. Fenster-/Tür-/Feuchte-/Rauchkontakte, Include ohne Geräteklasse, leere Domänenauswahl, alle vier Domänen, unknown/unavailable).
- Frontend-Warnung (`_noPresenceSourcesHint`): Bei ungespeicherten Domänenänderungen zeigt das Panel einen neutralen Hinweis (`presenceHintPending`) statt einer definitiven Warnung. Der Hinweis aktualisiert sich live über `_captureAreaDraft`. Die Warnung selbst erscheint nur bei gespeichertem Stand mit `presence.total == 0`. Der Text wurde präzisiert (`noPresenceSources`).
- Harness: `tests/frontend/run.mjs` BR12a/b auf neuen Wortlaut angepasst, BR12c neu (ungespeicherte Änderung → neutraler Hinweis).

### Offen (nächste Sitzung, Reihenfolge wie im Auftrag)

- Remote und Media Player: `on` gilt aktuell als aktiv. Für `remote` ist das fachlich unscharf (Gerät an ≠ Anwesenheit). Entscheidung vor Änderung nötig, Zustandsmodell je Domäne dokumentieren.
- Entitätsauswahl vereinheitlichen (Abschnitt 6 des Auftrags): Referenz ist das Dropdown „Entität für Dunkelheit“. Noch nicht umgesetzt.
- Formularlayout, einklappbare Abschnitte, 200 % Zoom und schmale Breiten (Abschnitte 7 und 8): nicht umgesetzt, nicht geprüft.
- Reale Home-Assistant-Prüfung mit echtem Bewegungs- und Fenstersensor: offen.
- Die IDE meldet in `helpers/sources.py` (`_numeric_state_value`) einen möglichen `None`-Zugriff. Die Zeile existierte vorher und ist nicht Teil dieser Änderung; prüfen.
- Graph `graphify-out/` gehört zu `45a0911`, HEAD ist `609d16f`. Nicht neu erzeugt.

## Präsenz-Domänensemantik (DECIDED / CLOSED, 2026-11-22)

- Verbindlich, keine erneute Rückfrage: `media_player` zählt nur bei `playing` (Aktivitätsindiz, keine bestätigte Anwesenheit). `on` allein gilt nicht mehr als Anwesenheit. `remote` wird nie automatisch erkannt; ein ausdrücklich eingeschlossenes Remote zählt bei `on`. `device_tracker` bleibt unverändert.
- Verhaltensänderung: Bereiche, die sich auf einen im Leerlauf eingeschalteten Media Player oder ein automatisch gefundenes Remote verlassen haben, verlieren dieses Signal, bis die Quelle eingeschlossen wird oder der Media Player spielt. Gespeicherte Konfigurationen bleiben erhalten, keine Datenmigration.
- Regressionstests: `tests/test_sources.py`, `tests/test_presence_source_detection.py`. Entscheidung in `docs/DECISIONS.md`, Spezifikation in `docs/source/concepts/presence-sensing.md`.

## Bereichseinstellungen: gemeinsame Entitätsauswahl (2026-11-22, Arbeitsstand, ungebunden)

- Neue Komponente: `custom_components/adaptive_areas/frontend/aa-entity-picker.js` (`<aa-entity-picker>`, lesbar, kein Build). Einzel- und Mehrfachauswahl über die Attribute `name` und `multiple`. Ausgewählte Werte stehen als versteckte `input[name=...]` im Light DOM, damit das Formular und der Entwurfsfluss sie unverändert lesen.
- Registrierung: `panel.py` lädt das Modul über `add_extra_js_url` mit Versionsparameter, vor dem Panel. Das Modul gilt damit für jede HA-Oberfläche, nicht nur für das Panel. Der Harness lädt es vor dem Panel.
- Umgestellt: Einschluss, Ausschluss, Anwesenheits-Kontrollentitäten, Behalten (`keep_only`) als Mehrfachauswahl; „Entität für Dunkelheit“, Akzentuierung und Schlaf als Einzelauswahl.
- Bedienung: Suche nach Entity-ID und Anzeigename (ohne Groß-/Kleinschreibung); Chips mit Entfernen-Knopf; Pfeiltasten bewegen die aktive Option, Enter schaltet um, Escape schließt nur die Liste, Tab verlässt die Komponente ohne Falle; sichtbarer Fokus. Öffnen und Schließen ändert nichts. Enter sendet das Formular nicht ab.
- Begrenzung: höchstens 200 Treffer werden angezeigt, mit Hinweis.
- Nicht umgestellt (weiterhin native Auswahl): Umgebungsfelder (`area_temperature_sensor`, `area_humidity_sensor`, `outdoor_*`, `surface_temperature_entity`), `relevant_windows` (bereichsgefiltert) und die globalen Felder `weather_entity` und `global_light_sensor`. Das ist ein eigener Schritt, weil diese Felder den Bereichsfilter der Registry nutzen.
- Formular: einheitliche Feldhöhe 40 px, Beschriftung über dem Feld, Checkbox mit 18 px und gleicher Mitte wie das Label. Lux-Felder bleiben höchstens 9 rem breit. Abschnittsköpfe sind dezent getrennt; Auf- und Zuklappen verändert keine Eingaben und keinen Entwurf.
- Tests: `tests/frontend/run.mjs` PK1–PK9, SEC1–SEC2 (neu), H4/BR11/RS1 angepasst. Ergebnis 350/350. Python: 701 bestanden.
- Nicht geprüft: echter 200-%-Browserzoom (der Harness verkleinert nur das Viewport und ist ausdrücklich keine Zoomprüfung), reale Home-Assistant-Oberfläche, Tastatur mit Screenreader.

## Entity-Picker: endgültiger Ladeweg und Vereinheitlichung (2026-11-22, Arbeitsstand, ungebunden)

- Ladeweg: `panel.py` registriert das Panel mit `module_url` = `frontend/adaptive-areas-loader.js?v=<Version>`. Der Lader importiert zuerst `aa-entity-picker.js` und danach `adaptive-areas-panel.js`. Keine globale Einbindung (`add_extra_js_url` entfernt). Fällt der Picker-Import aus, öffnet sich das Panel trotzdem und zeigt einen Fehlerhinweis (`pickerUnavailable`) auf dem Bereichsformular und in den Globalen Einstellungen.
- Die Panel-Datei bleibt ein klassisches Skript ohne `import` (der Harness wertet sie so aus). Modul-Caching: der Lader trägt die Version; die relativen Imports laufen über den statischen Pfad ohne `cache_headers`, also werden sie revalidiert.
- Umgestellt auf `<aa-entity-picker>`: Temperatur- und Feuchtesensoren des Bereichs, Außen- und Oberflächensensor, `relevant_windows`, `weather_entity`, `global_light_sensor` (Luxfilter: `device_class: illuminance` oder Einheit `lx`), `climate:entity_id`, Lichter der Lichtgruppen (Domäne `light`), Einschluss, Ausschluss, Anwesenheits-Kontrolle, Behalten.
- Filter der Komponente: Attribute `domain`, `device-class` (mit Lux-Regel), `scope` (Bereichs-ID, nur wenn die Registry verfügbar ist). Gespeicherte Werte bleiben immer sichtbar und werden bei Abweichung gekennzeichnet: nicht gefunden, außerhalb des Bereichs oder nicht verfügbar (vorhandene Texte `fxMarkNotFound`, `fxOutOfScope`, `fxMarkUnavailable`).
- Trefferliste: höchstens 200 Einträge. Gespeicherte Werte gehen nie verloren, auch nicht jenseits der Grenze.
- Barrierefreiheit: Combobox mit `aria-expanded`, `aria-controls`, `aria-activedescendant`, beschriftetes Suchfeld, Entfernen-Schaltflächen mit Namen, Statusmeldung bei Änderungen (`role=status`). Ein echter Screenreader-Test ist nicht durchgeführt.
- Bewusst nativ geblieben (keine Entitäten): Bereichs-Auswahlen (`data-*-area`, `area_id`), Aufzählungen (`room_category`, `type`, Aktivierung, Helligkeit der Lichtgruppen) und die Zustandswerte der Blockierung (`*_blocking_states`, Zeichenketten).
- Tests: Browser 354/354 (neu: ENT1–ENT3, ENT5; umgestellt: S-, G-, V02-, LG1-, S4-Prüfungen). Python 707 bestanden, inkl. neuer `tests/test_panel_loading.py`.
- Nicht geprüft: echter 200-%-Browserzoom (Browser-Zoom ist im Harness nicht steuerbar; Viewport-Verkleinerung ist keine Zoomprüfung), echte Home-Assistant-Oberfläche, Screenreader.

## CI: Beta-Job sichtbar machen und Release-Ausnahme 1.6.19-rc.15 (2026-11-22)

- `continue-on-error` aus `test-beta` entfernt. Der Beta-Job meldet seinen Status. Andere Workflows enthalten keine Fehlerunterdrückung (geprüft: `grep continue-on-error|| true`). `main` hat keine Branch-Protection.
- Beta-Prüfung: **BLOCKED – TEST INFRASTRUCTURE INCOMPATIBILITY**. Details und Nachweis: `docs/TESTING.md` („Beta test job status“).
- Ausnahme ausschließlich für `1.6.19-rc.15`: Release, obwohl der Beta-Job rot ist, weil der Fehler aus der Testinfrastruktur stammt. Voraussetzungen: Validate, Lint, Stable-Tests, lokale Python- und Browser-Suite, JSON, Release-Validierung grün. Keine Umstellung auf optional.
- Für künftige Releases gilt wieder: Beta-Job muss grün sein.

## Praxisabnahme 1.6.19-rc.15 (2026-11-22, Benutzerfeedback)

Die folgenden Punkte stammen aus Praxistests des Benutzers in einer realen Home-Assistant-Instanz. Sie sind Benutzerfeedback und keine automatisierten Testergebnisse. Sie gelten für die geprüften Szenarien und nicht pauschal für alle Geräte oder Home-Assistant-Versionen.

- Präsenzquellenerkennung: fachlich abgenommen. Acht Praxistests bestanden (inaktiver Bewegungssensor → frei; bestätigte Bewegung → belegt; geöffneter Fensterkontakt → keine Anwesenheit; automatische Erkennung ohne manuelle Einschlussliste).
- Bereichsstatus frei/belegt: für die geprüften Szenarien abgenommen.
- Fensterkontakte: geprüfter Ausschluss erfolgreich.
- Entity-Picker: fachlich abgenommen (Suche, Hinzufügen, Entfernen, Speichern, Persistenz nach Bereichswechsel).
- Formularlayout und einklappbare Abschnitte: fachlich abgenommen.
- Speicherung und Neuladen: erfolgreich geprüft (Dashboard nach Neuladen und erneutem Öffnen).
- Nicht abgenommen oder nicht geprüft: Beta-Kompatibilität (BLOCKED – TEST INFRASTRUCTURE INCOMPATIBILITY), echter 200-%-Browserzoom, Screenreader, Verhalten mit weiteren Sensortypen und Home-Assistant-Versionen.

### Vorschläge (ohne Umsetzung)

- Beta-CI-Modernisierung: `docs/specifications/beta-ci-modernisation.md`.
- Prozent-Hysterese für Lichtautomatik: Entscheidung DECIDED / CLOSED (2026-11-22). Plan und Entscheidungen: `docs/specifications/light-percent-hysteresis-plan.md`. Die frühere absolute Festlegung in `dashboard-migration-matrix.md` ist ersetzt.

## Helligkeitsdiagnose (lokal, 2026-11-22, nicht committet)

- Nicht committet. Geändert: `dashboard.py`, `helpers/light_runtime.py` (nur lesende Eigenschaft `last_dispatched_action`), Panel, DE/EN-Texte, Tests (`test_dashboard.py`, `test_brightness_diagnostics.py`, `test_light_override_sequence.py`, `run.mjs`), `docs/specifications/brightness-diagnostics-concept.md`.
- Ursprüngliche Praxisprobleme: weiterhin **ungeklärt**. Benötigte Daten: siehe `docs/specifications/brightness-diagnostics-concept.md`, Abschnitt 7.
- Datenschutz: Entitäts-IDs und Grenzwerte erscheinen nur im Admin-Laufzeitstatus (Endpunkt admin-only) und in der Admin-Detailansicht. Für Nicht-Administratoren bleibt die Quelle ausgeblendet.

## Lichtsteuerung und eindeutige Gruppenzuordnung (2026-11-24, Commit 76bd329, Pre-Release 1.7.0-rc.1)

- Stand, Regeln und Prüfungen: `docs/CURRENT_STATE.md`, Abschnitt „Lichtsteuerung und eindeutige Gruppenzuordnung“.
- Gemeinsame Speicherprüfung: `helpers/light_ownership_runtime.py` (`light_group_ownership_problem`), genutzt von `area_config.py` (Dashboard) und `config_flow.py` (Options-Flow).
- Nächster Schritt: praktische Validierung von 1.7.0-rc.1 auf Home Assistant 2026.11.3 (Testsystem), danach Auswertung. Ein Stable-Release ist nicht freigegeben.
- Bekannt: Das Legacy-Feld `vacancy_delay` wirkt nicht mehr, wird aber im Light-Tab noch angezeigt (CHANGELOG, Known issues).

## Handover: correction block 1.7.0-rc.1 (not committed)

- Start with `docs/CURRENT_STATE.md` (section "Final state of the correction block").
- Before committing: re-run the browser harness (`node tests/frontend/run.mjs`). The last run that completed was 416/416, before the backend-only changes of the last round; the final run hung in the local headless Chrome.
- Open decisions: brightness limits while Light is disabled (review); policy-only removed in Phase 2 (Variante B, no automatic default group); Options Flow offers no view of retained configurations.
- Commit allowlist and messages: see the final report of this session; split by topic (light control, Area brightness sensor, retained features, device-class selector).
- Phase 3 committed as a7c3a55 (group context tracking simplified, threshold model in helpers/brightness.py, light_policy.py removed). Phase 4 in the working tree, not committed: helpers/light_executor.py removed (native light.turn_on/turn_off service call in light.py), helpers/light_dispatch.py removed (Override enum now in helpers/light_transition.py). Kept with evidence: _all_target_lights_on, _supersede_pending, _failed_action, _decision_previous (see docs/CURRENT_STATE.md).
- Phase 2 committed locally as 811e18f (policy-only removed). Phase 3 in the working tree: origin registry reduced to the automatic group Context ids (signal numbering, thread binding, executor tracking and listener notification removed), `_light_group_own_contexts` removed, threshold model moved to helpers/brightness.py (light_policy.py removed). Not committed. Next: Phase 4 control mechanisms (_failed_action, _supersede_pending, _decision_previous, _all_target_lights_on).
