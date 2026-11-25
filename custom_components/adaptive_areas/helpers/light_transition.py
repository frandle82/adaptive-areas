"""Pure transition decision for one automatic light group (not wired into production).

Configuration and the current valid state decide. An automatic light command is issued only
when the configured condition changes through a relevant state transition: the desired
state derived from the previous valid state differs from the one derived from the current
valid state. No state, no change, no command. The function never calls Home Assistant.

Rules of the shared group decision path (transitions only):
- vacancy (occupied False) desires OFF for every brightness mode;
- occupied True and brightness BRIGHT desires OFF for turn_off and dark_on_bright_off;
- occupied True desires ON for ignore and turn_off (brightness independent, occupancy only);
- occupied True desires ON for require_dark and dark_on_bright_off only with DARK;
- brightness UNKNOWN never desires ON for a brightness-dependent mode;
- an active manual override, a disabled automation or a disabled activation suppress all
  automatic commands;
- a blocked or non-matching activation vetoes ON but not the vacancy OFF.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from custom_components.adaptive_areas.helpers.brightness import BrightnessState

MODE_IGNORE = "ignore"
MODE_REQUIRE_DARK = "require_dark"
MODE_TURN_OFF = "turn_off"
MODE_DARK_ON_BRIGHT_OFF = "dark_on_bright_off"
MODES = (MODE_IGNORE, MODE_REQUIRE_DARK, MODE_TURN_OFF, MODE_DARK_ON_BRIGHT_OFF)


class Override(StrEnum):
    """Confirmed manual override state for one target."""

    NONE = "none"
    FORCE_ON = "force_on"
    FORCE_OFF = "force_off"


class TransitionAction(StrEnum):
    """Outcome of one transition decision."""

    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    NO_ACTION = "no_action"


class TransitionReason(StrEnum):
    """Stable, traceable reason codes (no personal data)."""

    VACANCY_OFF = "vacancy_off"
    OCCUPIED_ON = "occupied_on"
    BRIGHT_OFF = "bright_off"
    DARK_ON = "dark_on"
    NO_TRANSITION = "no_transition"
    NO_PREVIOUS_STATE = "no_previous_state"
    NO_CURRENT_STATE = "no_current_state"
    UNKNOWN_INPUT = "unknown_input"
    MANUAL_OVERRIDE = "manual_override"
    AUTOMATION_OFF = "automation_off"
    ACTIVATION_DISABLED = "activation_disabled"
    BLOCKER_OFF = "blocker_off"
    BLOCKED_ON_VETO = "blocked_on_veto"
    INITIAL = "initial"
    BRIGHTNESS_NOT_DARK = "brightness_not_dark"
    AUTOMATIC_ON_DISABLED = "automatic_on_disabled"


@dataclass(frozen=True, slots=True)
class GroupConfig:
    """Configured behaviour of one light group (from the options, never from state)."""

    mode: str
    activation_enabled: bool = True
    # False for the ALL group: it is switched off on vacancy only, never on automatically.
    allow_on: bool = True


@dataclass(frozen=True, slots=True)
class AreaState:
    """One valid decision input at one point in time.

    occupied: True, False, or None when presence is unknown.
    brightness: DARK, BRIGHT, or UNKNOWN (hysteresis already applied by the caller).
    activation_matches: the configured activation state is active.
    blocked: a configured blocker state is active.
    controlling: the automation switch allows control.
    override: an active manual override (FORCE_ON or FORCE_OFF) suppresses automation.
    """

    occupied: bool | None
    brightness: BrightnessState
    activation_matches: bool = True
    blocked: bool = False
    controlling: bool = True
    override: Override = Override.NONE


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    """Single decision for one transition (or the one initial decision), with its reason."""

    action: TransitionAction
    reason: TransitionReason
    kind: str = "transition"  # "transition" or "initial"


def _desired(
    config: GroupConfig, state: AreaState
) -> tuple[bool | None, TransitionReason | None]:
    """Desired light state (True ON, False OFF, None no statement) with the reason.

    Returns (None, reason) when the state gives no automatic statement.
    """
    if not config.activation_enabled:
        return None, TransitionReason.ACTIVATION_DISABLED
    if state.override is not Override.NONE:
        return None, TransitionReason.MANUAL_OVERRIDE
    if not state.controlling:
        return None, TransitionReason.AUTOMATION_OFF
    if state.occupied is None:
        return None, TransitionReason.UNKNOWN_INPUT
    if state.occupied is False:
        return False, TransitionReason.VACANCY_OFF
    # Occupied from here on.
    if not config.allow_on:
        # No automatic ON for this group: the occupied state gives no statement. A vacancy
        # OFF after it is still a valid transition (see _previous_allows_transition).
        return None, TransitionReason.AUTOMATIC_ON_DISABLED
    if state.brightness is BrightnessState.BRIGHT and config.mode in (
        MODE_TURN_OFF,
        MODE_DARK_ON_BRIGHT_OFF,
    ):
        return False, TransitionReason.BRIGHT_OFF
    if state.blocked or not state.activation_matches:
        # Existing blocker semantics: an active blocker while occupied switches the group OFF
        # and never ON. The vacancy OFF above applies without a blocker.
        return False, TransitionReason.BLOCKER_OFF
    if config.mode in (MODE_IGNORE, MODE_TURN_OFF):
        return True, TransitionReason.OCCUPIED_ON
    # require_dark and dark_on_bright_off: ON only with a known DARK reading.
    if state.brightness is BrightnessState.DARK:
        return True, TransitionReason.DARK_ON
    if state.brightness is BrightnessState.UNKNOWN:
        return None, TransitionReason.UNKNOWN_INPUT
    return None, TransitionReason.BRIGHTNESS_NOT_DARK


def _previous_allows_transition(before_reason: TransitionReason | None) -> bool:
    """Whether a previous state without a desire can still start a transition.

    Unknown input and a neutral brightness (BRIGHT under require_dark) carry no suppression:
    the current valid state decides. Manual override, automation off and disabled activation
    suppress the previous state, so releasing them never replays a suppressed command.
    """
    return before_reason in (
        TransitionReason.UNKNOWN_INPUT,
        TransitionReason.BRIGHTNESS_NOT_DARK,
        TransitionReason.AUTOMATIC_ON_DISABLED,
    )


def transition_decision(
    config: GroupConfig,
    previous: AreaState | None,
    current: AreaState | None,
) -> TransitionDecision:
    """Decide the single automatic command, if any, for one state transition.

    Pure and deterministic. At most one command per transition: the caller issues the
    command returned here once and never retries it.
    """
    if config.mode not in MODES:
        raise ValueError(f"unknown light group mode: {config.mode!r}")
    if current is None:
        return TransitionDecision(
            TransitionAction.NO_ACTION, TransitionReason.NO_CURRENT_STATE
        )
    if previous is None:
        return TransitionDecision(
            TransitionAction.NO_ACTION, TransitionReason.NO_PREVIOUS_STATE
        )
    if previous == current:
        return TransitionDecision(
            TransitionAction.NO_ACTION, TransitionReason.NO_TRANSITION
        )
    if current.override is not Override.NONE:
        return TransitionDecision(
            TransitionAction.NO_ACTION, TransitionReason.MANUAL_OVERRIDE
        )

    now, reason = _desired(config, current)
    before, _before_reason = _desired(config, previous)
    if now is None:
        return TransitionDecision(
            TransitionAction.NO_ACTION, reason or TransitionReason.UNKNOWN_INPUT
        )
    # A manual override that ended with a CLEAR (now: vacancy) still allows the OFF of that
    # transition. It never allows an ON, so nothing is replayed from the override.
    released_override_off = (
        _before_reason is TransitionReason.MANUAL_OVERRIDE and now is False
    )
    if before is None and not (
        _previous_allows_transition(_before_reason) or released_override_off
    ):
        # A suppressed previous state (override, automation off, activation disabled, or a
        # veto followed by an ON) is no basis for a transition: no command from it.
        return TransitionDecision(
            TransitionAction.NO_ACTION, TransitionReason.NO_PREVIOUS_STATE
        )
    if before == now:
        return TransitionDecision(
            TransitionAction.NO_ACTION, TransitionReason.NO_TRANSITION
        )
    action = TransitionAction.TURN_ON if now else TransitionAction.TURN_OFF
    return TransitionDecision(action, reason or TransitionReason.NO_TRANSITION)


def initial_decision(
    config: GroupConfig, current: AreaState | None
) -> TransitionDecision:
    """Return the single initial decision at setup or reload, from the current valid state.

    It is separate from transition decisions: there is no previous state, so the current
    valid state alone decides (for example DARK + OCCUPIED gives ON). It is taken once per
    setup or reload and never repeated for the same state.
    """
    if config.mode not in MODES:
        raise ValueError(f"unknown light group mode: {config.mode!r}")
    if current is None:
        return TransitionDecision(
            TransitionAction.NO_ACTION, TransitionReason.NO_CURRENT_STATE, "initial"
        )
    now, reason = _desired(config, current)
    if now is None:
        return TransitionDecision(
            TransitionAction.NO_ACTION,
            reason or TransitionReason.UNKNOWN_INPUT,
            "initial",
        )
    action = TransitionAction.TURN_ON if now else TransitionAction.TURN_OFF
    return TransitionDecision(action, reason or TransitionReason.INITIAL, "initial")


async def execute_once(decision: TransitionDecision, service_call) -> str:
    """Issue the decided command at most once. A failure is reported, never retried.

    `service_call` is an injected asynchronous callable taking the action. Without an
    action there is no call. The return value is "not_executed", "succeeded" or "failed".
    """
    if decision.action is TransitionAction.NO_ACTION:
        return "not_executed"
    try:
        await service_call(decision.action)
    except Exception:  # noqa: BLE001 - any failure ends the attempt, nothing is retried
        return "failed"
    return "succeeded"


@dataclass(frozen=True, slots=True)
class LightOwner:
    """Deterministic owner of one physical light inside one Area."""

    owner: str  # "group" or "none"
    groups: tuple[str, ...] = ()
    reason: str = ""


def light_owner(
    light: str,
    group_members: Mapping[str, Iterable[str]],
) -> LightOwner:
    """Decide which automatic path owns a physical light: exactly one path, never two.

    - In at least one configured group of this Area: the group owns it (its group
      configuration is decisive). Several groups of the same Area are allowed; they are
      reported as ``multiple_groups_same_area``.
    - Otherwise: no automatic owner. A lamp outside every group is never switched automatically.
    Cross-Area ownership is an invalid configuration and is refused by the ownership check.
    """
    groups = tuple(
        sorted(name for name, members in group_members.items() if light in set(members))
    )
    if groups:
        reason = "multiple_groups_same_area" if len(groups) > 1 else "group_member"
        return LightOwner("group", groups, reason)
    return LightOwner("none", (), "not_a_target")
