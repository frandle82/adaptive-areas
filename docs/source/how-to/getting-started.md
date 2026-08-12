# Getting Started

You’ve already [installed](installation.md) Adaptive Areas—awesome! 🎉
Now let’s walk through how to configure your home with Adaptive Areas.

## Migrating from Magic Areas

Keep Magic Areas installed while importing its configuration. Go to
**Settings > Devices & Services > Integrations**, click **+ Add Integration**, and
select **Adaptive Areas**. Existing entries appear at the top of the area list as
**(Import Magic Areas) _Area name_**.

Select each entry you want to import. Adaptive Areas copies its data and options,
migrates legacy light-group settings, and updates references to entities created
by the old integration. The original Magic Areas entry is not changed. Review the
imported areas before disabling or removing Magic Areas.

## 🏠 Step 1: Define Your Areas

If you haven’t paid much attention to Home Assistant’s **Area Registry** before, now is the time!

Go to **Settings > Areas** and make sure every room or zone in your home is represented as an area. Since you're here, if your home is multi-story, configure the each Floor and assign areas to them.

Once you’ve created your areas, go to **Settings > Devices & Services > Integrations**, click **+ Add Integration**, search for **Adaptive Areas**, and create an Adaptive Area for each of your defined areas.

## ⚙️ Step 2: Configure Each Adaptive Area

After creating an Adaptive Area, go back to the **Integrations** page, find the Adaptive Areas entry for that area, and click **Configure**.

Supported user-facing options are available in the UI, and every setting includes a helpful description.

!!! question "Struggling to understand how a setting works?"
    💬 Ask for help in [GitHub Discussions](https://github.com/frandle82/adaptive-areas/discussions).

## 📥 Step 3: Include or Exclude Entities

Adaptive Areas uses entities assigned to areas in Home Assistant to determine presence and apply features.

However, not all entities can be assigned to areas (e.g., those without a `unique_id`). No worries! You can:

- Use the `Include Entities` setting to manually assign unsupported entities to your Adaptive Area.
- Use the `Exclude Entities` setting to remove entities from *all* Adaptive Areas features (useful if something is incorrectly triggering presence or behavior).

!!! note
    Includes/excludes apply globally across all features. Feature-specific exclusions are not currently supported.

## ✨ Step 4: Enable Features

Adaptive Areas includes many powerful [features](../features/index.md)—from presence-based lighting to climate control and media routing.

After the basic configuration, you’ll be prompted to select which features you want to enable for the area. The next screens will let you customize them in detail. Each setting includes descriptions to help you choose what fits best.

## 🛠️ Something’s Not Right?

No worries! Try the following:

- Visit our [Troubleshooting](troubleshooting.md) guide
- Ask a question in [GitHub Discussions](https://github.com/frandle82/adaptive-areas/discussions)
- Or [open an issue](https://github.com/frandle82/adaptive-areas/issues) on GitHub

---

Now go forth and bring your house to life—with Adaptive Areas ✨
