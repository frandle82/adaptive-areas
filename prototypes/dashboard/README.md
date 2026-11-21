# Dashboard-Prototyp (Designreferenz)

Eigenständige, lokal aufrufbare Designreferenz für das Adaptive-Areas-Dashboard.
Eine Datei, keine Abhängigkeiten, keine externen Ressourcen.

**Abgrenzung:** Dieser Prototyp ist **nicht** Bestandteil der Integration. Er liegt außerhalb von `custom_components/` und wird von der Integration weder geladen noch referenziert. Er enthält ausschließlich Mock-Daten und simuliert alle Zustände. Keine Verbindung zu Home Assistant, keine Schreibvorgänge, keine Aktionen an Geräten.

## Aufrufen

    open prototypes/dashboard/index.html

Oder die Datei im Browser öffnen. Der Startzustand kann über URL-Parameter gesetzt werden, z. B.

    index.html?role=user&theme=dark&width=390&view=overview

| Parameter | Werte | Wirkung |
|---|---|---|
| `role` | `admin`, `user` | Rolle (Administrator oder Nicht-Admin) |
| `theme` | `light`, `dark` | Theme |
| `width` | `320`, `390`, `430`, `768`, `1024`, `1280`, `1440` | Simulierte Containerbreite |
| `view` | `overview`, `areas`, `area`, `environment`, `cleaning`, `usage`, `lighting`, `climate`, `trace`, `diagnostics`, `settings`, `manage`, `editor` | Ansicht |
| `area` | z. B. `buero`, `keller`, `gaeste-wc-mit-sehr-langem-namen` | Bereich für Detail und Editor |
| `loss`, `unknown`, `disabled`, `savefail`, `loading`, `empty` | `1` | Zustände |
| `controls` | `1` | Prototyp-Steuerung ausgeklappt |

## Finaler Funktionsumfang

**Navigation.** Drei Gruppen: Monitoring (Überblick, Bereiche, Raumklima, Reinigung, Raumnutzung), Analyse (Lichtautomatik, Klimaautomatik, Decision Trace, Diagnose) und Verwaltung (Globale Einstellungen, Bereichsverwaltung). Die Gruppen stehen oben, die Unteransichten darunter; beides umbricht und scrollt nicht horizontal. Nicht-Admins sehen nur die Monitoring-Gruppe.

**Überblick.** Vier Kennzahlen mit Icons, jede als Filter nutzbar: Physische Bereiche (Innen/Außen), Belegt (als „x von y“ mit Unbekannt- und Nicht-verfügbar-Angabe), Umwelthinweise (fachlich) und Technische Auffälligkeiten (nicht verfügbare Quellen, getrennt von fachlichen Hinweisen). Meta-Areas (Floor, Interior, Global) als Aggregatkarten, nicht in die Kennzahlen eingerechnet. Filter: Alle, Belegt, Frei, Unbekannt, Nicht verfügbar, Umwelthinweise, Technisch, Auffälligkeiten; Suche nach dem Bereichsnamen.

**Area Cards.** Icon, Name (umbricht, wird nicht gekürzt), Präsenzstatus mit Farbe und Text, Pfeil als Navigationshinweis. Messwerte mit Icon und Einheit. Zusatzzustände als Chips. Kontext nur bei Relevanz: Umwelthinweise, Reinigung, Leuchten (nur wenn an), technische Quellen. Bei Platzmangel steht der Status unter dem Namen.

**Bereichsdetail.** Präsenz, Raumklima, Reinigung, Raumnutzung, Zustand, Lichtautomatik und letzte Entscheidungen (Admin). Bei Verbindungsverlust mit Hinweis auf veraltete Werte.

**Raumklima.** Balken für Temperatur, Luftfeuchte und CO₂ mit eindeutig beschrifteter Skala. Fehlende Werte als „Keine Daten“ (nicht 0). Außenbereiche nur als Referenz. Klassifikationen werden nicht erfunden, sondern als Hinweis auf die Integration gekennzeichnet. Tabelle als ergänzende Ansicht.

**Reinigung.** Nach Fälligkeit gruppiert: Überfällig, Heute fällig, Bald fällig, Nicht fällig, Keine Daten, Deaktiviert. Kennzahlen je Gruppe. Keine Steuerung.

**Raumnutzung.** Horizontale Balken auf einer Zeitskala von 0 bis 8 Stunden. Fehlende Daten und deaktivierte Bereiche getrennt aufgeführt, nicht als 0 Minuten.

**Lichtautomatik und Klimaautomatik (Admin).** Nur Anzeige des Laufzeitstatus, gekennzeichnet als „Simulierte Laufzeitdaten“. Keine Solltemperatur, kein Modus.

**Decision Trace (Admin).** Neueste Entscheidungen zuerst. Je Eintrag Feature, Auslöser, Entscheidung und Ergebnis (Beobachtet, Ausgeführt, Übersprungen). Fehlende Begründungen werden ausdrücklich als „Keine Begründung aufgezeichnet“ angezeigt. Filter nach Bereich, Feature und Ergebnis, Hinweis auf das Limit von 20 Einträgen je Bereich.

**Diagnose (Admin).** Sicherheitswarnungen, technische Fehler, fehlende Daten und Normalbetrieb getrennt. Verweis auf die native Integrationsdiagnose.

