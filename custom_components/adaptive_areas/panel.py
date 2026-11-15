"""Sidebar registration for the read-only Adaptive Areas dashboard."""

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.frontend import async_panel_exists
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.websocket import async_register_websocket_commands

_PANEL_PATH = "adaptive-areas"
_STATIC_PATH = "/adaptive_areas_panel"


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register static assets, WebSocket commands, and the admin-only panel once."""
    async_register_websocket_commands(hass)
    # Frontend is part of normal HA, but is intentionally absent in backend-only tests.
    if "frontend" not in hass.config.components:
        return
    if async_panel_exists(hass, _PANEL_PATH):
        return
    asset_path = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_STATIC_PATH, str(asset_path), cache_headers=False)]
    )
    await panel_custom.async_register_panel(
        hass=hass,
        frontend_url_path=_PANEL_PATH,
        webcomponent_name="adaptive-areas-panel",
        sidebar_title="Adaptive Areas",
        sidebar_icon="mdi:floor-plan",
        module_url=f"{_STATIC_PATH}/adaptive-areas-panel.js?v=1.6.18",
        require_admin=True,
    )
