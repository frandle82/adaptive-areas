"""Pure transition decision: configured modes, transitions, UNKNOWN, overrides (no HA)."""

# ruff: noqa: D103 - table-driven test names describe the case

from __future__ import annotations

import pytest

from custom_components.adaptive_areas.helpers.brightness import BrightnessState
from custom_components.adaptive_areas.helpers.light_dispatch import Override
from custom_components.adaptive_areas.helpers.light_transition import (
    execute_once,
    initial_decision,
    light_owner,
    MODE_DARK_ON_BRIGHT_OFF,
    MODE_IGNORE,
    MODE_REQUIRE_DARK,
    MODE_TURN_OFF,
    AreaState,
    GroupConfig,
    TransitionAction,
    TransitionReason,
    transition_decision,
)

D, B, U = BrightnessState.DARK, BrightnessState.BRIGHT, BrightnessState.UNKNOWN
ON, OFF, NONE = (
    TransitionAction.TURN_ON,
    TransitionAction.TURN_OFF,
    TransitionAction.NO_ACTION,
)


def st(occupied, brightness, **kw) -> AreaState:
    return AreaState(occupied=occupied, brightness=brightness, **kw)


def go(mode, prev, cur, **cfg):
    return transition_decision(GroupConfig(mode=mode, **cfg), prev, cur)


# -- The seven examples of the product specification (mode with turn-off configured) --


def test_example_1_dark_unoccupied_to_dark_occupied_is_on() -> None:
    d = go(MODE_TURN_OFF, st(False, D), st(True, D))
    assert d.action is ON


def test_example_2_bright_occupied_to_dark_occupied_is_on() -> None:
    d = go(MODE_TURN_OFF, st(True, B), st(True, D))
    assert d.action is ON


def test_example_3_dark_occupied_to_bright_occupied_is_off_when_configured() -> None:
    assert go(MODE_TURN_OFF, st(True, D), st(True, B)).action is OFF
    assert go(MODE_DARK_ON_BRIGHT_OFF, st(True, D), st(True, B)).action is OFF
    assert go(MODE_REQUIRE_DARK, st(True, D), st(True, B)).action is NONE


def test_example_4_dark_occupied_to_dark_unoccupied_is_off() -> None:
    d = go(MODE_REQUIRE_DARK, st(True, D), st(False, D))
    assert (d.action, d.reason) == (OFF, TransitionReason.VACANCY_OFF)


def test_example_5_unchanged_conditions_give_no_action() -> None:
    assert (
        go(MODE_TURN_OFF, st(True, D), st(True, D)).reason
        is TransitionReason.NO_TRANSITION
    )


def test_example_6_unknown_without_valid_information_gives_no_action() -> None:
    assert go(MODE_REQUIRE_DARK, st(True, D), st(True, U)).action is NONE
    assert go(MODE_REQUIRE_DARK, st(False, D), st(None, D)).action is NONE


def test_example_7_repeated_identical_event_gives_no_action() -> None:
    state = st(True, D)
    assert go(MODE_REQUIRE_DARK, state, state).action is NONE


# -- Every mode, every relevant transition --


@pytest.mark.parametrize(
    ("mode", "prev", "cur", "expected"),
    [
        (MODE_IGNORE, st(False, D), st(True, D), ON),
        (MODE_IGNORE, st(True, D), st(False, D), OFF),
        (
            MODE_IGNORE,
            st(True, B),
            st(True, D),
            NONE,
        ),  # ignore does not react to brightness
        (
            MODE_TURN_OFF,
            st(False, B),
            st(True, B),
            NONE,
        ),  # bright occupied is OFF, no change
        (MODE_TURN_OFF, st(True, D), st(True, B), OFF),
        (
            MODE_TURN_OFF,
            st(True, B),
            st(False, B),
            NONE,
        ),  # already OFF-desired: no command
        (MODE_REQUIRE_DARK, st(False, B), st(True, B), NONE),  # bright: no ON
        (MODE_REQUIRE_DARK, st(False, D), st(True, D), ON),
        (MODE_REQUIRE_DARK, st(True, D), st(False, D), OFF),
        (MODE_DARK_ON_BRIGHT_OFF, st(False, D), st(True, D), ON),
        (MODE_DARK_ON_BRIGHT_OFF, st(True, D), st(True, B), OFF),
        (MODE_DARK_ON_BRIGHT_OFF, st(True, B), st(True, D), ON),
        (MODE_DARK_ON_BRIGHT_OFF, st(True, D), st(False, D), OFF),
    ],
)
def test_mode_transition_table(mode, prev, cur, expected) -> None:
    assert go(mode, prev, cur).action is expected


def test_both_conditions_change_at_once_follow_the_current_state() -> None:
    """Occupancy and brightness change together: the current valid state decides."""
    assert go(MODE_DARK_ON_BRIGHT_OFF, st(False, B), st(True, D)).action is ON
    assert go(MODE_DARK_ON_BRIGHT_OFF, st(True, D), st(False, B)).action is OFF


# -- Hysteresis: the caller applies it; a band reading keeps the previous state --


