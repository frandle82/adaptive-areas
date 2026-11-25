"""Direct HA tests of the ALL light group on the shared decision path (Schritt C).

The ALL group is switched off on a vacancy (CLEAR) only, never on automatically. Real service
calls on the ALL group entity are counted (automation context, no user). No sleeps.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import LightGroupCategory
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_clear_cutover import _entry, _run
from tests.test_light_coordination_regression import (  # noqa: F401
    _bright,
    _dark,
    _free,
    _occupy,
    probe_devices,
)

pytestmark = pytest.mark.usefixtures("probe_devices")

ALL_GROUP = "light.adaptive_areas_light_groups_kitchen_all_lights"
OVERHEAD = "light.adaptive_areas_light_groups_kitchen_overhead_lights"


def _auto(events: list[dict], target: str, service: str) -> list[dict]:
    return [
        e
        for e in events
        if e["service"] == service and e["target"] == target and not e["user"]
    ]


def _all_group(hass: HomeAssistant):
    from homeassistant.components.light import DATA_COMPONENT

    from custom_components.adaptive_areas.light import AreaLightGroup

    for entity in hass.data[DATA_COMPONENT].entities:
        if isinstance(entity, AreaLightGroup) and str(entity.category) == str(
            LightGroupCategory.ALL
        ):
            return entity
    raise AssertionError("no ALL group")


async def _all_override_on(hass: HomeAssistant) -> None:
    _all_group(hass)._set_manual_override(True)
    await hass.async_block_till_done()


async def test_occupation_never_switches_the_all_group_on(hass) -> None:
    """The ALL group has no automatic ON; the overhead group does its own ON."""
    per = await _run(hass, _entry(), [_dark, _occupy])
    assert _auto(per[1], ALL_GROUP, "turn_on") == []
    assert len(_auto(per[1], OVERHEAD, "turn_on")) == 1


async def test_clear_then_occupation_sends_no_all_on_and_no_extra_off(hass) -> None:
    """CLEAR sends one ALL OFF; the next occupation sends no ALL ON and no second OFF."""
    per = await _run(hass, _entry(), [_dark, _occupy, _free, _occupy])
    assert len(_auto(per[2], ALL_GROUP, "turn_off")) == 1
    assert _auto(per[3], ALL_GROUP, "turn_on") == []
    assert _auto(per[3], ALL_GROUP, "turn_off") == []


async def test_brightness_changes_do_not_switch_the_all_group(hass) -> None:
    """DARK and BRIGHT changes while occupied send no ALL command (no BRIGHT OFF on ALL)."""
    per = await _run(hass, _entry(), [_dark, _occupy, _bright, _dark])
    for step in per[1:]:
        assert _auto(step, ALL_GROUP, "turn_on") == []
        assert _auto(step, ALL_GROUP, "turn_off") == []


async def test_override_then_clear_allows_exactly_one_all_off(hass) -> None:
    """An override during occupation ends with the CLEAR; the allowed OFF is sent once."""
    per = await _run(
        hass,
        _entry(),
        [_dark, _occupy, _all_override_on, _free, _free],
    )
    assert len(_auto(per[3], ALL_GROUP, "turn_off")) == 1
    assert _auto(per[4], ALL_GROUP, "turn_off") == []


async def test_repeated_clear_sends_no_second_all_off(hass) -> None:
    """A repeated CLEAR is an identical input: no second ALL OFF."""
    per = await _run(hass, _entry(), [_dark, _occupy, _free, _free])
    assert len(_auto(per[2], ALL_GROUP, "turn_off")) == 1
    assert _auto(per[3], ALL_GROUP, "turn_off") == []


async def test_failed_all_off_is_not_retried_by_an_identical_event(
    hass, monkeypatch
) -> None:
    """A failing ALL OFF is attempted once; an identical later clear event does not retry."""
    from tests.service_faults import install_group_command_fault, native_group_command

    attempts: list[str] = []
    original = native_group_command(hass)

    async def failing(hass_, entity_id, service, *, context):
        if entity_id == ALL_GROUP and service == "turn_off":
            attempts.append(entity_id)
            raise RuntimeError("service unavailable")
        return await original(hass_, entity_id, service, context=context)

    install_group_command_fault(monkeypatch, hass, failing)
    await _run(hass, _entry(), [_dark, _occupy, _free, _free])
    assert attempts == [ALL_GROUP]


async def test_failed_all_off_then_new_occupation_and_clear_tries_again(
    hass, monkeypatch
) -> None:
    """After a failure, a new relevant change (occupation, then CLEAR) is a new decision."""
    from tests.service_faults import install_group_command_fault, native_group_command

    attempts: list[str] = []
    original = native_group_command(hass)

    async def failing_once(hass_, entity_id, service, *, context):
        if entity_id == ALL_GROUP and service == "turn_off":
            attempts.append(entity_id)
            if len(attempts) == 1:
                raise RuntimeError("service unavailable")
        return await original(hass_, entity_id, service, context=context)

    install_group_command_fault(monkeypatch, hass, failing_once)
    await _run(hass, _entry(), [_dark, _occupy, _free, _occupy, _free])
    assert len(attempts) == 2


async def test_all_off_forward_is_not_a_manual_override_of_the_subgroup(hass) -> None:
    """The ALL group forwards its CLEAR OFF to the lamps the overhead group also holds.

    The overhead group must recognise that change as the Area's own automation: no override.
    """
    from custom_components.adaptive_areas.const import LightGroupCategory
    from homeassistant.components.light import DATA_COMPONENT

    from custom_components.adaptive_areas.light import AreaLightGroup

    overhead_state: list[bool] = []

    async def _check(hass_: HomeAssistant) -> None:
        for entity in hass_.data[DATA_COMPONENT].entities:
            if isinstance(entity, AreaLightGroup) and str(entity.category) == str(
                LightGroupCategory.OVERHEAD
            ):
                overhead_state.append(entity.manual_override)
        await hass_.async_block_till_done()

    per = await _run(hass, _entry(), [_dark, _occupy, _free, _check])
    assert len(_auto(per[2], ALL_GROUP, "turn_off")) == 1
    assert overhead_state == [False]
