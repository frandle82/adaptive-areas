# Feature-Spezifikationen – Adaptive Areas

## 1. Präsenzerkennung
- **Eingangssensoren:** Bewegung, Präsenz (mmWave), Tür-/Fensterkontakte, Mediaplayer, BLE-Tracker.
- **Wasp-in-a-Box:**
  - Kombiniert Bewegungssensor ("Wasp") mit Türkontakt ("Box").
  - Bei geschlossener Tür bleibt der Raum auf "belegt", sobald einmal Bewegung erkannt wurde, bis die Tür wieder geöffnet wird.
- **BLE Tracking & Presence Hold:**
  - RSSI-Schwellenwerte und Timeout-Handling für BLE-Beacons und Wearables.
  - Presence-Hold-Schalter zum manuellen Festhalten des Präsenzzustands.

## 2. Beleuchtungssteuerung
- **Lichtgruppen:** Overhead (Decke), Task (Arbeitslicht), Accent (Akzentlicht), Night (Nachtlicht).
- **Adaptive Anpassung:**
  - Helligkeit und Farbtemperatur gekoppelt an Sonnenstand, Lux-Werte und Raumzustand (z. B. `sleep`, `accent`, `bright`).
- **Sleep Mode:**
  - Spezielle Nachtbeleuchtung mit minimaler Helligkeit und warmen Farben.

## 3. Sensor-Aggregate & Schwellenwerte
- Aggregation von Temperatur, Luftfeuchtigkeit, Beleuchtungsstärke (Lux), Luftqualität (CO2, VOC).
- Statistische Methoden: Durchschnitt, Median, Min, Max.
- Schwellenwertsensoren für Lüftungsempfehlungen und Klimaautomatik.
