"""Real lifecycle tests for brightness-dependent light groups.

Uses the integration setup (init_integration), the real config entry reload and unload, and
the real repair evaluation of async_setup_entry. Initial states are set before the setup, so the
initial decision of the integration is what gets tested.
"""

from __future__ import annotations

from homeassistant.const import EVENT_CALL_SERVICE, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT,
    DOMAIN,
)
from custom_components.adaptive_areas.repairs import (
    ISSUE_BRIGHTNESS_CONFIGURATION,
    _issue_id,
)
from tests import test_light_coordination_regression as regression
from tests.helpers import init_integration
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_coordination_regression import (  # noqa: F401
    CALLS,
    LIGHT,
    LUX,
    _entry,
    _enable_group_control,
    probe_devices,
)

pytestmark = __import__("pytest").mark.usefixtures(
    "probe_devices", "record_service_calls"
)


@__import__("pytest").fixture(name="record_service_calls")
def _record_service_calls(hass):
    """Record light service calls once per test (the listener is not part of the measured set)."""
    hass.bus.async_listen(EVENT_CALL_SERVICE, regression._on_call)
    return hass


async def _setup(hass: HomeAssistant, *, lux: str, motion: str, entry=None):
    """Set the physical states, then run the real integration setup and enable group control."""
    hass.states.async_set(
        LUX,
        lux,
        {"unit_of_measurement": "lx"} if lux not in ("unavailable", "unknown") else {},
    )
    hass.states.async_set(regression.MOTION, motion)
    hass.states.async_set(regression.SLEEP, STATE_OFF)
    entry = entry or _entry()
    CALLS.clear()
    await init_integration(hass, [entry])
    await _enable_group_control(hass)
    await hass.async_block_till_done()
    return entry


def _group_on_calls() -> list[tuple[str, str]]:
    return [call for call in CALLS if call[0] == "turn_on" and "overhead" in call[1]]


async def test_setup_in_dark_with_occupancy_turns_on_once(hass) -> None:
    """Setup in DARK with occupancy sends exactly one ON for the overhead group."""
    await _setup(hass, lux="50", motion=STATE_ON)
    assert len(_group_on_calls()) == 1


async def test_setup_in_bright_with_occupancy_sends_no_on(hass) -> None:
    """Setup in BRIGHT with occupancy sends no ON for a require-dark group."""
    await _setup(hass, lux="150", motion=STATE_ON)
    assert _group_on_calls() == []


async def test_setup_with_unknown_brightness_sends_no_on(hass) -> None:
    """Setup with an unavailable brightness source keeps require-dark silent (UNKNOWN is not DARK)."""
    await _setup(hass, lux="unavailable", motion=STATE_ON)
    assert _group_on_calls() == []


async def test_setup_with_unknown_occupancy_sends_no_on(hass) -> None:
    """Setup with unavailable occupancy never switches on; unknown is not vacancy either."""
    await _setup(hass, lux="50", motion="unavailable")
    assert _group_on_calls() == []


async def test_reload_after_on_sends_no_second_on(hass) -> None:
    """A real config entry reload with the lights already on sends no duplicate ON."""
    entry = await _setup(hass, lux="50", motion=STATE_ON)
    assert len(_group_on_calls()) == 1
    CALLS.clear()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await _enable_group_control(hass)
    await hass.async_block_till_done()
    assert _group_on_calls() == []


async def test_unload_releases_integration_event_listeners(hass) -> None:
    """Unload removes the integration's own bus listeners (registry and light events).

    Listeners of Home Assistant core for start, stop and component loading (homeassistant_*,
    component_loaded) are registered when the light and group domains load for the first time and
    stay registered by design; they are not counted here.
    """
    await hass.async_block_till_done()
    own_types = (
        "entity_registry_updated",
        "device_registry_updated",
        "floor_registry_updated",
        "label_registry_updated",
        "category_registry_updated",
        "call_service",
        "state_changed",
    )
    before = {t: hass.bus.async_listeners().get(t, 0) for t in own_types}
    entry = await _setup(hass, lux="50", motion=STATE_ON)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    after = {t: hass.bus.async_listeners().get(t, 0) for t in own_types}
    assert after == before


async def test_repair_is_created_at_setup_and_resolved_after_correction(hass) -> None:
    """Missing limits create the brightness repair during setup; a corrected entry plus reload clears it."""
    entry = _entry()
    entry.add_to_hass(hass)
    data = {
        **entry.data,
        CONF_ENABLED_FEATURES: {
            **entry.data[CONF_ENABLED_FEATURES],
            CONF_FEATURE_LIGHT: {},
        },
    }
    hass.config_entries.async_update_entry(entry, data=data)
    issue_id = _issue_id(ISSUE_BRIGHTNESS_CONFIGURATION, entry.entry_id)
    await _setup(hass, lux="50", motion=STATE_OFF, entry=entry)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "brightness_limits_missing"

    corrected = {
        **entry.data,
        CONF_ENABLED_FEATURES: {
            **entry.data[CONF_ENABLED_FEATURES],
            CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
        },
    }
    hass.config_entries.async_update_entry(entry, data=corrected)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