def test_hysteresis_band_keeps_dark_and_gives_no_transition() -> None:
    """Previous DARK, reading in the band (caller keeps DARK): no transition, no command."""
    assert go(MODE_REQUIRE_DARK, st(True, D), st(True, D)).action is NONE


def test_hysteresis_band_without_previous_state_is_unknown_and_no_action() -> None:
    assert go(MODE_REQUIRE_DARK, None, st(True, U)).action is NONE


# -- UNKNOWN on both sides --


def test_unknown_brightness_never_turns_a_dark_mode_on() -> None:
    assert go(MODE_REQUIRE_DARK, st(True, U), st(True, D)).action is ON
    assert go(MODE_REQUIRE_DARK, st(False, D), st(True, U)).action is NONE


def test_unknown_presence_never_causes_an_action_by_itself() -> None:
    """UNKNOWN as the current state gives no command.

    UNKNOWN as the previous state does not
    block a transition to a valid current state: the current state justifies the command.
    """
    assert go(MODE_TURN_OFF, st(True, D), st(None, D)).action is NONE
    d = go(MODE_TURN_OFF, st(None, D), st(True, D))
    assert (d.action, d.reason) == (ON, TransitionReason.OCCUPIED_ON)


def test_previous_unknown_is_decided_by_the_valid_current_state() -> None:
    """Unknown previous, valid current bright occupied: OFF is justified by the current state."""
    d = go(MODE_TURN_OFF, st(None, U), st(True, B))
    assert (d.action, d.reason) == (OFF, TransitionReason.BRIGHT_OFF)


@pytest.mark.parametrize("override", [Override.FORCE_ON, Override.FORCE_OFF])
def test_released_override_into_vacancy_allows_the_clear_off(override) -> None:
    """The CLEAR ends the override; the vacancy OFF of that transition stays allowed."""
    prev = st(True, D, override=override)
    d = go(MODE_TURN_OFF, prev, st(False, D))
    assert (d.action, d.reason) == (OFF, TransitionReason.VACANCY_OFF)


def test_blocker_released_while_occupied_gives_the_configured_on() -> None:
    """The blocker was active (OFF desired); its release is a state change: ON when configured."""
    prev = st(True, D, blocked=True)
    d = go(MODE_TURN_OFF, prev, st(True, D))
    assert (d.action, d.reason) == (ON, TransitionReason.OCCUPIED_ON)


def test_automation_off_previous_blocks_the_transition() -> None:
    prev = st(False, D, controlling=False)
    assert go(MODE_TURN_OFF, prev, st(True, D)).action is NONE


# -- Override, automation switch, activation, blockers --


@pytest.mark.parametrize("override", [Override.FORCE_ON, Override.FORCE_OFF])
def test_manual_override_suppresses_every_automatic_command(override) -> None:
    d = go(MODE_TURN_OFF, st(False, D), st(True, D, override=override))
    assert d.action is NONE
    assert d.reason is TransitionReason.MANUAL_OVERRIDE


def test_automation_switch_off_suppresses_commands() -> None:
    d = go(MODE_TURN_OFF, st(False, D), st(True, D, controlling=False))
    assert (d.action, d.reason) == (NONE, TransitionReason.AUTOMATION_OFF)


def test_disabled_activation_never_acts() -> None:
    d = go(MODE_TURN_OFF, st(False, D), st(True, D), activation_enabled=False)
    assert (d.action, d.reason) == (NONE, TransitionReason.ACTIVATION_DISABLED)


def test_blocker_while_occupied_switches_off_and_never_on() -> None:
    """Existing blocker semantics: occupied and blocked gives OFF; a blocker never starts ON."""
    assert (
        go(MODE_TURN_OFF, st(False, D, blocked=True), st(True, D, blocked=True)).action
        is NONE
    )
    d = go(MODE_TURN_OFF, st(True, D), st(True, D, blocked=True))
    assert (d.action, d.reason) == (OFF, TransitionReason.BLOCKER_OFF)
    assert go(MODE_TURN_OFF, st(False, D), st(True, D, blocked=True)).action is NONE


def test_non_matching_activation_never_switches_on() -> None:
    """Non-matching activation behaves like a blocker: it can switch OFF, never ON."""
    assert (
        go(MODE_TURN_OFF, st(False, D), st(True, D, activation_matches=False)).action
        is NONE
    )
    d = go(MODE_TURN_OFF, st(True, D), st(True, D, activation_matches=False))
    assert (d.action, d.reason) == (OFF, TransitionReason.BLOCKER_OFF)


# -- Output contract --


def test_decision_is_pure_and_repeatable() -> None:
    prev, cur = st(False, D), st(True, D)
    assert go(MODE_TURN_OFF, prev, cur) == go(MODE_TURN_OFF, prev, cur)


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError):
        transition_decision(GroupConfig(mode="teleport"), st(False, D), st(True, D))


def test_at_most_one_command_per_transition() -> None:
    """A transition yields one decision; the same pair again yields NO_ACTION (no retry)."""
    prev, cur = st(False, D), st(True, D)
    first = go(MODE_TURN_OFF, prev, cur)
    second = go(MODE_TURN_OFF, cur, cur)
    assert first.action is ON and second.action is NONE


