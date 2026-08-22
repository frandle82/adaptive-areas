# 🪟 Cover Groups and Area Cover Control

Enabling **Cover control** creates Home Assistant cover groups, separated by
device class, from the cover entities assigned to the Area. No group and no
automation are created when the feature is disabled; an Area without covers is
simply ignored.

Opening, closing, and shading are independent. All three automations are off by
default and must be enabled explicitly. Their configured triggers only request
a complete strategy evaluation—they never call a cover service directly.

## Opening and closing

Opening and closing can each react to a configured time, solar elevation,
brightness, a window transition, and the Area sleep state. Each strategy has
one optional permission entity (`binary_sensor`, `input_boolean`, or `switch`):
only `on` permits the action. The permission is a gate and is not an action
trigger.

An open or unknown window blocks automatic full closing. A blocked closing
request remains pending and is evaluated again when the window closes. Sleep
blocks automatic opening and can independently request closing.

## Shading

Shading can target all Area covers or a selected subset at one common position.
Partial positioning is sent only to covers that support it; unsupported covers
are skipped and reported in the decision diagnostics.

When **Area Climate** is enabled, shading consumes its hysteresis-stabilized
`heat_protection_demand` (`none`, `recommended`, `required`, or `unknown`). It
does not duplicate Area Climate's comfort calculation. If Area Climate is not
enabled, an explicit temperature entity and threshold can be configured. An
enabled but temporarily unknown Area Climate never silently switches to that
fallback.

Optional preventive shading uses the configured weather forecast temperature.
Missing forecasts are ignored without disabling normal thermal shading. An
optional brightness gate requires both a heat request (current or forecast) and
sufficient brightness. Raw fallback temperature and brightness use small fixed
hysteresis bands to avoid chatter.

Adaptive Areas deliberately does **not** implement window-relative solar
azimuth shading. For specialized facade, azimuth, elevation, slat, calendar, or
workday rules, Cover Control remains the more suitable integration.

## Manual operation and priorities

When manual-operation protection is enabled, an external cover movement pauses
all normal Area cover automation for the configured duration (15, 30, 60, 120,
or any valid number of minutes). Commands sent by Adaptive Areas itself are
tracked and do not start an override. Expiry causes a complete re-evaluation;
reload intentionally clears the temporary in-memory override.

The fixed priority is: unavailable/safety, manual override, open-window
protection, sleep/opening protection, closing, shading, opening, no action.
Manual override blocks normal movement; window protection is always applied to
full automatic closing before an actuator command is issued.

Each generated group exposes stable `cover_control` and `shading` attributes,
including action, target position, reason code, blocker, override expiry,
pending close, source, forecast state, brightness gate, and selected covers.
