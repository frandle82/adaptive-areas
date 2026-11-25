"""Meta-Area hierarchy, reload and unload regressions (Phase 7).

Real fixture hierarchy: interior and first_floor share kitchen, living_room and dining_room;
global contains every physical Area; ground_level and exterior share garage and backyard.
The child Areas report their brightness through their real state entities (`states` attribute).
Child Areas without a brightness source report only occupancy states: they are UNKNOWN for
brightness, so a Meta-Area is DARK or BRIGHT only when its relevant children report it.
"""

from __future__ import annotations

from homeassistant.core import Event, HomeAssistant
import pytest

from custom_components.adaptive_areas.const import (
    DOMAIN,
    EVENT_ADAPTIVE_AREAS_AREA,
    AreaStates,
)
from custom_components.adaptive_areas.helpers.area import iter_runtime_areas
from tests.test_dashboard_presence_state import multi_area  # noqa: F401

pytestmark = pytest.mark.usefixtures("multi_area")

BRIGHTNESS = (AreaStates.DARK, AreaStates.BRIGHT)


def _meta(hass: HomeAssistant, slug: str):
    for area in iter_runtime_areas(hass):
        if area.is_meta() and area.slug == slug:
            return area
    raise AssertionError(f"meta area {slug} missing")


def _child_entity(slug: str) -> str:
    return f"binary_sensor.adaptive_areas_presence_tracking_{slug}_area_state"


def _report(hass: HomeAssistant, slug: str, states: list[str] | None) -> None:
    """Set one child's brightness report. None = unavailable child."""
    if states is None:
        hass.states.async_set(_child_entity(slug), "unavailable", {})
        return
    hass.states.async_set(
        _child_entity(slug), "off", {"states": ["clear", *[str(s) for s in states]]}
    )


def _entity(hass: HomeAssistant, meta):
    return hass.data["binary_sensor"].get_entity(
        f"binary_sensor.adaptive_areas_presence_tracking_{meta.slug}_area_state"
    )


async def _recalc(hass: HomeAssistant, slug: str) -> set[str]:
    meta = _meta(hass, slug)
    _entity(hass, meta)._update_state()
    await hass.async_block_till_done()
    return {str(s) for s in meta.states} & {str(b) for b in BRIGHTNESS}


def _events(hass: HomeAssistant) -> list[tuple[str, str]]:
    log: list[tuple[str, str]] = []

    def _listener(event: Event) -> None:
        log.append((event.data["area_id"], event.data["event_type"]))

    hass.bus.async_listen(EVENT_ADAPTIVE_AREAS_AREA, _listener)
    return log


# Nested hierarchy: the same child feeds several Meta-Areas ------------------------------------


async def test_dark_child_propagates_to_every_meta_area_that_contains_it(hass) -> None:
    """Kitchen is DARK: first_floor, interior and global are DARK; second_floor is unaffected."""
    for slug in (
        "kitchen",
        "living_room",
        "dining_room",
        "master_bedroom",
        "guest_bedroom",
        "garage",
        "backyard",
        "front_yard",
    ):
        _report(hass, slug, [AreaStates.BRIGHT])
    _report(hass, "kitchen", [AreaStates.DARK])
    assert await _recalc(hass, "first_floor") == {AreaStates.DARK}
    assert await _recalc(hass, "interior") == {AreaStates.DARK}
    assert await _recalc(hass, "global") == {AreaStates.DARK}
    assert await _recalc(hass, "second_floor") == {AreaStates.BRIGHT}


async def test_unknown_child_of_a_floor_makes_only_that_floor_unknown(hass) -> None:
    """A child without brightness keeps the Meta-Areas that contain it UNKNOWN, not the others."""
    _report(hass, "master_bedroom", [AreaStates.BRIGHT])
    _report(hass, "guest_bedroom", [AreaStates.BRIGHT])
    assert await _recalc(hass, "second_floor") == {AreaStates.BRIGHT}
    assert (
        await _recalc(hass, "first_floor") == set()
    )  # kitchen etc. have no brightness
    _report(hass, "garage", None)
    assert await _recalc(hass, "ground_level") == set()


