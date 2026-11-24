"""Direct HA tests of the unified automatic path for secondary light groups (overhead group).

Real integration and real service events. Automatic calls are light calls without a user
context, counted on the overhead group entity (a group call forwards to its members; the
forward is not a second decision). No sleeps.
"""

from __future__ import annotations

import pytest
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    AreaStates,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
    LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
    LIGHT_GROUP_BRIGHTNESS_IGNORE,
    LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK,
    LIGHT_GROUP_BRIGHTNESS_TURN_OFF,
)
from tests import test_light_coordination_regression as regression
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_clear_cutover import EVENTS, _run
from tests.test_light_coordination_regression import (  # noqa: F401
    LIGHT,
    LUX,
    SLEEP,
    _bright,
    _dark,
    _entry,
    _free,
    _occupy,
    probe_devices,
)

pytestmark = pytest.mark.usefixtures("probe_devices")

OVERHEAD = "light.adaptive_areas_light_groups_kitchen_overhead_lights"


def _entry_with(brightness: str, blocking=None) -> MockConfigEntry:
    entry = _entry(blocking=blocking)
    groups = entry.data[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS]
    groups[CONF_OVERHEAD_LIGHTS_BRIGHTNESS] = brightness
    return entry


def _auto(events: list[dict], service: str) -> list[dict]:
    return [
        e
        for e in events
        if e["service"] == service and e["target"] == OVERHEAD and not e["user"]
    ]


async def _lux_unknown(hass: HomeAssistant) -> None:
    hass.states.async_set(LUX, "unavailable", {"unit_of_measurement": "lx"})
    await hass.async_block_till_done()


async def _sleep_on(hass: HomeAssistant) -> None:
    hass.states.async_set(SLEEP, STATE_ON)
    await hass.async_block_till_done()


async def _sleep_off(hass: HomeAssistant) -> None:
    hass.states.async_set(SLEEP, STATE_OFF)
    await hass.async_block_till_done()


async def _nothing(hass: HomeAssistant) -> None:
    await hass.async_block_till_done()


def _group(hass: HomeAssistant):
    from homeassistant.components.light import DATA_COMPONENT

    from custom_components.adaptive_areas.const import LightGroupCategory
    from custom_components.adaptive_areas.light import AreaLightGroup

    for entity in hass.data[DATA_COMPONENT].entities:
        if isinstance(entity, AreaLightGroup) and str(entity.category) == str(
            LightGroupCategory.OVERHEAD
        ):
            return entity
    raise AssertionError("no overhead group")


async def _force_override(hass: HomeAssistant) -> None:
    _group(hass)._set_manual_override(True)
    await hass.async_block_till_done()


# -- The four brightness modes -----------------------------------------------------


async def test_require_dark_occupation_in_dark_turns_on_once(hass) -> None:
    """require_dark: occupation with a DARK reading gives exactly one ON."""
    per = await _run(
        hass, _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK), [_dark, _occupy]
    )
    assert len(_auto(per[1], "turn_on")) == 1


async def test_require_dark_occupation_in_bright_sends_nothing(hass) -> None:
    """require_dark: BRIGHT never turns the group on."""
    per = await _run(
        hass, _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK), [_bright, _occupy]
    )
    assert _auto(per[1], "turn_on") == []


async def test_ignore_occupation_turns_on_regardless_of_brightness(hass) -> None:
    """ignore: the brightness is irrelevant; occupation gives one ON."""
    per = await _run(
        hass, _entry_with(LIGHT_GROUP_BRIGHTNESS_IGNORE), [_bright, _occupy]
    )
    assert len(_auto(per[1], "turn_on")) == 1


async def test_turn_off_mode_switches_off_when_bright_while_occupied(hass) -> None:
    """turn_off: occupied and BRIGHT gives one OFF; no ON from the brightness change."""
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_TURN_OFF),
        [_dark, _occupy, _bright],
    )
    assert len(_auto(per[1], "turn_on")) == 1
    assert _auto(per[2], "turn_on") == []
    assert len(_auto(per[2], "turn_off")) == 1


async def test_dark_on_bright_off_mode_follows_brightness(hass) -> None:
    """dark_on_bright_off: BRIGHT occupation sends nothing, DARK gives ON, BRIGHT gives OFF."""
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF),
        [_bright, _occupy, _dark, _bright],
    )
    assert _auto(per[1], "turn_on") == []
    assert len(_auto(per[2], "turn_on")) == 1
    assert len(_auto(per[3], "turn_off")) == 1


# -- UNKNOWN brightness and hysteresis -------------------------------------------


async def test_unknown_brightness_blocks_on_for_require_dark(hass) -> None:
    """require_dark: an UNKNOWN reading does not turn the group on."""
    per = await _run(
        hass, _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK), [_lux_unknown, _occupy]
    )
    assert _auto(per[1], "turn_on") == []


