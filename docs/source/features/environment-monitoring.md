# Area Evaluation and Room Usage

Area Evaluation is intrinsic to every regular indoor Area. It creates one **Area Evaluation** sensor while retaining the existing `sensor.adaptive_areas_environment_…` entity and unique ID for release-candidate compatibility. It uses configured primary indoor climate sensors and automatically discovered air-quality sensors after the normal include/exclude and entity-category filters. There is no feature toggle. Missing dimensions remain `unknown`; they are never interpreted as healthy.

Choose a room category and primary indoor temperature/humidity sensors under **Basic area options**. Configure optional outdoor, surface, window, and fan-role sources under **Area Evaluation**. The general exclusion list is authoritative for every source, including explicitly selected and automatically discovered exterior sources. The entity's `source_entities` attribute shows primary source identity and availability plus exact IDs and names used for other dimensions. Shareable diagnostics contain only modes, counts, and primary configured/available flags.

Room Usage remains a separate basic option, disabled by default. It uses only existing occupied/clear transitions, stores no movement history, and controls no cleaning device.

## Scientific and operational basis

Adaptive Areas combines published formulas and guidance with clearly labelled operational policy. It does not claim compliance with [ANSI/ASHRAE Standard 55](https://www.ashrae.org/technical-resources/bookstore/standard-55-thermal-environmental-conditions-for-human-occupancy) or [ISO 7730:2025](https://www.iso.org/standard/85803.html): ordinary rooms usually lack air speed, mean radiant temperature, clothing, and metabolic-rate inputs. Boundaries marked `Adaptive Areas operational` are deterministic automation rules, not health limits.

### Primary Area climate sensors

Adaptive Areas does not average every temperature and humidity sensor in an Area for thermal assessment. Select one representative indoor temperature sensor and one representative indoor relative-humidity sensor in **Basic area options**. Those deterministic sources form the operational indoor reference used by thermal, psychrometric, humidity, mould-risk, and cooling calculations. Area Aggregate Temperature and Humidity sensors remain separate statistical features and are never substituted.

If a primary source is unconfigured, excluded, unavailable, invalid, or deleted, its measurement stays unknown. Adaptive Areas does not fall back to another Area sensor, a climate attribute, or an Aggregate. Temperature-only category assessment can continue at `basic` input quality; calculations requiring relative humidity remain unknown. CO₂ and other independently discovered air-quality measurements continue to work.

One point measurement is not necessarily the spatial mean of a room. Position, mounting height, sunlight, exterior walls, heat sources, and local airflow influence readings. A representative sensor should generally avoid direct sunlight, radiators, supply/exhaust jets, exterior-door drafts, and appliance heat. Adaptive Areas does not validate placement.

### Thermal and moisture calculations

Room categories select purpose-based thermal reference profiles: living/sedentary, sleeping/rest, hygiene/wet, active domestic, circulation/transient, service/storage, and unconditioned. [German Environment Agency room-temperature references](https://www.umweltbundesamt.de/umwelttipps-fuer-den-alltag/richtiges-heizen-schuetzt-das-klima-den-geldbeutel) inform these profiles; category offsets and hysteresis are Adaptive Areas operational policy. Service/storage and unconditioned Areas report comfort as `not_applicable` rather than applying residential comfort language.

Temperature alone gives comfort quality `basic`. Temperature plus relative humidity gives `enhanced` and publishes:

* dew point and saturation vapour pressure using the [improved Magnus-form research](https://doi.org/10.1175/1520-0450(1996)035%3C0601:IMFAOS%3E2.0.CO;2);
* absolute humidity in g/m³;
* humidity ratio in g water/kg dry air;
* moist-air enthalpy in kJ/kg dry air, using standard-pressure perfect-gas approximations documented by the [ASHRAE Handbook psychrometrics chapter](https://handbook.ashrae.org/Handbooks/F25/SI/F25_Ch01/F25_Ch01_si.aspx);
* [Environment and Climate Change Canada's Humidex formula](https://climate.weather.gc.ca/glossary_e.html) only as a warm-stress index from 26 °C, never as a universal comfort temperature.

Outdoor temperature plus humidity enables humidity-ratio and enthalpy comparisons. Drying advice uses moisture content, not relative humidity alone. Passive cooling requires a useful temperature difference and, when humidity is known, an enthalpy advantage; cooler but moisture-heavy outdoor air is reported as a penalty.

### Humidity and mould-risk indicator

Room humidity above 65% starts a persistence signal. A short peak can request ventilation but does not immediately claim persistent mould risk. Risk becomes `elevated` after six hours and `high` after 24 hours.

With an optional measured cool-surface temperature, Adaptive Areas estimates surface relative humidity and uses the [German Environment Agency's 80% surface-RH guidance](https://www.umweltbundesamt.de/system/files/medien/4031/publikationen/240513_uba_fb_schimmelleitfaden_0.pdf); quality is `surface_based`. Without it, the 65% room-RH persistence proxy is labelled `room_air_estimate`. This is a conservative risk indicator, not mould detection.

## Air quality

CO₂ uses the German Environment Agency categories: up to 1000 ppm hygienically unremarkable, 1000–2000 ppm elevated with ventilation recommended, and above 2000 ppm hygienically unacceptable with urgent ventilation. The 850 ppm clearing value is an Adaptive Areas operational hysteresis threshold.

PM2.5, PM10, CO, and NO₂ use the [WHO 2021 24-hour guideline values](https://www.who.int/publications/i/item/9789240034228): 15 µg/m³, 45 µg/m³, 4 mg/m³, and 25 µg/m³ respectively. Adaptive Areas calculates a true elapsed-time-weighted rolling 24-hour average. Classification remains `unknown`/`limited` until at least 18 hours are covered. Higher severities are explicitly operational multiples, not extra WHO limits. Sensor calibration, placement, gaps, and sampling still matter.

TVOC mass concentration is only a [German AIR precaution indicator](https://www.umweltbundesamt.de/en/topics/health/commissions-working-groups/german-committee-on-indoor-air-guide-values): values above 950 µg/m³ are marked elevated, not toxicological. Generic VOC ppb and AQI values are exposed as `unsupported_scale` and are not mapped to invented universal health bands.

Air-quality severity remains separate from ventilation safety. Particles, CO, NO₂, AQI, or VOC can indicate degraded air without implying that outdoor ventilation is safe.

## Recommendations, context, and fan roles

The sensor exposes independent comfort, humidity, mould, air-quality, ventilation, cooling, window, ventilation-fan, circulation-fan, and cleaning results. `context` explains the dominant current decision in English or German; `reason_codes` supplies stable machine values. The RC compatibility attribute `decision_context` mirrors those codes.

Window advice is `open`, `close`, `keep_closed`, or `none`. Automatic discovery uses window-class binary sensors; other openings must be selected explicitly. Ventilation fans exchange indoor and outdoor air. Circulation fans only move indoor air. Area Evaluation publishes requests but never controls devices directly. Enabled Fan Control consumes them only after fan roles were explicitly configured; otherwise its established aggregate/setpoint behavior remains unchanged.

## Room usage and cleaning

Daily usage is `unused`, `low`, `normal`, or `high`, derived from occupied duration and session count. While occupied, cleaning is `postpone`; when a highly used room clears it is `preferred`; otherwise it is `allowed`. Counters are in memory and reset at the local day boundary or integration reload.

Manual Override remains limited to Light Groups. Area Evaluation and Room Usage do not extend it.
