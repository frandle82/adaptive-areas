# Git-Sicherheit – Adaptive Areas

* **Statusprüfung:** Vor Beginn jeder Änderung `git status --short --branch` ausführen und vorhandene Änderungen identifizieren.
* **Erhalts-Pflicht:** Fremde/vorhandene Änderungen des Benutzers niemals überschreiben oder löschen.
* **Fokus:** Nur Dateien ändern, die direkt zum aktuellen Auftrag gehören.
* **Keine unaufgeforderten Aktionen:** Keine Commits, Pushes, Tags, Releases, Branches oder Pull Requests ohne ausdrücklichen Auftrag.
* **Changelog-Pflicht bei Releases:** Wird ein Pre-Release oder Release erstellt, muss immer ein Changelog angegeben/erstellt werden.
* **Destruktive Befehle verboten:** Kein `git reset --hard`, `git clean`, Rebase oder Force-Push ohne ausdrücklichen Auftrag von Andreas.