async def test_recovered_child_restores_the_parent_meta_area(hass) -> None:
    """Outage and recovery of a child: the Meta-Areas follow it without a stale state."""
    for slug in ("master_bedroom", "guest_bedroom"):
        _report(hass, slug, [AreaStates.BRIGHT])
    assert await _recalc(hass, "second_floor") == {AreaStates.BRIGHT}
    _report(hass, "guest_bedroom", None)
    assert await _recalc(hass, "second_floor") == set()
    _report(hass, "guest_bedroom", [AreaStates.DARK])
    assert await _recalc(hass, "second_floor") == {AreaStates.DARK}


async def test_no_duplicate_brightness_events_across_nested_meta_areas(hass) -> None:
    """One child transition yields one event per Meta-Area that contains it, never more."""
    for slug in ("master_bedroom", "guest_bedroom"):
        _report(hass, slug, [AreaStates.BRIGHT])
    await _recalc(hass, "second_floor")
    events = _events(hass)
    _report(hass, "master_bedroom", [AreaStates.DARK])
    await _recalc(hass, "second_floor")
    await _recalc(hass, "second_floor")
    # master_bedroom is also a child of interior and global: each Meta-Area fires once.
    assert sorted(events) == sorted(
        [
            ("second_floor", "dark_started"),
            ("interior", "dark_started"),
            ("global", "dark_started"),
        ]
    )


# Reload and unload ------------------------------------------------------------------------------


async def _reload(hass: HomeAssistant) -> None:
    """Reload every Adaptive Areas config entry (one entry per Area and Meta-Area)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_reload_reinitialises_meta_brightness_from_children(hass) -> None:
    """After a real integration reload the Meta-Area is recalculated from the current children."""
    for slug in ("master_bedroom", "guest_bedroom"):
        _report(hass, slug, [AreaStates.BRIGHT])
    assert await _recalc(hass, "second_floor") == {AreaStates.BRIGHT}
    await _reload(hass)
    for slug in ("master_bedroom", "guest_bedroom"):
        _report(hass, slug, [AreaStates.DARK])
    assert await _recalc(hass, "second_floor") == {AreaStates.DARK}


async def test_reload_does_not_duplicate_meta_entities_or_events(hass) -> None:
    """Reload leaves exactly one presence entity per Meta-Area and sends no extra events."""
    before = len(
        [
            s
            for s in hass.states.async_all("binary_sensor")
            if s.entity_id.endswith("_second_floor_area_state")
        ]
    )
    await _reload(hass)
    after = len(
        [
            s
            for s in hass.states.async_all("binary_sensor")
            if s.entity_id.endswith("_second_floor_area_state")
        ]
    )
    assert before == after == 1
    for slug in ("master_bedroom", "guest_bedroom"):
        _report(hass, slug, [AreaStates.BRIGHT])
    await _recalc(hass, "second_floor")
    events = _events(hass)
    await _recalc(hass, "second_floor")
    assert events == []


async def test_unload_removes_meta_brightness_without_automatic_light_call(
    hass, monkeypatch
) -> None:
    """Unload stops the Meta-Area; no automatic light service call is issued at any point."""
    calls: list[tuple[str, str]] = []
    real = type(hass.services).async_call

    async def _spy(self, domain, service, *args, **kwargs):
        if domain == "light":
            calls.append((domain, service))
        return await real(self, domain, service, *args, **kwargs)

    monkeypatch.setattr(type(hass.services), "async_call", _spy)
    for slug in ("master_bedroom", "guest_bedroom"):
        _report(hass, slug, [AreaStates.DARK])
    await _recalc(hass, "second_floor")
    for entry in hass.config_entries.async_entries(DOMAIN):
        assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert calls == []
    # Native restored state after unload: unavailable, no brightness is published.
    state = hass.states.get(_child_entity("second_floor"))
    assert state is None or state.state == "unavailable"
