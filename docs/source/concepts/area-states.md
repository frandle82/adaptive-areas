# 🏠 Area States

Adaptive Areas’ primary goal is to understand and track an **area’s presence state** — that is, whether someone is currently there. But it doesn’t stop there: Adaptive Areas also monitors a set of **secondary states** that enrich how automations behave in each area.

## 🟢 Presence State

For each configured area, Adaptive Areas does the following:

1. Scans the area for all associated entities.
2. Identifies which entities are valid **presence sensors** (see: [Presence Sensing](presence-sensing.md)).
3. Automatically creates a binary sensor entity:
   `binary_sensor.area_{area_id}`

This sensor reflects the **presence state** of the area:

- When any presence entity enters a **presence state** (`on`, `home`, `playing`), the area is considered **occupied** (`on`).
- Once all presence entities leave those states, Adaptive Areas waits for a short delay (configured via `Clear Timeout`) before marking the area as **clear** (`off`).

The same entity explains its state without creating extra sensors. Its attributes include `occupied_since`, `last_activity`, `last_cleared`, the absolute projected `clear_at`, configured/available/active source counts, active and last-active sources, `last_reason`, `last_transition`, and `active_states`. Timestamps use ISO 8601; `occupied_since` and `clear_at` are `null` while clear.

Semantic transitions are also published on the Home Assistant event bus as `adaptive_areas_area_event`. The payload contains `area_id`, `area_type`, `event_type`, `previous_states`, `states`, and a stable machine-readable `reason`. Event types are `occupied`, `cleared`, `dark_started`, `dark_ended`, `sleep_started`, `sleep_ended`, `extended_started`, `extended_ended`, `accented_started`, and `accented_ended`. Unchanged state evaluations do not emit an event.

!!! note
    Adaptive Areas automatically listen for area changes on entities.
    Changing an entity's area will cause Adaptive Areas to reload.


## 🌙 Secondary States

In addition to presence, Adaptive Areas tracks a set of **secondary states** that provide context about the area. These are based on specific configurable entities:

| Secondary State | Triggered by...             |
|-----------------|-----------------------------|
| `dark`/`bright` | Area Light Sensor           |
| `sleep`         | Sleep Entity                |
| `accented`      | Accent Entity               |
| `extended`      | Automatically, after area stays occupied for longer than `Extended Time` seconds |

Secondary states are optional but very useful — especially when layering automations or refining behavior per room.

## 💡 How Secondary States Are Used

Several Adaptive Areas features take advantage of these secondary states to fine-tune their behavior:

- **[Light Groups](../features/light-groups.md)**
  Use both presence and secondary states to determine which lights to turn on (e.g. only accent lighting when sleeping or dark).

- **[Climate Control](../features/climate-control.md)**
  Can trigger presets based on state (e.g. only change temperature after an area has been `occupied` for a while → `extended`).

- **[Area-Aware Media Player](../features/area-aware-media-player.md)**
  Filters notification playback based on secondary states, such as avoiding alerts in sleeping areas or playing TTS messages only when someone has been around for a while.

---

By layering **presence** with **secondary states**, Adaptive Areas gives you fine-grained, context-aware control over your automations — making each room react more intelligently to how it's being used.
