# Area Climate, Area Health, and Room Usage

## Area Climate

Area Climate is optional and disabled by default. It retains the existing `environment` entity and unique IDs for compatibility. Indoor Areas receive the full assessment and recommendations. Exterior Areas receive a reduced measurement and air-quality assessment without comfort, mould, ventilation, window, fan, or cooling outputs. Missing dimensions remain `unknown`; never interpreted as healthy.

Enable **Area Climate** under **Feature selection**. **Area Climate** is the single configuration menu for primary climate sources in both indoor and exterior Areas. It contains temperature and relative humidity for both Area types. Indoor Areas additionally contain the room category, cool-surface temperature, relevant windows, passive-cooling difference, and humidity-warning duration. Exterior Areas intentionally omit those indoor-only controls. Pollutant sensors are discovered automatically from Home Assistant metadata. Explicit outdoor temperature/humidity and concrete fan fields are not offered. `source_entities` provides traceability.

Every primary climate source selector uses the same candidate basis: all `sensor.*` entities assigned directly or through a device to the current Home Assistant Area. Adaptive Areas-generated sensors are excluded to prevent self-reference. Device class, unit, integration, manufacturer, and names never remove a primary-source candidate.

Exterior Areas are the central outdoor reference. Their primary temperature and humidity values plus supported PM2.5, PM10, NO₂, ozone, CO, and TVOC sensors are interpreted as outdoor measurements. Multiple exterior values use deterministic aggregation: a mean for primary climate values and the conservative maximum for pollutants. Legacy explicit outdoor fields remain runtime fallbacks only when no valid exterior Area source exists.

## Area Health

Area Health is separate optional feature for smoke, gas, moisture alarms, safety, and problem binary sensors. It replaces no Area Climate measurement. Area Climate performs no generic binary environmental aggregation. Imported legacy Magic Areas `health`/German “Umweltsensoren” configuration is discarded rather than silently enabling Area Health.

## Scientific and operational basis

