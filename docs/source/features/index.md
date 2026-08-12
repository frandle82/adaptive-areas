# ✨ Feature List

Adaptive Areas can do a lot more than [presence sensing](../concepts/presence-sensing.md)! Below is a list of built-in features grouped by category.

## 🧠 Smart Groups
Entities grouped with presence-aware automation logic.

* 💡 [Light Groups](light-groups.md)
  Automatically controls lights per area using presence, darkness, sleep, and more.

* 🌀 [Fan Groups](fan-groups.md)
  Groups an area's fans and switches the group on or off from an aggregate sensor and area state.

* 🌡️ [Climate Control](climate-control.md)
  Maps area states to presets on one selected climate entity.

## 🧱 Simple Groups
Passive entity grouping for easier control.

* 🪟 [Cover Groups](cover-groups.md)
  Groups all `cover` entities (e.g. blinds, shades, garage doors) using [`cover.group`](https://www.home-assistant.io/integrations/cover.group/).

* 📺 [Media Player Groups](media-player-groups.md)
  Groups all `media_player` entities using [`media_player.group`](https://www.home-assistant.io/integrations/media_player.group/).


## 📊 Sensor Features
Sensor logic, tracking, and hazard detection.

* 🌿 [Area Evaluation](environment-monitoring.md)
  Intrinsically evaluates compatible indoor, outdoor, surface, and air-quality sources while keeping missing dimensions unknown and sources traceable.

* 📍 [BLE Tracker Sensors](ble-tracker-monitor.md)
  Adds support for BLE presence sensors (e.g., Bermuda, ESPresence, Room Assistant). Automatically maps tracked devices to areas.

* 📊 [Aggregation](aggregation.md)
  Creates aggregate `sensor` or `binary_sensor` for supported device classes (e.g., temperature, humidity, occupancy).

* 🚨 [Health Sensor](health-sensor.md)
  Creates a binary sensor per area to represent health problems (e.g., leaks, smoke, gas).

* 🐝 [Wasp in a Box](wasp-in-a-box.md)
  Adds intelligent presence logic using motion + door sensors to infer room occupancy even when closed.

## 🔊 Notifications

* 🔉 [Area-Aware Media Player](area-aware-media-player.md)
  A smart proxy `media_player` that plays TTS only in **occupied** areas. Great for room-aware voice alerts.

## ✋ Overrides

* ⏸️ [Presence Hold](presence-hold.md)
  Adds a manual `switch` to override presence state to `occupied`, with optional auto-reset timer.
