# 🌡️ Climate Control

The **Climate Control** feature allows you to **map area states to climate device presets** automatically.
Instead of manually adjusting HVAC modes, Adaptive Areas ensures your climate follows the rhythm of your home’s activity.

When configuring Climate Control, you will first be asked to **select a climate entity**. Adaptive Areas will then pull the available presets from that device for mapping.

!!! tip
    🧠 Climate control is best used in **meta-areas** such as *Interior* or *Floor* meta-areas.
    Meta-areas’ secondary states (such as `sleep` 🛌) are calculated from child areas.
    You can configure the secondary state calculation method directly in the UI.

## ⚙️ Configuration Options

| Option                     | Type          | Default | Description |
|----------------------------|---------------|---------|-------------|
| **Climate Entity**         | `entity_id`   | `None`  | The climate device to control. |
| **Preset (Clear)**         | `string`      | Blank   | Preset to apply when the area becomes `clear` (e.g., `away`, `eco`). |
| **Preset (Occupied)**      | `string`      | Blank   | Preset to apply when the area becomes `occupied` (e.g., `home`, `comfort`). |
| **Preset (Extended)**      | `string`      | Blank   | Preset to apply when the area reaches `extended` occupancy. |
| **Preset (Sleep)**         | `string`      | Blank   | Preset to apply when the area enters the `sleep` state. |
| **Occupied preset delay**  | `int (minutes)` | `10`  | Minimum continuous occupancy before applying the occupied preset. |

!!! warning
    If you leave a preset mapping blank, Adaptive Areas will **not change the climate** when that state is active.
    This is useful if you want the system to wait until an `extended` state ⏳ before adjusting the climate.

## 🚀 How It Works

Whenever an area’s state changes (either **primary**: `occupied`/`clear`, or **secondary**: `sleep` / `dark` / `extended`), Adaptive Areas automatically applies the mapped preset to the configured climate device.

## 🧠 Usage Examples

### 🛌 Lower temperature at night
Map the `sleep` state to a cooler preset like `sleep` or `eco`.

- **Why**: Many people sleep better at lower temperatures.
- **How**: When the meta-area enters the `sleep` state, Adaptive Areas sets the climate to your `sleep` preset automatically.

### 🌅 Resume comfort in the morning
Map the `occupied` state to a `home` or `comfort` preset.

- **Why**: As the home becomes active in the morning, you want a warmer or cooler preset for comfort.
- **How**: As soon as presence is detected, Adaptive Areas switches the climate back to the desired preset.

### ⏳ Delay climate change until extended occupancy
Leave the `occupied` state preset blank, but set a preset for `extended`.

- **Why**: Avoid premature heating/cooling for brief visits in areas like a study or guest room.
- **How**: The preset only changes after the area has been occupied for an extended period.

### 🌇 Reduce energy use when no one’s home
Map the `clear` state to an energy-saving preset like `away` or `eco`.

- **Why**: No one's home, no need to run HVAC at full blast.
- **How**: When the entire meta-area becomes `clear`, Adaptive Areas switches the climate system to a lower-energy mode.

!!! warning
    ✅ Make sure your climate devices support the required presets (`home`, `away`, `eco`, `sleep`, etc.),
    or customize them according to your climate integration.
