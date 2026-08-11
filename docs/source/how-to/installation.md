# Installation

Adaptive Areas can be installed in two ways: through [HACS](https://hacs.xyz) (recommended), or manually.

## 🚀 Installing via HACS (Recommended)

Download and install through [HACS (Home Assistant Community Store)](https://hacs.xyz/):

[![Open your Home Assistant instance and add the Adaptive Areas repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=frandle82&repository=adaptive-areas&category=integration)

### Don't like clicking links? No problem!

Adaptive Areas is installed as a custom HACS repository. Use the button above, or add `https://github.com/frandle82/adaptive-areas` as an Integration repository in HACS. Then:

1. Open HACS in your Home Assistant interface.
2. Go to **Integrations**.
3. Click the **+ Explore & Download Repositories** button.
4. Search for `Adaptive Areas`.
5. Click **Download** to install.

Once downloaded and installed, restart Home Assistant.

## 🛠️ Manual Installation

Prefer to install manually? Here's how:

1. Download the `adaptive_areas` integration folder from the [GitHub repository](https://github.com/frandle82/adaptive-areas).
2. Copy the entire `adaptive_areas` folder into your Home Assistant's `custom_components/` directory:

```
<config>/custom_components/adaptive_areas
```

3. Restart Home Assistant.

## ⚙️ Setting Up Adaptive Areas

Once installed, setup is done entirely through the **Integrations UI**:

1. Go to **Settings > Devices & Services > Integrations**
2. Click **+ Add Integration**
3. Search for `Adaptive Areas`
4. Select the integration, choose an area to configure, and submit

Adaptive Areas will now appear on your **Integrations** page. You can click **Configure** at any time to adjust its options. See each [feature](../features/index.md) for information on the configuration options for each.

## 🐛 Enabling Debug Logs (Optional)

Having trouble or want to dive deeper? You can enable debug logs by adding the following to your `configuration.yaml`:
```yaml
logger:
  default: warning
  logs:
    custom_components.adaptive_areas: debug
```

Then restart Home Assistant. Debug messages will now appear in your logs.

## ✅ What’s Next?
Once Adaptive Areas is installed and running, check out the [Getting Started](getting-started.md) guide to learn how to make your first area magical and our [Implementation Ideas](library/implementation-ideas-for-every-room.md) to learn how to make every other area in your home just as magical!