Adaptive Areas combines published formulas and guidance with clearly labelled operational policy. It does not claim compliance with [ANSI/ASHRAE Standard 55](https://www.ashrae.org/technical-resources/bookstore/standard-55-thermal-environmental-conditions-for-human-occupancy) or [ISO 7730:2025](https://www.iso.org/standard/85803.html): ordinary rooms usually lack air speed, mean radiant temperature, clothing, and metabolic-rate inputs. Boundaries marked `Adaptive Areas operational` are deterministic automation rules, not health limits.

### Primary Area climate sensors

Adaptive Areas does not average every temperature and humidity sensor in an Area for thermal assessment. Select one representative temperature sensor and one representative relative-humidity sensor under **Area Climate**. An explicit selection is authoritative even when its device class is missing or incorrect. When no source is selected, exactly one same-Area sensor with the matching official Home Assistant device class is used automatically; ambiguous discovery remains unknown. Area Aggregate Temperature and Humidity sensors remain separate statistical features and are never substituted.

If neither an explicit source nor one unambiguous device-class source is available, the measurement stays unknown. Adaptive Areas never uses entity-name or friendly-name heuristics, climate attributes, or an Aggregate as a fallback. Temperature-only category assessment can continue at `basic` input quality; calculations requiring relative humidity remain unknown. CO₂ and other independently discovered air-quality measurements continue to work.

One point measurement is not necessarily the spatial mean of a room. Position, mounting height, sunlight, exterior walls, heat sources, and local airflow influence readings. A representative sensor should generally avoid direct sunlight, radiators, supply/exhaust jets, exterior-door drafts, and appliance heat. Adaptive Areas does not validate placement.

### Thermal and moisture calculations

Room categories select purpose-based thermal reference profiles: living/sedentary, sleeping/rest, hygiene/wet, active domestic, circulation/transient, service/storage, and unconditioned. [German Environment Agency room-temperature references](https://www.umweltbundesamt.de/umwelttipps-fuer-den-alltag/richtiges-heizen-schuetzt-das-klima-den-geldbeutel) inform these profiles; category offsets and hysteresis are Adaptive Areas operational policy. Service/storage and unconditioned Areas report comfort as `not_applicable` rather than applying residential comfort language.

Indoor comfort is split into `temperature_state`, `humidity_comfort_state`, and transparent `combined_comfort`. High, very low, or low humidity changes the combined result even when temperature is comfortable. The legacy `comfort` attribute remains a temperature-state compatibility alias. These are operational categories, not a comprehensive thermal-comfort model. Temperature plus relative humidity also publishes:

* dew point and saturation vapour pressure using the [improved Magnus-form research](https://doi.org/10.1175/1520-0450(1996)035%3C0601:IMFAOS%3E2.0.CO;2);
* absolute humidity in g/m³;
* humidity ratio in g water/kg dry air;
* moist-air enthalpy in kJ/kg dry air, using standard-pressure perfect-gas approximations documented by the [ASHRAE Handbook psychrometrics chapter](https://handbook.ashrae.org/Handbooks/F25/SI/F25_Ch01/F25_Ch01_si.aspx);
* [Environment and Climate Change Canada's Humidex formula](https://climate.weather.gc.ca/glossary_e.html) only as a warm-stress index from 26 °C, never as a universal comfort temperature.

Outdoor temperature plus humidity enables humidity-ratio and enthalpy comparisons. Drying advice uses moisture content, not relative humidity alone. Passive cooling requires a useful temperature difference, an enthalpy advantage when humidity is known, and outdoor air quality that is not clearly worse.

### Humidity and mould-risk indicator

Room humidity from 60–65% is observed as elevated. At 65% a persistence timer starts; after the configured operational duration it recommends ventilation. Values above 70% are weighted more strongly. Values above 75%, or a rise of at least 15 percentage points within five minutes, require ventilation immediately. Other short peaks do not automatically request ventilation. Mould risk becomes `elevated` after six hours and `high` after 24 hours; both durations are Adaptive Areas operational policy, not biological limits.

With an optional measured cool-surface temperature, Adaptive Areas estimates surface relative humidity and uses the [German Environment Agency's 80% surface-RH guidance](https://www.umweltbundesamt.de/system/files/medien/4031/publikationen/240513_uba_fb_schimmelleitfaden_0.pdf); quality is `surface_based`. Without it, the 65% room-RH persistence proxy is labelled `room_air_estimate`. This is a conservative risk indicator, not mould detection.

A future mould model should incorporate surface moisture, surface temperature, exposure duration, and drying phases dynamically. Current fixed persistence durations deliberately remain transparent operational logic.

## Air quality

### Air-quality and pollutant sensor requirements

Adaptive Areas uses the `device_class` provided by Home Assistant to determine the type of an air-quality or pollutant sensor. For automatic pollutant evaluation, the Home Assistant entity must provide a matching sensor device class and, where required for that class, a supported unit of measurement.

Supported device classes include `aqi`, `carbon_dioxide`, `carbon_monoxide`, `nitrogen_dioxide`, `ozone`, `pm1`, `pm25`, `pm10`, `volatile_organic_compounds`, and `volatile_organic_compounds_parts`. Adaptive Areas does not infer a sensor type from its entity ID, display name, source integration, manufacturer, or attribution.

If a source integration does not provide a suitable device class or a unit supported by that device class, correct the source entity or provide a correctly configured Home Assistant sensor entity. Adaptive Areas does not add missing source metadata or offer parallel pollutant type and unit overrides. See the official [Home Assistant sensor entity documentation](https://developers.home-assistant.io/docs/core/entity/sensor/) for supported device classes and units.

Once a source is identified by its device class, Adaptive Areas may convert a compatible published unit internally to the reference unit required by its evaluation matrix. Gas ratios for CO, NO₂, and ozone use the conventional reference conversion at 25 °C and 101.325 kPa. Generic AQI and VOC-parts scales remain exposed but unclassified, so they do not affect `pollutant_state`.

CO₂ uses the German Environment Agency categories: up to 1000 ppm hygienically unremarkable, 1000–2000 ppm elevated with ventilation recommended, and above 2000 ppm hygienically unacceptable with urgent ventilation. The 850 ppm clearing value is an Adaptive Areas operational hysteresis threshold.

PM2.5, PM10, CO, and NO₂ use the [WHO 2021 24-hour guideline values](https://www.who.int/publications/i/item/9789240034228): 15 µg/m³, 45 µg/m³, 4 mg/m³, and 25 µg/m³ respectively. Adaptive Areas calculates a true elapsed-time-weighted rolling 24-hour average. Classification remains `unknown`/`limited` until at least 18 hours are covered. Current values may still create provisional warnings. Only the first threshold is the scientific guideline; higher severities are `adaptive_areas_operational`. Each pollutant assessment publishes guideline, period, exceedance, severity basis, coverage, and quality metadata.

NO₂ additionally has a rolling one-hour assessment. [German Environment Agency indoor precaution values](https://www.umweltbundesamt.de/themen/luft/luftschadstoffe-im-ueberblick/stickstoffoxide/stickstoffdioxid-gesundheitliche-bedeutung-von) are 80 µg/m³ (Richtwert I) and 250 µg/m³ (Richtwert II); the more critical valid short- or long-term result wins. Ozone uses the WHO eight-hour guideline of 100 µg/m³ after at least six hours of coverage, with higher levels classified by Adaptive Areas operational policy.

TVOC mass concentration is only a [German AIR precaution indicator](https://www.umweltbundesamt.de/en/topics/health/commissions-working-groups/german-committee-on-indoor-air-guide-values): values above 950 µg/m³ are marked elevated, not toxicological. Generic VOC ppb and AQI values are exposed as `unsupported_scale` and are not mapped to invented universal health bands.

`air_exchange_suitability` compares indoor and exterior PM2.5, PM10, NO₂, and ozone as `favorable`, `acceptable`, `unfavorable`, `hazardous`, or `unknown`. Cleaner outdoor air supports exchange. Worse or hazardous outdoor air keeps windows closed and blocks passive cooling; configured mechanical ventilation remains available. Unknown outdoor pollution never becomes “good”.

## Recommendations, context, and fan roles

Indoor Area Climate sensor exposes independent temperature, humidity, combined comfort, mould, air-quality, ventilation, cooling, window, ventilation-fan, and circulation-fan results. `context` explains the dominant current decision in English or German; `reason_codes` supplies stable machine values. Dominance order is hazard, critical air quality, urgent ventilation, high mould risk, recommended ventilation, cooling, comfort, then unremarkable state.

Window advice is `open`, `close`, `keep_closed`, or `none`. Automatic discovery uses window-class binary sensors; other openings must be selected explicitly. Area Climate publishes abstract ventilation and circulation requests but never stores or controls concrete `fan.*` entities. The Fan Groups feature owns actual fan membership and consumes Area Climate requests when both features are enabled.

## Room Usage

The optional **Cleaning Tracker** replaces the former daily Room Usage classifier while preserving its existing sensor and unique IDs. It uses the Area's established Adaptive Areas presence events; no separate presence detection is created.

For every regular Home Assistant Area, the tracker accumulates occupied time since the last cleaning. The value is persisted across Home Assistant restarts and config-entry reloads and is refreshed every minute while the Area remains occupied. Configure **Presence time until cleaning is due** in minutes per Area; the default is 480 minutes (8 hours).

The existing `sensor.adaptive_areas_room_usage_<area>` now reports a numeric Cleaning Score from 0 to 100%:

```text
min(100, cumulative_presence_seconds / (presence_minutes_to_due * 60) * 100)
```

`binary_sensor.adaptive_areas_room_usage_<area>_cleaning_due` turns on when the accumulated presence reaches the configured threshold.

The following services accept one or more Home Assistant Area IDs:

- `adaptive_areas.mark_cleaned` resets the score to 0% and records `last_cleaned`.
- `adaptive_areas.reset` completely clears the saved tracker state, including `last_cleaned`.
- `adaptive_areas.set_score` sets a value from 0 to 100% and recalculates the underlying occupied seconds so normal accumulation can continue.

Manual Override remains limited to Light Groups. Area Climate and Room Usage do not extend it.
