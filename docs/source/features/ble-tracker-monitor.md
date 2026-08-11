# 📡 Bluetooth & BLE Tracker Monitor

The **BLE Tracker Monitor** feature streamlines presence detection using **text-based BLE sensors**, such as those from [Bermuda](https://github.com/agittins/bermuda), [ESPresence](https://espresense.com/), or [Room Assistant](https://github.com/mKeRix/room-assistant).

Instead of manually creating [template binary sensors](https://www.home-assistant.io/integrations/template/) for each area, Adaptive Areas does it **automatically**.

## ⚙️ Configuration Options

| Option                 | Type               | Default | Description |
|------------------------|--------------------|---------|-------------|
| **BLE Tracker Entities** | `list (entity_id)` | `None`  | List of tracker entities to monitor. Each entity's state must contain the area **name**, **ID**, or **slug** (case-insensitive). |

## 🚀 How It Works

When you add a BLE tracker sensor to the area config, Adaptive Areas will:

1. **Create a binary presence sensor** automatically.
2. **Check its state** against the area’s name, ID, or slug (all compared in lowercase).
3. If there’s a match → the area is set to `occupied`.

✅ Any text-based sensor that reports an area name, ID, or slug can be used with this feature—not just BLE trackers.

## 🧠 Compatibility

This feature works with (and is tested or expected to work with):

- [Bermuda](https://github.com/agittins/bermuda) ✅
- [ESPresence](https://espresense.com/) ⚠️ Requires consistent naming
- [Room Assistant](https://github.com/mKeRix/room-assistant) ⚠️ Untested, but should work

💬 Have another system that reports presence as text? It’ll likely work too.

## ⚠️ Flappy Sensors? Read This

!!! warning
    BLE trackers can be **flappy**—reporting incorrect or outdated values momentarily.
    To prevent false `clear` states, add them to the **"keep only sensors"** list in your area config.

This way, their presence signal is only *added* to the logic and not used as the sole decider.

## 💡 Example Use Case

Imagine your Bermuda tracker reports `"living_room"` when it detects someone there.
Adaptive Areas will:

- Detect that `living_room` matches the area’s slug
- Set the Living Room area to `occupied`
- No templates needed!