async def test_unknown_brightness_does_not_block_on_for_turn_off_mode(hass) -> None:
    """turn_off: UNKNOWN brightness does not prevent the ON of an occupied Area."""
    per = await _run(
        hass, _entry_with(LIGHT_GROUP_BRIGHTNESS_TURN_OFF), [_lux_unknown, _occupy]
    )
    assert len(_auto(per[1], "turn_on")) == 1


async def test_hysteresis_no_extra_switch_within_the_same_reading(hass) -> None:
    """require_dark: a repeated DARK reading after an ON sends nothing (no flip-flop)."""
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _occupy, _dark, _dark],
    )
    assert len(_auto(per[1], "turn_on")) == 1
    assert _auto(per[2], "turn_on") == []
    assert _auto(per[3], "turn_on") == []
    assert _auto(per[2], "turn_off") == []


# -- Duplicates and failures -------------------------------------------------------


async def test_repeated_identical_occupation_sends_no_second_on(hass) -> None:
    """The same occupation signal again is an identical input: no second command."""
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _occupy, _occupy],
    )
    assert _auto(per[2], "turn_on") == []
    assert len(_auto(per[1], "turn_on")) == 1


async def test_failed_automatic_call_is_not_retried(hass, monkeypatch) -> None:
    """A failing automatic ON is attempted once; the same unchanged input sends no retry."""
    from custom_components.adaptive_areas.helpers import light_executor

    attempts: list[str] = []
    original = light_executor.async_execute_light_entity_action

    async def failing(hass_, entity_id, service, *, context):
        if entity_id == OVERHEAD and service == "turn_on":
            attempts.append(entity_id)
            raise RuntimeError("service unavailable")
        return await original(hass_, entity_id, service, context=context)

    monkeypatch.setattr(
        "custom_components.adaptive_areas.light.async_execute_light_entity_action",
        failing,
    )
    await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _occupy, _occupy],
    )
    assert attempts == [OVERHEAD]


# -- Blocker and override ----------------------------------------------------------


async def test_blocker_activation_switches_off_and_blocker_end_switches_on(
    hass,
) -> None:
    """An effective blocker switches OFF; its end switches ON again under matching conditions."""
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK, blocking=[AreaStates.SLEEP]),
        [_dark, _occupy, _sleep_on, _sleep_off],
    )
    assert len(_auto(per[1], "turn_on")) == 1
    assert _auto(per[2], "turn_on") == []
    assert len(_auto(per[2], "turn_off")) == 1
    assert len(_auto(per[3], "turn_on")) == 1


async def test_manual_override_during_occupation_blocks_automatic_action(hass) -> None:
    """An override set before the occupation blocks its ON; the CLEAR sends no OFF here."""
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _force_override, _occupy, _free],
    )
    assert _auto(per[2], "turn_on") == []
    assert _auto(per[3], "turn_off") == []


# -- Initial decision and reload ---------------------------------------------------


async def test_initial_decision_is_taken_once_per_generation(hass) -> None:
    """Occupied and dark, lights off: exactly one automatic ON per generation, never a second.

    The automation switch is on from the setup on, so the occupied, dark Area switches on once
    (by the initial decision or the switch listener, whichever comes first). The reload is a
    new generation with the lights already on: it sends nothing.
    """
    entry = _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK)
    hass.states.async_set(LUX, "50", {"unit_of_measurement": "lx"})
    hass.states.async_set(regression.MOTION, STATE_ON, {"device_class": "motion"})

    async def _reload(hass_: HomeAssistant) -> None:
        await hass_.config_entries.async_reload(entry.entry_id)
        await hass_.async_block_till_done()
        await regression._enable_group_control(hass_)

    per = await _run(hass, entry, [_nothing, _reload])
    assert len(_auto(EVENTS, "turn_on")) == 1
    assert _auto(per[1], "turn_on") == []


async def test_reload_keeps_the_state_without_a_duplicate_command(hass) -> None:
    """After a reload the lights are already on: the initial decision sends nothing."""
    entry = _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK)

    async def _reload(hass_: HomeAssistant) -> None:
        await hass_.config_entries.async_reload(entry.entry_id)
        await hass_.async_block_till_done()
        await regression._enable_group_control(hass_)

    per = await _run(hass, entry, [_dark, _occupy, _reload])
    assert len(_auto(per[1], "turn_on")) == 1
    assert _auto(per[2], "turn_on") == []
    assert _auto(per[2], "turn_off") == []


# -- Automation switch -------------------------------------------------------------


