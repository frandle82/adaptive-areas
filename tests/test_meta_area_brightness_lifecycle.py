"""Meta-Area brightness: lifecycle, transitions, events and light calls (Phase 5 completion).

Complements tests/test_meta_area_brightness.py. The production aggregation is used throughout:
the child Areas report their states through their real state entities, and the Meta-Area
entity recalculates through its own `_update_state`.
"""

from __future__ import annotations

from homeassistant.core import Event, HomeAssistant
import pytest

from custom_components.adaptive_areas.const import (
    AreaStates,
    EVENT_ADAPTIVE_AREAS_AREA,
)
from custom_components.adaptive_areas.helpers.area import iter_runtime_areas
from tests.test_dashboard_presence_state import multi_area  # noqa: F401

pytestmark = pytest.mark.usefixtures("multi_area")


def _meta(hass: HomeAssistant):
    for area in iter_runtime_areas(hass):
        if area.is_meta() and area.get_child_areas():
            return area
    raise AssertionError("no meta area with children in the fixture")


def _child_entity(slug: str) -> str:
    return f"binary_sensor.adaptive_areas_presence_tracking_{slug}_area_state"


def _entity(hass: HomeAssistant, meta):
    return hass.data["binary_sensor"].get_entity(
        f"binary_sensor.adaptive_areas_presence_tracking_{meta.slug}_area_state"
    )


def _report(hass: HomeAssistant, slug: str, states: list[str] | None) -> None:
    """Set one child's report: a list of states, or None for no state attribute."""
    if states is None:
        hass.states.async_set(_child_entity(slug), "unavailable", {})
    else:
        hass.states.async_set(
            _child_entity(slug), "off", {"states": [str(s) for s in states]}
        )


def _set_all(hass: HomeAssistant, children: list[str], value) -> None:
    for slug in children:
        _report(hass, slug, value)


async def _recalc(hass: HomeAssistant, meta) -> set[str]:
    """Recalculate the Meta-Area through its production entity and return its states."""
    entity = _entity(hass, meta)
    entity._update_state()
    await hass.async_block_till_done()
    return {str(s) for s in meta.states}


def _brightness(states: set[str]) -> set[str]:
    return states & {AreaStates.DARK, AreaStates.BRIGHT}


def _record_events(hass: HomeAssistant, meta) -> list[str]:
    events: list[str] = []

    def _listener(event: Event) -> None:
        if event.data.get("area_id") == meta.id:
            events.append(event.data["event_type"])

    hass.bus.async_listen(EVENT_ADAPTIVE_AREAS_AREA, _listener)
    return events


# 4.1 Hierarchy and lifecycle ---------------------------------------------------------------


async def test_single_relevant_child_dark_makes_meta_dark(hass) -> None:
    """A single relevant DARK child makes the Meta-Area DARK."""
    meta = _meta(hass)
    children = meta.get_child_areas()
    _set_all(hass, children, None)
    _report(hass, children[0], [AreaStates.DARK])
    states = await _recalc(hass, meta)
    assert AreaStates.DARK in states
    assert AreaStates.BRIGHT not in states


async def test_bright_child_with_unknown_siblings_is_unknown(hass) -> None:
    """A BRIGHT child together with other relevant UNKNOWN children is UNKNOWN."""
    meta = _meta(hass)
    children = meta.get_child_areas()
    _set_all(hass, children, None)
    _report(hass, children[0], [AreaStates.BRIGHT])
    assert _brightness(await _recalc(hass, meta)) == set()


async def test_exactly_one_relevant_bright_child_is_bright(hass) -> None:
    """With exactly one relevant child, reporting BRIGHT makes the Meta-Area BRIGHT."""
    meta = _meta(hass)
    only = meta.get_child_areas()[0]
    _report(hass, only, [AreaStates.BRIGHT])
    original = meta.get_child_areas
    meta.get_child_areas = lambda: [only]  # type: ignore[method-assign]
    try:
        assert _brightness(await _recalc(hass, meta)) == {AreaStates.BRIGHT}
    finally:
        meta.get_child_areas = original  # type: ignore[method-assign]


async def test_no_relevant_children_is_unknown(hass) -> None:
    """A single BRIGHT child with all others missing is UNKNOWN."""
    meta = _meta(hass)
    for slug in meta.get_child_areas():
        hass.states.async_remove(_child_entity(slug))
    assert _brightness(await _recalc(hass, meta)) == set()


async def test_missing_child_entity_is_unknown_and_recovers(hass) -> None:
    """No relevant child is UNKNOWN for the Meta-Area."""
    meta = _meta(hass)
    children = meta.get_child_areas()
    _set_all(hass, children, [AreaStates.BRIGHT])
    assert _brightness(await _recalc(hass, meta)) == {AreaStates.BRIGHT}
    hass.states.async_remove(_child_entity(children[0]))
    assert _brightness(await _recalc(hass, meta)) == set()
    _report(hass, children[0], [AreaStates.BRIGHT])
    assert _brightness(await _recalc(hass, meta)) == {AreaStates.BRIGHT}


