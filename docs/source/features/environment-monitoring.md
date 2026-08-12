# Environment Monitoring and Room Usage

Environment Monitoring creates one Environment sensor for an eligible regular area. It evaluates only Area entities that remain after Adaptive Areas' normal include/exclude and entity-category filtering. Missing data stays `unknown`; it is never interpreted as healthy.

Room Usage is a separate option under **Basic area options**. It is disabled by default and can create the same Environment sensor without enabling Environment Monitoring. It uses only the Area's existing presence transitions. It does not discover more people, store movement history, or control a vacuum.

## Scientific and technical basis

Adaptive Areas uses published formulae and documented operational policies, not a universal environmental score. [ANSI/ASHRAE Standard 55](https://www.ashrae.org/technical-resources/bookstore/standard-55-thermal-environmental-conditions-for-human-occupancy) and [ISO 7730:2025](https://www.iso.org/standard/85803.html) inform the limitations described below; the integration does not claim compliance with either standard. The centralized policies and pollutant matrix in `helpers/environment.py` identify each boundary and its basis. Thresholds labelled “Adaptive Areas operational” are deterministic automation rules, not medical limits.

## Thermal comfort

With temperature only, Adaptive Areas applies the configured comfort band and marks the result confidence as `limited`. With temperature and relative humidity it also publishes:

* dew point, calculated with the Magnus approximation;
* apparent temperature, using the Canadian humidex formula at warm temperatures;
* confidence `full`.

The result is a practical indoor indicator, not an ASHRAE 55 or ISO 7730 PMV/PPD calculation. Those standards need inputs such as air speed, radiant temperature, clothing and metabolic rate that ordinary Home Assistant rooms generally do not provide. The implementation is informed by the open-source [Thermal Comfort integration](https://github.com/dolezsa/thermal_comfort), but has no added runtime dependency.

## Air quality matrix

The worst available pollutant determines `air_quality`: `good`, `degraded`, `poor`, `critical`, or `unknown`.

| Input | Good through | Degraded through | Poor through | Evaluation basis |
| --- | ---: | ---: | ---: | --- |
| CO₂ | 1000 ppm | 1400 ppm | 2000 ppm | German Environment Agency indoor-air bands |
| PM2.5 | 15 µg/m³ | 37.5 µg/m³ | 75 µg/m³ | WHO 24-hour guideline, then operational multiples |
| PM10 | 45 µg/m³ | 75 µg/m³ | 150 µg/m³ | WHO 24-hour guideline, then operational bands |
| CO | 4 mg/m³ | 7 mg/m³ | 10 mg/m³ | WHO 24-hour guideline and operational bands |
| NO₂ | 25 µg/m³ | 50 µg/m³ | 100 µg/m³ | WHO 24-hour guideline and operational multiples |
| AQI | 50 | 100 | 150 | Operational AQI bands; the sensor's own AQI system applies |
| VOC | 250 µg/m³ | 500 µg/m³ | 1000 µg/m³ | Adaptive Areas operational bands for mass-concentration sensors |
| VOC (parts) | 220 ppb | 660 ppb | 2200 ppb | Adaptive Areas operational bands for parts-per-billion sensors |

PM2.5, PM10, CO and NO₂ use the mean of observed samples retained for up to 24 hours. This is not a regulatory monitor: sampling frequency, calibration and sensor placement still matter. Units must match the matrix; unsupported or unavailable readings are ignored. The source values are the [WHO 2021 air quality guidelines](https://www.who.int/publications/i/item/9789240034228/) and the German Environment Agency's [indoor CO₂ guidance](https://www.umweltbundesamt.de/system/files/medien/pdfs/kohlendioxid_2008.pdf).

Air-quality severity and ventilation are intentionally separate. CO₂ and persistent or rapidly rising humidity can request ventilation. PM, CO, NO₂, AQI or VOC can make air quality poor or critical, but Adaptive Areas does not claim that opening a window or running an extraction fan is always the safe remedy for those pollutants.

## Humidity and mould risk

Humidity is classified independently. Values above 65% start a persistence timer; very high humidity and a rapid rise can act immediately. The mould-risk indicator needs temperature, humidity and dew point:

* `low`: no sustained warning signal;
* `elevated`: high moisture for six hours, or humidity above 75%;
* `high`: high moisture for 24 hours with high humidity or a small dew-point depression;
* `unknown`: required measurements are missing.

This is a conservative risk indicator, not mould detection and not a surface-temperature model. The thresholds reflect the German Environment Agency's advice that long-term indoor humidity should remain below roughly 65–70%: [Ventilation prevents mould](https://www.umweltbundesamt.de/themen/richtiges-lueften-beugt-schimmel-vor).

## Recommendations and context

The Environment sensor exposes independent comfort, humidity, mould risk, air quality, ventilation, cooling, window, ventilation-fan and circulation-fan results. `context` explains the dominant current decision in human-readable English or German. `reason_codes` preserves stable machine values for automations. The compatibility attribute `decision_context` currently mirrors those codes.

Priority is deterministic: an active Area Health warning, critical/poor air quality, urgent/required ventilation, high mould risk or persistent humidity, thermal discomfort, window advice, cleaning advice, then normal or partial-data status. This answers why ventilation or cleaning is recommended without exposing personal identifiers.

CO₂ ventilation starts above 1000 ppm, becomes required above 1400 ppm and urgent above 2000 ppm. Hysteresis keeps an active recommendation until CO₂ falls below 850 ppm. Passive cooling is recommended only when the room exceeds the configured maximum and outdoor air is at least the configured difference cooler. Air-quality and humidity needs outrank thermal efficiency.

Window advice is `open`, `close`, `keep_closed`, or `none`. Automatic discovery uses window-class binary sensors only; other openings must be selected explicitly.

## Room usage and cleaning

When opted in, daily usage is derived from occupied/clear transitions:

* `unused`: no occupancy today;
* `low`: less than 30 occupied minutes and fewer than two sessions;
* `normal`: at least 30 minutes or two sessions;
* `high`: at least two hours or four sessions.

While occupied, cleaning is `postpone`. When a highly used room clears, cleaning is `preferred`; otherwise it is `allowed`. The sensor also exposes current and daily occupied durations, session count and last-transition timestamps. Counters reset at the local day boundary and are in-memory only, so an integration reload starts a new observation period.

## Fan roles and Manual Override

Ventilation fans exchange indoor and outdoor air. Circulation fans only move indoor air and can respond to warm occupied rooms. Configure ventilation fans explicitly; unclassified Area fans use the circulation role.

The engine only publishes fan requests. Existing Fan Control consumes them only while Fan Control is enabled. Room Usage alone never changes Fan Control's established aggregate/setpoint behavior.

Manual Override remains limited to the existing Light Groups implementation. Environment Monitoring and Room Usage neither extend nor redesign it.
