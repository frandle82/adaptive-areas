"""Meta-Area brightness follows its child Areas (Phase 5).

DARK when any child Area is DARK. BRIGHT only when every child Area reports BRIGHT. A child
without DARK or BRIGHT (UNKNOWN, missing state entity or missing states attribute) never makes
the Meta-Area BRIGHT. The Meta-Area ALL light group takes no automatic decision from this state.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest

from custom_components.adaptive_areas.const import AreaStates
from custom_components.adaptive_areas.helpers.area import iter_runtime_areas
from tests.test_dashboard_presence_state import (  # noqa: F401
    _overview,
    multi_area,
)

pytestmark = pytest.mark.usefixtures("multi_area")


def _meta_with_children(hass: HomeAssistant):
    for area in iter_runtime_areas(hass):
        if area.is_meta() and area.get_child_areas():
            return area
    raise AssertionError("no meta area with children in the fixture")


def _child_entity(slug: str) -> str:
    return f"binary_sensor.adaptive_areas_presence_tracking_{slug}_area_state"


def _meta_entity(hass: HomeAssistant, meta):
    return hass.data["binary_sensor"].get_entity(
        f"binary_sensor.adaptive_areas_presence_tracking_{meta.slug}_area_state"
    )


def _set_children(hass: HomeAssistant, children: list[str], mode: str) -> None:
    """Set each child to one brightness report; ``mode`` decides which children differ."""
    for index, slug in enumerate(children):
        if mode == "all_bright":
            states = [AreaStates.BRIGHT]
        elif mode == "all_dark":
            states = [AreaStates.DARK]
        elif mode == "all_unknown":
            states = []
        elif mode == "one_dark":
            states = [AreaStates.DARK] if index == 0 else [AreaStates.BRIGHT]
        elif mode == "one_unknown":
            states = [] if index == 0 else [AreaStates.BRIGHT]
        elif mode == "dark_and_unknown":
            states = [AreaStates.DARK] if index == 0 else []
        else:
            raise AssertionError(mode)
        hass.states.async_set(
            _child_entity(slug),
            "off",
            {"states": [str(state) for state in states]},
        )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("all_bright", [AreaStates.BRIGHT]),
        ("all_dark", [AreaStates.DARK]),
        ("all_unknown", []),
        ("one_dark", [AreaStates.DARK]),
        ("one_unknown", []),
        ("dark_and_unknown", [AreaStates.DARK]),
    ],
)
async def test_meta_brightness_matrix(hass: HomeAssistant, mode, expected):
    """The Meta-Area DARK/BRIGHT follows the child matrix; UNKNOWN is never BRIGHT."""
    meta = _meta_with_children(hass)
    _set_children(hass, meta.get_child_areas(), mode)
    entity = _meta_entity(hass, meta)
    entity._update_state()
    states = entity._get_secondary_states()
    brightness = [s for s in states if s in (AreaStates.DARK, AreaStates.BRIGHT)]
    assert brightness == expected


async def test_missing_child_entity_is_not_bright(hass: HomeAssistant):
    """A child without a state entity is unknown: the Meta-Area is not BRIGHT."""
    meta = _meta_with_children(hass)
    children = meta.get_child_areas()
    _set_children(hass, children, "all_bright")
    hass.states.async_remove(_child_entity(children[0]))
    entity = _meta_entity(hass, meta)
    entity._update_state()
    assert AreaStates.BRIGHT not in entity._get_secondary_states()


async def test_dashboard_does_not_count_unknown_meta_as_bright(
    hass: HomeAssistant,
) -> None:
    """The overview reports no brightness for a Meta-Area whose children are all UNKNOWN."""
    meta = _meta_with_children(hass)
    _set_children(hass, meta.get_child_areas(), "all_unknown")
    entity = _meta_entity(hass, meta)
    entity._update_state()
    payload = await _overview(hass)
    meta_rows = [a for a in payload["areas"] if a.get("type") == "meta"]
    assert meta_rows
    assert all(
        row.get("brightness") is None or row["brightness"].get("state") != "bright"
        for row in meta_rows
        if row["id"] == meta.slug
    )
