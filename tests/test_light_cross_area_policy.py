"""B01 cross-Area: a lamp of Area A's HA area that is exclusively a group member of Area B.

Area A's policy-only path must not switch it; Area B's configured group controls it.
Real setup, real service events (shared harness of test_light_ownership_runtime).
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from tests.test_light_ownership_runtime import (
    LIGHT,
    LIGHT_B,
    POLICY_LAMP,
    _area_entry,
    _automatic,
    _dark,
    _free,
    _occupy,
    _run,
    _targets,
    setup_lamps,  # noqa: F401
)
import pytest

from tests.test_light_coordination_regression import (  # noqa: F401
    LUX,
    probe_devices,
)
from tests.test_light import setup_entities_light_one  # noqa: F401

pytestmark = pytest.mark.usefixtures("probe_devices", "lamps")


async def test_policy_of_owner_area_does_not_switch_foreign_lamp(
    hass: HomeAssistant,
) -> None:
    """LIGHT is in kitchen's HA area and in kitchen's scope, but only living room's group owns it."""
    entries = {
        "a": _area_entry("a", [POLICY_LAMP, LIGHT], []),
        "b": _area_entry("b", [LIGHT_B, LIGHT], [LIGHT]),
    }
    per = await _run(hass, entries, [_dark, _occupy("a"), _occupy("b")])
    # Kitchen policy switches its own policy-only lamp, never the lamp of Living room's group.
    assert POLICY_LAMP in _targets(per[1])
    assert LIGHT not in _targets(per[1])
    # Living room's configured group controls the lamp: an automatic call reaches it.
    assert any(LIGHT in e["targets"] for e in _automatic(per[2]))
    assert not any(LIGHT in e["targets"] for e in _automatic(per[1]))


async def test_all_group_of_the_other_area_never_switches_the_owned_lamp(
    hass: HomeAssistant,
) -> None:
    """Area A's ALL group does not contain a lamp that only Area B's group owns.

    Through a full cycle (occupation and final CLEAR) Area A's ALL group never switches it.
    """
    from custom_components.adaptive_areas.helpers.light_ownership_runtime import (
        owned_automatic_lights,
    )

    # A has a configured group (so its ALL group exists); the owned lamp is not in it.
    entries = {
        "a": _area_entry("a", [POLICY_LAMP, LIGHT], [POLICY_LAMP]),
        "b": _area_entry("b", [LIGHT_B, LIGHT], [LIGHT]),
    }
    a_all = "light.adaptive_areas_light_groups_kitchen_all_lights"

    async def _check_all(hass_: HomeAssistant) -> None:
        state = hass_.states.get(a_all)
        assert state is not None
        assert LIGHT not in state.attributes.get("lights", [])
        assert LIGHT in owned_automatic_lights(hass_)

    per = await _run(hass, entries, [_dark, _occupy("a"), _free("a"), _check_all])
    a_off = [
        e
        for e in _automatic(per[2])
        if e["service"] == "turn_off" and a_all in e["targets"]
    ]
    assert not any(LIGHT in e["targets"] for e in a_off)
