# 💡 Light Groups

The **Light Groups** feature in Adaptive Areas helps you organize and automate your lights intelligently and contextually—starting with automatic [light group](https://www.home-assistant.io/integrations/light.group/) creation and adding state-aware behavior for smarter automation.

## ✅ Basic Functionality

At its simplest, this feature automatically creates a Home Assistant light group for each area using all `light` entities assigned to it.

!!! warning
    No group will be created if there are no `light` entities in the area.

## 🌈 Available Light Groups

You can classify your lights into **predefined groups** for specific purposes:

- **Overhead Lights** – Main ceiling lights for general illumination.
- **Accent Lights** – Decorative or highlight lighting (e.g., under cabinets, wall sconces).
- **Task Lights** – Focused lights for workspaces, desks, or reading.
- **Sleep Lights** – Dim lighting suitable for nighttime or bedtime use.

Each of these groups—when populated—automatically gets a dedicated `light.group` in Home Assistant.
They can also be linked to an area's **secondary states** (e.g., `sleep`, `accented`, `extended`) for smarter automation.

!!! warning
    🧠 To enable automation, turn on the `Light Control ($Area)` switch created by Adaptive Areas.

## ⚙️ Configuration Options

| Option                              | Type             | Default      | Description                                                                                      |
|------------------------------------|-----------------|-------------|--------------------------------------------------------------------------------------------------|
| Overhead lights                     | entity list      | blank       | Lights assigned to this group.                                                                  |
| States which this group should be on (Overhead lights) | list | `occupied` | Area states that trigger this group.                                                           |
| When should we control this light? (Overhead lights) | multi-choice  | occupancy + state | `occupancy` triggers on clear → occupied; `state` triggers on secondary state changes.         |
| Sleep lights                        | entity list      | blank       | Lights assigned to this group.                                                                  |
| States which this group should be on (Sleep lights) | list | `occupied` | Area states that trigger this group.                                                           |
| When should we control this light? (Sleep lights) | multi-choice  | occupancy + state | Same behavior explanation as above.                                                            |
| Accent lights                       | entity list      | blank       | Lights assigned to this group.                                                                  |
| States which this group should be on (Accent lights) | list | `occupied` | Area states that trigger this group.                                                           |
| When should we control this light? (Accent lights) | multi-choice  | occupancy + state | Same behavior explanation as above.                                                            |
| Task lights                          | entity list      | blank       | Lights assigned to this group.                                                                  |
| States which this group should be on (Task lights) | list | `occupied` | Area states that trigger this group.                                                           |
| When should we control this light? (Task lights) | multi-choice  | occupancy + state | Same behavior explanation as above.                                                            |

!!! warning "💡 **Control Timing Notes:** "
    - **Occupancy only:** Light group reacts when entering the room (clear → occupied) but not if the area enters a secondary state while already occupied.
    - **State only:** Light group reacts when a secondary state changes but **not** when first entering the room.
    - **Both selected (default):** Reacts on room entry **and** secondary state changes.

## 🔁 Automatic Control

Adaptive Areas can automatically turn lights on or off based on:

- **Primary presence state**: `occupied` or `clear`
- **Secondary states**: `dark`, `extended`, `sleep`, etc.

### 🌒 The `dark` State

If the area's brightness is `dark` (from the illuminance sensor and the Light Lux limits; `unknown` never counts as dark):

- Lights turn on only when the area is both **occupied** _and_ **dark**.
- Otherwise, lights turn on anytime the area becomes occupied.

!!! note
    ✅ If the area becomes dark while already occupied, lights will turn on immediately.

#### Brightness Mode Matrix

The brightness mode of each group decides what an occupied Area does. Brightness is `dark`, `bright` or `unknown` (see [Area states](../concepts/area-states.md#secondary-states)). `unknown` is never treated as dark or bright.

| Mode | Area `occupied`, brightness `dark` | Area `occupied`, `bright` | Area `occupied`, `unknown` |
|------|------------------------------------|---------------------------|----------------------------|
| `ignore` | Turn on | Turn on | Turn on |
| `require_dark` | Turn on | Do nothing | Do nothing |
| `turn_off` | Turn on | Turn off | Turn on |
| `dark_on_bright_off` | Turn on | Turn off | Do nothing |

The vacancy OFF is the same in every mode: when the Area becomes `clear`, the ALL group turns the lights off.

!!! note
    Decided behaviour for `unknown`: `ignore` and `turn_off` switch on when occupied; `require_dark` and `dark_on_bright_off` do not switch on automatically. A sensor outage alone never sends a command. `unknown` is never treated as dark or bright.

    `dark_on_bright_off` and `require_dark` turn on only with a known `dark` reading. `turn_off` turns on when occupied unless the Area is `bright`. A missing brightness source is an incomplete configuration, reported by a repair.

### 💡 Automatically Turning Off Lights

When an area becomes `clear`, **all lights are turned off**, regardless of secondary state.
Disable **Light Control** to override.

## 🚀 How it Works

Light groups are tied to area states:

- **States:** Each group activates only when the area is in selected states (primary or secondary).
- **Control timing:** Decide if groups react on **occupancy**, **secondary state changes**, or both (recommended).

**Example:**
- `Sleep Lights` set to **occupancy only**: will turn on when you enter a bedroom at night, but not if `sleep` state activates while already inside.
- `Accent Lights` set to **state only**: will turn on whenever the `extended` state is activated, even if already inside.

## ✋ Manual Override and Ungrouped Lamps

- **Only group lamps are controlled automatically.** A lamp that is in no light group is never switched by Adaptive Areas, even when brightness limits are set. To keep automatic control for such a lamp, add it to an individual light group of the Area.
- **A manual change overrides the automation.** An override is an external intervention in the automatic control. It is not proof of a human action: a physical switch or another automation can set it too.
- **Commands of Adaptive Areas never set an override**, including the group's own commands, their forwarding to members, the automatic all-off at clear, initialisation, restoration after a restart or an outage, and a change that only reports the same state.
- **A change from outside** (switch, other automation, unknown origin) sets the override while the Area is occupied. An external ON is not read as a wish to switch off.
- **CLEAR ends the override**, as before. Brightness and blocker rules are unchanged.
- **Own commands are recognised by their Home Assistant context only.** Home Assistant keeps a call's context on an entity for 5 seconds. A device that reports its new state later (slow cloud or polled integrations, long transitions) reports it with a new context. Neither Home Assistant nor Adaptive Areas can then attribute it, so it counts as a change from outside and sets the override.
- **The decision trace shows where an override came from.** Its start is recorded with the change (`manual_on` or `manual_off`) and the origin class, which says only what Home Assistant's Context proves: a call under a user account (frontend, app, API or voice assistant), a derived context (for example an automation, script or scene), or not attributable (device report, physical switch, another integration, an automation with a time or sun trigger, or a device answer after the 5-second window). The panel's light diagnosis shows each group with its state, automatic control, manual override and last decision, so an override of the ALL group is not shown as one of the accent group. Its end is recorded with the cause (area clear or blocking state); a restored override is recorded at setup. Skipped light decisions show their reason, for example `manual_override`, `no_transition` or `already_on`.

## 🧠 Usage Examples

### 🛋️ TV ambiance with accent lights

- **Group:** Accent Lights
- **State:** `accented`
- **Trigger Mode:** `state` (media player, for exmaple)
- **Why:** Soft lighting during movie nights or relaxing evenings.

### 💤 Nighttime routine in bedrooms

- **Group:** Sleep Lights
- **State:** `sleep`
- **Trigger Mode:** `occupancy`
- **Why:** Turn on softer lights when entering the room at night.

## 🎚️ Brightness and Color Temperature

Adaptive Areas **does not control brightness or color temperature**.
Use integrations like:

- [Adaptive Lighting](https://github.com/basnijholt/adaptive-lighting/)
- [Circadian Lighting](https://github.com/claytonjn/hass-circadian_lighting)

These handle brightness/temperature better and are fully compatible with Adaptive Areas.