async def test_unavailable_child_is_unknown_and_dark_from_others_still_counts(
    hass,
) -> None:
    """An unavailable child is UNKNOWN; a DARK child among the others still counts."""
    meta = _meta(hass)
    children = meta.get_child_areas()
    _set_all(hass, children, [AreaStates.BRIGHT])
    _report(hass, children[1], None)
    assert _brightness(await _recalc(hass, meta)) == set()
    _report(hass, children[2], [AreaStates.DARK])
    assert _brightness(await _recalc(hass, meta)) == {AreaStates.DARK}


async def test_child_removed_from_hierarchy_is_not_counted(hass) -> None:
    """A child that is no longer a child of the Meta-Area does not influence its brightness."""
    meta = _meta(hass)
    children = list(meta.get_child_areas())
    _set_all(hass, children, [AreaStates.BRIGHT])
    removed = children.pop()
    _report(hass, removed, [AreaStates.DARK])
    original = meta.get_child_areas
    meta.get_child_areas = lambda: children  # type: ignore[method-assign]
    try:
        assert _brightness(await _recalc(hass, meta)) == {AreaStates.BRIGHT}
    finally:
        meta.get_child_areas = original  # type: ignore[method-assign]

    meta = _meta(hass)
    children = meta.get_child_areas()
    _set_all(hass, children, [AreaStates.BRIGHT])
    _report(hass, children[0], [AreaStates.DARK])
    first = _brightness(await _recalc(hass, meta))
    second = _brightness(await _recalc(hass, meta))
    assert first == second == {AreaStates.DARK}


# 4.2 Brightness transitions and event contract -----------------------------------------------


@pytest.mark.parametrize(
    ("before", "after", "expected_brightness", "expected_events"),
    [
        ("unknown", "dark", {AreaStates.DARK}, ["dark_started"]),
        ("unknown", "bright", {AreaStates.BRIGHT}, []),
        ("dark", "unknown", set(), ["dark_ended"]),
        ("bright", "unknown", set(), []),
        ("dark", "bright", {AreaStates.BRIGHT}, ["dark_ended"]),
        ("bright", "dark", {AreaStates.DARK}, ["dark_started"]),
        ("dark", "dark", {AreaStates.DARK}, []),
        ("bright", "bright", {AreaStates.BRIGHT}, []),
    ],
)
async def test_brightness_transition_and_events(
    hass, before, after, expected_brightness, expected_events
) -> None:
    """Each transition yields the aggregated brightness and the existing event contract."""
    meta = _meta(hass)
    children = meta.get_child_areas()
    values = {
        "unknown": [],
        "dark": [AreaStates.DARK],
        "bright": [AreaStates.BRIGHT],
    }
    _set_all(hass, children, values[before])
    await _recalc(hass, meta)
    events = _record_events(hass, meta)
    _set_all(hass, children, values[after])
    states = await _recalc(hass, meta)
    assert _brightness(states) == expected_brightness
    assert events == expected_events


async def test_unchanged_aggregate_sends_no_duplicate_events(hass) -> None:
    """A removed child is not counted."""
    meta = _meta(hass)
    children = meta.get_child_areas()
    _set_all(hass, children, [AreaStates.DARK])
    await _recalc(hass, meta)
    events = _record_events(hass, meta)
    for _ in range(3):
        await _recalc(hass, meta)
    assert events == []


async def test_one_dark_child_among_brights_fires_one_dark_started(hass) -> None:
    """Repeated recalculation uses the current child states only."""
    meta = _meta(hass)
    children = meta.get_child_areas()
    _set_all(hass, children, [AreaStates.BRIGHT])
    await _recalc(hass, meta)
    events = _record_events(hass, meta)
    _report(hass, children[0], [AreaStates.DARK])
    await _recalc(hass, meta)
    _report(hass, children[0], [AreaStates.DARK])
    await _recalc(hass, meta)
    assert events == ["dark_started"]


# 4.3 Automatic light control ------------------------------------------------------------------
async def test_meta_dark_sends_no_automatic_light_call(hass, monkeypatch) -> None:
    """Meta-Area DARK and BRIGHT transitions issue no automatic light service call.

    Negative check on real Home Assistant service calls. Automatic group commands come only from
    the individual Area light groups; the Meta-Area light group (ALL) takes no such decision.
    """
    calls: list[tuple[str, str]] = []
    real = type(hass.services).async_call

    async def _spy(self, domain, service, *args, **kwargs):
        if domain == "light":
            calls.append((domain, service))
        return await real(self, domain, service, *args, **kwargs)

    monkeypatch.setattr(type(hass.services), "async_call", _spy)
    # Positive control: the spy sees a real light call (an unknown entity is a no-op).
    await hass.services.async_call("light", "turn_on", {"entity_id": "light.none"})
    assert calls == [("light", "turn_on")]
    calls.clear()
    meta = _meta(hass)
    children = meta.get_child_areas()
    _set_all(hass, children, [AreaStates.BRIGHT])
    await _recalc(hass, meta)
    _report(hass, children[0], [AreaStates.DARK])
    await _recalc(hass, meta)
    _set_all(hass, children, [AreaStates.DARK])
    await _recalc(hass, meta)
    await hass.async_block_till_done()
    assert calls == []
