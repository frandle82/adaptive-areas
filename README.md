[![Build Status][ci-status]][actions] [![GitHub Release][releases-shield]][releases] [![License][license-shield]](LICENSE)
[![HACS][hacs-shield]][hacs]

# Adaptive Areas for Home Assistant: Smarter areas, adaptive automation

Adaptive Areas is a Home Assistant custom integration that makes your smart home think for itself through rock-solid presence tracking — the foundation for a truly smart home.

Adaptive Areas knows when a room is occupied (and when it’s not) and reacts automatically. It turns Home Assistant’s Areas into dependable, presence-aware zones so your home feels alive without you lifting a finger. Instead of building dozens of manual automations, let Adaptive Areas control your lights, climate, and other devices so that they do just right thing, at the right time.

### What this means for you:

- 🏠 Areas that know when they’re occupied (and when they’re clear)
- 💡 Lights that only turn on when (and where) they’re needed
- 🌡 Climate that adapts to your presence and routines
- 🌀 Fans that respond automatically to heat, humidity, or CO₂
- 🎶 Media and alerts routed only to occupied spaces

Smart areas that just work, every time, out of the box. Fully customizable if you want it.

#### Download and install through [HACS (Home Assistant Community Store)](https://hacs.xyz/):

[![Open your Home Assistant instance and add the Adaptive Areas repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=frandle82&repository=adaptive-areas&category=integration)

## ✨ What Adaptive Areas Does

* Detects presence in each area using multiple sources (motion sensors, media players, device trackers, BLE beacons, and more).
* Creates smart groups (lights, fans, climate, media players) that respond to an area’s state automatically.
* Supports secondary states like dark, sleep, and extended for context-aware automation.
* Provides meta-areas (e.g., Interior, Exterior, Global, Floors) to coordinate multiple areas at once.
* Includes built-in, automation-like features: light control, fan groups, climate preset switching, and more
* Supports native Home Assistant diagnostics, Repairs, System Health, and a privacy-safe recent Decision Trace for troubleshooting.

> [!NOTE]
> Check out the [core concepts](docs/source/concepts/index.md) in the documentation.

## Features

### Presence
* **🕰️ Smart Presence Timeouts:** Each area has a configurable timeout for clearing presence after the last motion. If motion is detected again within the timeout, it resets — no abrupt shutoffs.
* **✋ Presence Hold:** Creates a switch to manually override presence in an area. Useful if sensors aren’t fully reliable yet or for guests.
* **🌿 Optional Area Evaluation:** Regular indoor Areas can evaluate category-aware thermal conditions, moisture, mould risk, air quality, ventilation, cooling, source provenance, and optional room usage. The feature is disabled by default, and missing dimensions remain unknown.
* **🕯️ Secondary States:** Define subtle room states for more nuanced automations:
    * `dark` / `bright`: Based on light sensors or sun
    * `sleep`: Tracked by any entity
    * `extended`: When a room has been occupied beyond a set time
    * `accented`: Track presence based on entertainment like media players
* **🏠 Meta-Areas and Hierarchies:** Set areas as **interior**, **exterior** and assign them to **floors**. Adaptive Areas will create meta-areas to track grouped presence (e.g., upstairs occupied). Presence logic and secondary states are inherited and calculated automatically.

### Smart Control
* **💡 Smart Light Groups**: Automatically groups your lights by purpose — overhead, task, accent, and sleep — and controls them based on presence state. Lights can be set to trigger only in the dark or after extended occupancy.
* **🌡️ Climate Control:** Map area states to climate device presets. For example: set your HVAC to `eco` when empty, and back to `comfort` when occupied or in sleep mode.
* **🧠 Wasp in a Box:** Reliable presence sensing that accounts for people entering/leaving rooms with doors. Combines motion and door/garage sensors to prevent lights from turning off while you’re still inside.
* **🔥 Fan Groups:** Auto-creates a `fan` group entity for each area and lets you control it using an aggregated value like temperature, humidity, or CO₂. Great for exhaust fans, ceiling fans, or air quality fans.
* **📶 Area-Aware Media Player:** Play media (like TTS alerts) only in rooms that are currently occupied. Forward notifications to the right areas — not empty ones.
* **🧮 Sensor Aggregates:** Aggregates all `sensor` and `binary_sensor` entities in the area by `device_class` and `unit_of_measurement`. Great for dashboards, alerts, and logic.
* **🚨 Health Sensor:** Auto-aggregated binary sensors for safety-related device classes:
    * `gas`, `smoke`, `moisture` (leaks), `problem`, `safety`
* **📡 BLE Tracker Integration:** Track text-based BLE sensors (like ESPresense, Bermuda, or Room Assistant) directly. Adaptive Areas will convert their values into usable presence sensors automatically.

> [!TIP]
> Learn more about all features in the [documentation](docs/source/features/index.md).

## 🧙 Demo / How can Adaptive Areas help me?

Check out the [Implementation Ideas](docs/source/how-to/library/implementation-ideas-for-every-room.md) documentation to see how you can apply Adaptive Areas to every room in your house.

## 🚀 Getting Started

Go to the documentation [Quick Start](docs/source/how-to/getting-started.md) for installation instructions.

📖 Visit the [documentation](docs/source/index.md) for complete guides, examples, and tips.

Enjoy smarter automations — and areas that finally understand you're still in the room ✨

## 🛠️ Problems/bugs, questions, feature requests?

Visit the [Troubleshooting](docs/source/how-to/troubleshooting.md) documentation for instructions on getting help.

## 🌐 Adaptive Areas in your language!

Adaptive Areas has full translation support, meaning even your entities will be translated and is available in the following languages:

Translations live in [`custom_components/adaptive_areas/translations`](custom_components/adaptive_areas/translations). Contributions are welcome through pull requests.

## Attribution

Adaptive Areas is based on [Magic Areas](https://github.com/jseidl/magic-areas). The original copyright and license terms remain available in [LICENSE](LICENSE).

## Development

Commit messages follow Conventional Commits. After staging the intended files, run `scripts/commit "type(scope): description"` to validate and commit them. Release drafts are maintained automatically; maintainers can create drafts, pre-releases, and final releases through the **Create Release** GitHub Actions workflow. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

[actions]: https://github.com/frandle82/adaptive-areas/actions
[hacs]: https://github.com/hacs/integration
[license-shield]: https://img.shields.io/github/license/frandle82/adaptive-areas.svg?style=for-the-badge
[releases-shield]: https://img.shields.io/github/release/frandle82/adaptive-areas.svg?style=for-the-badge
[releases]: https://github.com/frandle82/adaptive-areas/releases
[ci-status]: https://img.shields.io/github/actions/workflow/status/frandle82/adaptive-areas/validation.yaml?style=for-the-badge
[hacs-shield]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
