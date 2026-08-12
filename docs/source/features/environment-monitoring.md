# Environment Monitoring

Environment Monitoring creates one Environment sensor for an eligible regular area. It discovers supported Area sensors after Adaptive Areas' normal include/exclude and entity-category filtering, then evaluates only the information that is actually available.

Adaptive Areas never assumes unavailable environmental information is good. For example, a room with temperature but no CO₂, VOC, or AQI sensor still receives a comfort assessment, while ventilation remains `unknown`.

## Assessments and recommendations

The sensor summarizes four independent results:

* Comfort: `cold`, `cool`, `comfortable`, `warm`, `hot`, `very_hot`, or `unknown`.
* Humidity: `very_dry`, `dry`, `normal`, `elevated`, `high`, `very_high`, or `unknown`.
* Ventilation: `not_required`, `recommended`, `required`, `urgent`, `ventilating`, or `unknown`.
* Cooling: `not_required`, `passive_recommended`, `active_recommended`, or `unknown`.

The `decision_context` attribute explains active recommendations with privacy-safe reasons such as high CO₂, prolonged humidity, a rapid humidity rise, or cooler outdoor air. These values are translated in the Home Assistant UI while their stable machine values remain suitable for automations.

CO₂ is the strongest ventilation indicator. The defaults recommend ventilation above 1000 ppm, require it above 1400 ppm, and mark it urgent above 2000 ppm. A recommendation that has started does not clear until CO₂ falls below 850 ppm. VOC, AQI, prolonged humidity above 65%, humidity above 75%, and a rapid humidity rise can contribute when available. These defaults are Adaptive Areas product rules, not universal medical limits.

The default comfort band is 20–24 °C. Passive cooling is recommended only when the room is above the configured maximum and outdoor air is at least 2 K cooler. If outdoor temperature is unavailable, Adaptive Areas does not claim that opening a window will cool the room. Air-quality and humidity needs take priority over thermal efficiency.

Window advice is `open`, `close`, `keep_closed`, or `none`. Automatic discovery uses window-class binary sensors only; doors and other openings must be selected explicitly. An open window changes an active ventilation assessment to `ventilating` instead of repeatedly recommending that it be opened.

## Fan roles

Environment Monitoring distinguishes ventilation fans from circulation fans:

* Ventilation fans exchange indoor and outdoor air and may respond to air-quality or humidity needs.
* Circulation fans move indoor air and may respond to thermal comfort only while the Area is occupied.

Home Assistant fan entities do not reliably describe this distinction. Configure ventilation fans explicitly. Unclassified Area fans default to the safer circulation role and are never claimed to reduce CO₂, VOC, or humidity through air exchange. Fans can also be excluded from Environment requests while remaining in the passive fan group.

The Environment Engine only publishes requests. It never calls fan services directly. Existing Fan Control consumes those requests only when Fan Control is already enabled; enabling Environment Monitoring never silently enables device automation.