# -- Initial decision (setup and reload), kept separate from transitions --


@pytest.mark.parametrize(
    ("mode", "state", "expected"),
    [
        (MODE_REQUIRE_DARK, st(True, D), ON),  # startup DARK + OCCUPIED
        (MODE_TURN_OFF, st(True, B), OFF),  # startup BRIGHT + OCCUPIED
        (MODE_TURN_OFF, st(True, U), ON),  # startup UNKNOWN brightness, turn_off
        (
            MODE_REQUIRE_DARK,
            st(True, U),
            NONE,
        ),  # startup UNKNOWN brightness, require_dark
        (MODE_REQUIRE_DARK, st(None, D), NONE),  # startup UNKNOWN presence
        (MODE_TURN_OFF, st(False, D), OFF),  # startup vacancy
    ],
)
def test_startup_initial_decision(mode, state, expected) -> None:
    d = initial_decision(GroupConfig(mode=mode), state)
    assert d.action is expected
    assert d.kind == "initial"


def test_initial_decision_without_state_is_no_action() -> None:
    assert initial_decision(GroupConfig(mode=MODE_TURN_OFF), None).action is NONE


def test_reload_takes_one_initial_decision_from_the_current_state() -> None:
    """Reload is a setup again: the current valid state gives exactly one initial decision."""
    assert (
        initial_decision(GroupConfig(mode=MODE_REQUIRE_DARK), st(True, D)).action is ON
    )


def test_initial_decision_is_not_a_transition_decision() -> None:
    """A transition needs a previous state; the initial decision never does."""
    assert go(MODE_TURN_OFF, None, st(True, D)).action is NONE
    assert initial_decision(GroupConfig(mode=MODE_TURN_OFF), st(True, D)).action is ON


# -- Override end, concurrent changes, repetition --


def test_override_end_in_occupation_does_not_replay_an_on() -> None:
    """Override holds an occupied light; when it ends while still occupied, no ON is replayed."""
    held = st(True, D, override=Override.FORCE_OFF)
    assert go(MODE_TURN_OFF, held, st(True, D)).action is NONE


def test_override_end_then_a_later_real_transition_acts_normally() -> None:
    held = st(True, D, override=Override.FORCE_OFF)
    released = st(True, D)
    later = st(False, D)
    assert go(MODE_TURN_OFF, held, released).action is NONE
    assert go(MODE_TURN_OFF, released, later).action is OFF


def test_concurrent_presence_and_brightness_change_follow_the_current_state() -> None:
    """Occupancy and brightness change together: the current state decides once."""
    assert (
        go(MODE_TURN_OFF, st(False, D), st(True, B)).action is NONE
    )  # OFF desired both times
    assert go(MODE_REQUIRE_DARK, st(False, B), st(True, D)).action is ON


def test_repeated_identical_events_never_repeat_a_command() -> None:
    first = go(MODE_REQUIRE_DARK, st(False, D), st(True, D))
    repeat = go(MODE_REQUIRE_DARK, st(True, D), st(True, D))
    assert first.action is ON and repeat.action is NONE


def test_turn_off_with_unknown_brightness_allows_occupancy_on() -> None:
    assert go(MODE_TURN_OFF, st(False, U), st(True, U)).action is ON


# -- Execution: one attempt, no retry --


async def test_failed_service_call_is_not_retried() -> None:
    decision = go(MODE_TURN_OFF, st(False, D), st(True, D))
    calls: list = []

    async def failing(action) -> None:
        calls.append(action)
        raise RuntimeError("service failed")

    assert await execute_once(decision, failing) == "failed"
    assert calls == [ON]


async def test_successful_call_is_issued_once_and_no_call_without_action() -> None:
    decision = go(MODE_TURN_OFF, st(False, D), st(True, D))
    calls: list = []

    async def succeeding(action) -> None:
        calls.append(action)

    assert await execute_once(decision, succeeding) == "succeeded"
    no_action = go(MODE_TURN_OFF, st(True, D), st(True, D))
    assert await execute_once(no_action, succeeding) == "not_executed"
    assert calls == [ON]


# -- Single owner per physical light (deterministic rule) --


def test_light_in_a_group_is_owned_by_the_group() -> None:
    owner = light_owner("light.a", {"overhead": ["light.a"]})
    assert (owner.owner, owner.groups, owner.reason) == (
        "group",
        ("overhead",),
        "group_member",
    )


def test_light_outside_every_group_has_no_automatic_owner() -> None:
    """Policy-only is removed: a lamp in no group is never an automatic target."""
    owner = light_owner("light.b", {"overhead": ["light.a"]})
    assert owner.owner == "none"


def test_light_in_several_groups_of_one_area_is_reported() -> None:
    owner = light_owner("light.a", {"overhead": ["light.a"], "sleep": ["light.a"]})
    assert owner.owner == "group"
    assert owner.groups == ("overhead", "sleep")
    assert owner.reason == "multiple_groups_same_area"


def test_light_outside_both_is_not_automatic() -> None:
    assert light_owner("light.z", {"overhead": ["light.a"]}).owner == "none"
