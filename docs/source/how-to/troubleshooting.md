# Troubleshooting

If you’ve followed our [Installation](installation.md) and [Getting Started](getting-started.md) guides, things should be smooth sailing 🛶—but if something’s acting weird, this page will help you debug it.

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
