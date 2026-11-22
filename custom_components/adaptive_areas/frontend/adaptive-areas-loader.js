// Entry module of the Adaptive Areas panel. Only this panel imports the entity picker,
// so no other Home Assistant page loads it. The picker is loaded first, so the
// custom element exists before the panel renders. If the picker fails to load, the
// panel still opens and shows a notice where the entity selection is needed.
//
// Cache: the loader is registered with the integration version (`?v=<version>`). The
// modules it imports carry the same version, so an update always loads the JavaScript
// that belongs to the installed integration, even if the browser cached an older copy.
const version = new URL(import.meta.url).searchParams.get("v");
const query = version ? `?v=${encodeURIComponent(version)}` : "";
try {
  await import(`./aa-entity-picker.js${query}`);
} catch (error) {
  console.error("Adaptive Areas: entity picker could not be loaded", error);
}
await import(`./adaptive-areas-panel.js${query}`);