async def test_disabled_automation_sends_nothing_and_enabling_evaluates_the_current_state(
    hass,
) -> None:
    """Disabled automation sends nothing; enabling it is a relevant event on the current state."""

    async def _disable(hass_: HomeAssistant) -> None:
        await hass_.services.async_call(
            "switch",
            "turn_off",
            {ATTR_ENTITY_ID: regression.CONTROL_SWITCH},
            blocking=True,
        )
        await hass_.async_block_till_done()

    async def _enable(hass_: HomeAssistant) -> None:
        await regression._enable_group_control(hass_)

    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _disable, _occupy, _enable],
    )
    assert _auto(per[2], "turn_on") == []
    assert len(_auto(per[3], "turn_on")) == 1


# -- Manual complete switch-off and override (Schritt A) --------------------------


async def _manual_group_off(hass: HomeAssistant) -> None:
    """Switch the whole overhead group off as a user (user context)."""
    await hass.services.async_call(
        "light",
        "turn_off",
        {ATTR_ENTITY_ID: OVERHEAD},
        blocking=True,
        context=Context(user_id=regression.PROBE_USER[0]),
    )
    await hass.async_block_till_done()


async def _override_state(hass: HomeAssistant) -> None:
    SEEN.append({"override": _group(hass).manual_override})


SEEN: list[dict] = []
KITCHEN_ALL = "light.adaptive_areas_light_groups_kitchen_all_lights"


async def test_manual_full_off_holds_against_presence_activity(hass) -> None:
    """Auto ON, then a user's complete OFF: presence activity does not switch the group on."""
    SEEN.clear()
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _occupy, _manual_group_off, _override_state, _occupy],
    )
    assert len(_auto(per[1], "turn_on")) == 1
    assert SEEN == [{"override": True}]
    assert _auto(per[2], "turn_off") == []
    assert _auto(per[4], "turn_on") == []


async def test_manual_full_off_holds_against_brightness_change(hass) -> None:
    """After a user's complete OFF, a DARK/BRIGHT change does not switch the group on."""
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _occupy, _manual_group_off, _bright, _dark],
    )
    assert _auto(per[3], "turn_on") == []
    assert _auto(per[4], "turn_on") == []


async def test_clear_ends_the_manual_override_and_allows_the_clear_off(hass) -> None:
    """CLEAR ends the override; the automatic OFF of the ALL group stays allowed (one call).

    The lamps are still on here (override set without a manual action), so the OFF is needed.
    """
    SEEN.clear()
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _occupy, _force_override, _free, _override_state],
    )
    assert SEEN == [{"override": False}]
    all_off = [
        e
        for e in per[3]
        if e["service"] == "turn_off" and e["target"] == KITCHEN_ALL and not e["user"]
    ]
    assert len(all_off) == 1


async def test_user_full_off_then_clear_sends_no_redundant_off(hass) -> None:
    """Lamps already off by the user: CLEAR ends the override and sends no redundant OFF."""
    SEEN.clear()
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _occupy, _manual_group_off, _free, _override_state],
    )
    assert SEEN == [{"override": False}]
    assert [
        e
        for e in per[3]
        if e["service"] == "turn_off" and e["target"] == KITCHEN_ALL and not e["user"]
    ] == []


async def test_reoccupation_after_clear_is_regular_automation_again(hass) -> None:
    """After CLEAR the automation may switch on again on a new occupation (exactly one ON)."""
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _occupy, _manual_group_off, _free, _occupy],
    )
    assert len(_auto(per[4], "turn_on")) == 1


async def test_override_set_before_the_scheduled_on_discards_it(hass) -> None:
    """A planned automatic ON is dropped if an override is set before its service call."""

    async def _schedule_then_override(hass_: HomeAssistant) -> None:
        from custom_components.adaptive_areas.helpers.light_transition import (
            TransitionAction,
        )

        group = _group(hass_)
        group._async_schedule_command(TransitionAction.TURN_ON, "area_state_changed")
        group._set_manual_override(True)
        await hass_.async_block_till_done()

    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _schedule_then_override],
    )
    assert _auto(per[1], "turn_on") == []


async def _presence_unavailable(hass: HomeAssistant) -> None:
    hass.states.async_set(regression.MOTION, "unavailable", {"device_class": "motion"})
    await hass.async_block_till_done()


async def test_unknown_presence_never_switches_the_group_off(hass) -> None:
    """Occupied and lamps on; the presence source becomes unavailable: no automatic OFF."""
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_dark, _occupy, _presence_unavailable],
    )
    assert len(_auto(per[1], "turn_on")) == 1
    assert _auto(per[2], "turn_off") == []


async def test_unknown_presence_never_switches_the_group_on(hass) -> None:
    """Presence unknown from the start: no ON, even with dark and a later brightness change."""
    per = await _run(
        hass,
        _entry_with(LIGHT_GROUP_BRIGHTNESS_REQUIRE_DARK),
        [_presence_unavailable, _dark, _bright, _dark],
    )
    for step in per:
        assert _auto(step, "turn_on") == []