**Einstellungen und Bereichsverwaltung (Admin).** Jedes Formular hat einen Basiszustand (letzter Speicherstand) und einen Entwurf. „Speichern“ ist nur aktiv, wenn der Entwurf vom Basiszustand abweicht. Während eines Speichervorgangs sind Eingaben gesperrt, Doppelklicks lösen nur einen Vorgang aus, und Navigation oder Rollenwechsel sind gesperrt. Beim Verlassen mit ungespeicherten Änderungen erscheint eine Bestätigung („Bleiben“ oder „Verwerfen“). Jeder Editor hat einen eigenen Entwurf; Editoren werden nicht vermischt. Bei simuliertem Fehler oder bei Verbindungsverlust bleiben die Eingaben erhalten, und es wird kein Erfolg vorgetäuscht. Löschen öffnet einen modalen Dialog, bei Schließen kehrt der Fokus zum Auslöser zurück.

**Feature-Verfügbarkeit.** Fünf Features sind unabhängig schaltbar: Raumklima, Reinigung, Raumnutzung, Lichtautomatik und Klimaautomatik. Pro Feature gibt es vier Zustände: global deaktiviert (Navigation und Ansichten ausgeblendet, Karten zeigen „Deaktiviert (global)“), für einen Bereich deaktiviert („Für Bereich aus“), aktiv ohne Daten („Keine Daten“) und aktiv mit Daten. Ein deaktiviertes Feature erzeugt keine Warnungen und keine Filtertreffer. Verbindungsverlust ist davon getrennt.

**Verbindungsverlust.** Die Kopfzeile zeigt „Verbindung unterbrochen“ mit dem Zeitpunkt der letzten erfolgreichen Aktualisierung. Zuletzt bekannte Werte bleiben sichtbar und sind als „zuletzt bekannt“ gekennzeichnet. Belegt wird nicht als aktuelle Zahl behauptet („—“, darunter „Zuletzt bekannt: x von y“). Meta-Areas zeigen die letzte Belegung ebenfalls als „zuletzt bekannt“. Historische Entscheidungen bleiben Fakten; die Liste selbst ist als veraltet markiert.

**Systemzustände.** Verbunden, Verbindung unterbrochen, Lädt (Skeleton), Leer (keine Bereiche), Unbekannt, Nicht verfügbar, Speicherfehler.

## Steuerung (nur Prototyp)

Oben links ausklappbar: Rolle, Theme, Breite (320 bis 1440 px) und Zustände (Verbindung unterbrochen, Unbekannte Daten, fünf Feature-Schalter „… aus“, Speichern schlägt fehl). Die Steuerung ist nicht Teil der Produktoberfläche.

## Überprüfen

1. Datei öffnen und den Mock-Hinweis oben prüfen.
2. Rolle auf Nicht-Admin: Admin-Gruppen verschwinden. Direktaufruf einer Admin-Ansicht (`?role=user&view=trace`) zeigt „Nur für Administratoren“.
3. Breiten 320 bis 1440 durchschalten: Kartenraster passt sich an; kein horizontales Scrollen.
4. Verbindung unterbrochen aktivieren: Banner erscheint, Belegt zeigt „—“, Werte sind als veraltet markiert.
5. Feature global deaktivieren: Raumklima, Reinigung und Raumnutzung verschwinden aus der Navigation; Karten zeigen „Deaktiviert“.
6. Bereichsdetail „Keller“: Reinigung als „Für diesen Bereich deaktiviert“.
7. Einstellungen: Wert ändern, Speichern; mit „Speichern schlägt fehl“ wiederholen.

## Automatisierte Prüfung (Stand dieser Version)

Die Prüfung lief über das Chrome DevTools Protocol mit der installierten Google Chrome, ohne zusätzliche Pakete. Das Prüfskript liegt im Scratchpad der Entwicklungssitzung und ist nicht Teil des Repositorys.

- 75 von 75 Interaktionstests bestanden (Navigation, Rollen, Theme, Suche und Filter, Bereichsauswahl, Trace, Formular mit Fokus- und Entwurfsverhalten, Speichern und Fehler, Doppelklick, Löschdialog mit Fokusrückkehr, Navigation und Editorwechsel bei ungespeicherten Änderungen, Verbindungsverlust und Kombinationen, Feature-Verfügbarkeit, lange Namen, Tastaturbedienung, 60 schnelle Ansichtswechsel, Sortierung Raumnutzung und Trace).
- 98 von 98 Layout-Messungen ohne Befund bei 320, 390, 430, 768, 1024, 1280 und 1440 px (jeweils gemessene Container-Breite, kein horizontaler Überlauf, keine abgeschnittenen Namen, Touch-Ziele mindestens 44 px).
- Keine JavaScript-Fehler in der Konsole.
- Kontrast Statusfarben auf Karten 5,3 bis 7,1 zu 1 (Text).
- Dark Mode und Light Mode: in dieser Prüfung nicht erneut je Breite gemessen; die Farbwerte sind über Variablen definiert.

## Bekannte Einschränkungen

- Alle Daten sind Mock-Daten. Der Prototyp zeigt keine echten Zustände aus Home Assistant.
- Die Screenshots und die Prüfung stammen von Headless Chrome, nicht von einer Home-Assistant-Instanz.
- Tastaturbedienung ist durch Tests der Navigation und des Dialogs abgedeckt, aber nicht vollständig geprüft.
- Die Bereichsnamen sind nicht gekürzt. Bei sehr langen Namen umbrechen sie in mehrere Zeilen.
- Der Primärbutton-Kontrast (weiß auf Dunkelteal) ist rechnerisch 5,7 zu 1, nicht gemessen.
- Die Zuordnung der Icons zu Bereichen ist im Prototyp fest hinterlegt. In der Produktion müssten die Area-Icons der Konfiguration verwendet werden.
- Die Mindestversion der Übersetzungsschnittstelle und die Zuordnung der Klassifikationen sind nicht Teil dieses Prototyps.
- Der Prototyp ist eine Designreferenz und kein Nachweis der Kompatibilität mit Home Assistant.
