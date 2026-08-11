# Troubleshooting

If you’ve followed our [Installation](installation.md) and [Getting Started](getting-started.md) guides, things should be smooth sailing 🛶—but if something’s acting weird, this page will help you debug it.

## Diagnostics and troubleshooting

### Download diagnostics

In Home Assistant, open **Settings → Devices & services → Adaptive Areas**. Open
the relevant config entry's menu and select **Download diagnostics**.

The downloaded file contains a privacy-safe configuration summary, current area
states, a presence-source summary, enabled feature status, generated-entity
counts, active Repair findings, and the recent automated Decision Trace. Entity
object IDs, person and device-tracker identifiers, BLE identifiers, hardware
unique IDs, exact locations, media content, tokens, and credentials are not
exported. Entity references are reduced to structural details such as domain,
device class, availability, and active status.

Device diagnostics are also available because every Adaptive Areas device maps
to exactly one Adaptive Areas config entry. They contain the same redacted entry
information.

### Repairs

Adaptive Areas creates native Home Assistant Repair issues for persistent,
actionable configuration problems—for example, when a configured Home Assistant
Area or floor was deleted, or when an explicitly selected entity no longer
exists. An entity that is merely `unavailable` or `unknown` is not treated as
missing.

Open **Settings → System → Repairs** to review an issue. Repair issues do not
silently delete or rewrite configuration. Reconfigure or remove the affected
Adaptive Areas entry after reviewing its automations. The issue disappears
automatically after the corrected entry is loaded again.

### System Health

Home Assistant's **System information** view includes a concise Adaptive Areas
summary: integration version, configured and loaded entry counts, regular and
meta-area counts, classifications, active Repair count, and the number of legacy
Magic Areas entries detected. It deliberately contains no area names, entity
IDs, device IDs, or location information.

### Decision Trace

Diagnostics include the oldest-to-newest history of up to 20 recent presence
transitions and automatic decisions for each loaded area. Entries explain why an
action executed, was skipped, or failed using stable reason codes and target
counts without storing target entity IDs or service payloads.

The trace is lightweight and kept only in memory. It is not written to disk, it
resets when the config entry is reloaded or Home Assistant restarts, and tracing
never changes automation behavior.

## 🧪 Step 1: Enable Logging

The first step to troubleshooting is **turning on logging** so you can see what’s going on behind the scenes.

!!! tip
    Use `info` level for general debugging. Use `debug` only as a last resort — it’s very verbose.

### 🔍 Basic Logging Setup

Add this to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.adaptive_areas: info
```

### 🎯 Debug a Specific Feature

If you’re debugging a specific platform (like `media_player` for [Media Player Groups](../features/media-player-groups.md) or [Area-Aware Media Player](../features/area-aware-media-player.md)), you can target that platform directly:

```yaml
logger:
  default: warning
  logs:
    custom_components.adaptive_areas.media_player: debug
```

### 🧱 Debug Area Initialization / Load Issues

To debug area loading and avoid noisy output from other features, you can enable debug globally for `adaptive_areas` while silencing the individual platforms:

```yaml
logger:
  default: warn
  logs:
    custom_components.adaptive_areas: debug
    custom_components.adaptive_areas.base: warn
    custom_components.adaptive_areas.binary_sensor: warn
    custom_components.adaptive_areas.light: warn
    custom_components.adaptive_areas.fan: warn
    custom_components.adaptive_areas.media_player: warn
    custom_components.adaptive_areas.sensor: warn
    custom_components.adaptive_areas.switch: warn
    custom_components.adaptive_areas.cover: warn
    custom_components.adaptive_areas.threshold: warn
    custom_components.adaptive_areas.config_flow: warn
```

Once enabled, restart Home Assistant and check the **Logs** section under **Developer Tools**. Most errors are self-explanatory.

## ❗ Common Issues

### 🚫 Entity Not Being Added to an Area

If an entity doesn’t seem to be included in an Adaptive Area:

1. Go to **Developer Tools > States** or use the **Entity Filter** menu.
2. Check that the entity:
    - ✅ Belongs to a [supported platform](../concepts/presence-sensing.md/#supported-presence-sources)
    - ✅ (If it’s a `binary_sensor`) Has a `device_class` that is [supported for presence sensing](../concepts/presence-sensing.md/#default-binary_sensor-device-classes)
    - ✅ Is actually assigned to an area in Home Assistant

If any of the above isn’t true, the entity may not be recognized by Adaptive Areas. Use `Include Entities` in the configuration to override it if needed.

## 🆘 Still Stuck?

No worries! You can:

- Open a [GitHub issue](https://github.com/frandle82/adaptive-areas/issues) with:
    - A **clear description** of your setup and what’s going wrong
    - A **log excerpt** showing the problem (please format it!)
- Ask in [GitHub Discussions](https://github.com/frandle82/adaptive-areas/discussions) for help from other Adaptive Areas users

We’re happy to help you get everything working! 💫
