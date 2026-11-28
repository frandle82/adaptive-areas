"""Phase J.3: deterministic light lifecycle and Meta presence unload (L01-L36).

Rules under test (decided for RC.5):

A. A manual override is a runtime state of one setup generation. It is never restored at
   setup: a restart and an integration reload start without it.
B. The initial decision of a light group is completed only when its inputs exist: the
   native group is available, the light control switch is registered, presence is known
   and, where the decision needs it, the brightness is known. It runs at most once per
   setup generation, from the state at that moment; nothing earlier is replayed.
C. Every timer and pending evaluation of a presence entity ends with its unload.

The setup is the exact HAOS layout of Phase J.2 (template light helper on
`input_boolean.licht`, GlobalEntry, "Arbeitszimmer", Meta "global"); see
tests/test_light_template_helper.py. Everything runs on the real Home Assistant components.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import Context, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError

from custom_components.adaptive_areas import light as aa_light
from custom_components.adaptive_areas.binary_sensor import presence as aa_presence
from custom_components.adaptive_areas.const import (
    EVENT_ADAPTIVEAREAS_AREA_STATE_CHANGED,
)
from custom_components.adaptive_areas.dashboard import build_decision_trace
from custom_components.adaptive_areas.helpers.area import iter_runtime_areas
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from tests.service_faults import install_group_command_fault
from tests.test_light_template_helper import (
    ALL,
    BOOL,
    BRIGHT,
    DARK,
    GROUP,
    LAMP,
    META_ALL,
    MOTION,
    PRESENCE,
    SWITCH,
    Calls,
    _advance,
    _area,
    _clear,
    _lux,
    _no_override,
    _override,
    _setup,
)

STORED_OVERRIDE = [
    State(GROUP, STATE_OFF, {"manual_override": True, "controlling": True}),
    State(ALL, STATE_OFF, {"manual_override": True, "controlling": True}),
]
OCCUPIED_DARK = State(PRESENCE, STATE_ON, {"states": ["occupied", "extended", "dark"]})


def _groups(hass: HomeAssistant) -> dict[str, aa_light.AreaLightGroup]:
    return {
        entity.entity_id: entity
        for entity in hass.data["light"].entities
        if isinstance(entity, aa_light.AreaLightGroup)
    }


def _initial(hass: HomeAssistant, group: str = "accent_lights") -> list[tuple]:
    """Initial-trigger entries of one group, oldest first: (decision, outcome, reasons)."""
    entries = build_decision_trace(_area(hass))["entries"]
    return [
        (entry["decision"], entry["outcome"], entry["reason_codes"])
        for entry in reversed(entries)
        if entry["trigger"] == "initial" and entry["group"] == group
    ]


def _completed(hass: HomeAssistant, group: str = "accent_lights") -> list[tuple]:
    return [item for item in _initial(hass, group) if "initial_pending" not in item[2]]


async def _user_off(hass: HomeAssistant) -> None:
    user = await hass.auth.async_create_user("phase-j3", group_ids=["system-admin"])
    await hass.services.async_call(
        "light",
        "turn_off",
        {ATTR_ENTITY_ID: LAMP},
        blocking=True,
        context=Context(user_id=user.id),
    )
    await hass.async_block_till_done()


def _force_platform_order(monkeypatch: pytest.MonkeyPatch, first: str) -> None:
    """Make the presence or the light entities finish their setup first (deterministic)."""
    done = asyncio.Event()
    classes = {
        "presence": aa_presence.AreaStateBinarySensor,
        "light": aa_light.AreaLightGroup,
    }
    leader = classes[first]
    follower = classes["light" if first == "presence" else "presence"]
    leader_added, follower_added = (
        leader.async_added_to_hass,
        follower.async_added_to_hass,
    )

    async def _leader(self) -> None:
        await leader_added(self)
        done.set()

    async def _follower(self) -> None:
        await done.wait()
        await follower_added(self)

    monkeypatch.setattr(leader, "async_added_to_hass", _leader)
    monkeypatch.setattr(follower, "async_added_to_hass", _follower)


# L01, L02, L06, L07, L13: no restored override, in both platform orders ---------------


@pytest.mark.parametrize("run", range(3))
@pytest.mark.parametrize("first", ["presence", "light"])
@pytest.mark.parametrize("occupied", [True, False])
async def test_l01_l02_l06_l07_l13_restart_never_restores_an_override(
    hass: HomeAssistant, hass_storage, monkeypatch, first: str, occupied: bool, run: int
) -> None:
    """L01/L02/L06/L07/L13: RC.4 attributes `manual_override=true` are not used at setup.

    Restored occupied and dark: the lamp switches on once the group is available. Restored
    free: nothing is switched on. Same result for both platform orders, every run.
    """
    _force_platform_order(monkeypatch, first)
    entry = await _setup(
        hass,
        hass_storage,
        lux=DARK,
        motion=STATE_ON if occupied else STATE_OFF,
        restore=[
            State(
                PRESENCE,
                STATE_ON if occupied else STATE_OFF,
                {"states": ["occupied", "extended", "dark"] if occupied else ["clear"]},
            ),
            *[
                State(s.entity_id, s.state, {**s.attributes, "controlling": False})
                for s in STORED_OVERRIDE
            ],
        ],
    )
    try:
        _no_override(hass)
        for group in _groups(hass).values():
            assert group.controlling is True
        assert hass.states.get(LAMP).state == (STATE_ON if occupied else STATE_OFF)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_l03_restart_with_unknown_presence_switches_nothing(
    hass: HomeAssistant, hass_storage
) -> None:
    """L03: presence source unavailable at restart: no old override, no switching."""
    entry = await _setup(
        hass,
        hass_storage,
        lux=DARK,
        motion=STATE_UNAVAILABLE,
        restore=[OCCUPIED_DARK, *STORED_OVERRIDE],
    )
    try:
        _no_override(hass)
        assert hass.states.get(BOOL).state == STATE_OFF
        assert _completed(hass) == []
        assert ("no_action", "skipped", ["initial_pending", "unknown_input"]) in (
            _initial(hass)
        )
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# L04, L05: a reload ends an override on purpose ---------------------------------------


async def test_l04_l05_reload_ends_a_valid_override_and_decides_again(
    hass: HomeAssistant, hass_storage
) -> None:
    """L04/L05: a user OFF while occupied and dark; each reload ends the override.

    The regular initial decision of the new generation then switches the lamp on (dark and
    occupied). Two more reloads change nothing: the lamp is on, no second ON is sent.
    """
    entry = await _setup(hass, hass_storage)
    try:
        await _lux(hass, DARK)
        await _user_off(hass)
        assert _override(hass, GROUP)
        calls = Calls(hass)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        _no_override(hass)
        assert hass.states.get(LAMP).state == STATE_ON
        assert calls.booleans() == ["input_boolean.turn_on"]
        for _reload in range(2):
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            _no_override(hass)
        assert calls.booleans() == ["input_boolean.turn_on"]
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# L09, L10, L11: a runtime override keeps until CLEAR ------------------------------------


async def test_l09_l10_l11_override_survives_activity_and_extended_until_clear(
    hass: HomeAssistant, hass_storage, freezer
) -> None:
    """L09/L10/L11: brightness, presence activity and extended keep it; CLEAR ends it."""
    entry = await _setup(hass, hass_storage)
    try:
        await _lux(hass, DARK)
        await _user_off(hass)
        calls = Calls(hass)
        await _lux(hass, BRIGHT)
        await _lux(hass, DARK)
        await _advance(hass, freezer, 6)
        hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion", "seq": 1})
        await hass.async_block_till_done()
        assert _area(hass).has_state("extended")
        assert _override(hass, GROUP)
        assert calls.booleans() == []
        hass.states.async_set(MOTION, STATE_OFF, {"device_class": "motion"})
        await hass.async_block_till_done()
        await _advance(hass, freezer, 11)  # extended timeout
        assert not _area(hass).is_occupied()
        _no_override(hass)
        await _advance(hass, freezer, 11)  # the Meta Area's own extended timeout
        assert not any(area.is_occupied() for area in iter_runtime_areas(hass))
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# L15-L18: the initial decision waits for the native group ------------------------------


@pytest.mark.parametrize(
    ("change", "expected", "booleans"),
    [
        (None, STATE_ON, ["input_boolean.turn_on"]),  # L15/L16
        ("bright", STATE_OFF, []),  # L17: no stale ON
    ],
)
async def test_l15_l16_l17_initial_decision_when_the_group_becomes_available(
    hass: HomeAssistant, hass_storage, change: str | None, expected: str, booleans
) -> None:
    """L15/L16/L17: the decision uses the state at availability, never an earlier one."""
    calls: Calls | None = None

    async def _before_start() -> None:
        nonlocal calls
        assert hass.states.get(GROUP).state == STATE_UNAVAILABLE
        assert _completed(hass) == []
        calls = Calls(hass)
        if change == "bright":
            await _lux(hass, BRIGHT)

    entry = await _setup(hass, hass_storage, lux=DARK, before_start=_before_start)
    try:
        assert hass.states.get(LAMP).state == expected
        assert calls is not None and calls.booleans() == booleans
        completed = _completed(hass)
        assert len(completed) == 1
        assert ("no_action", "skipped", ["initial_pending", "group_unavailable"]) in (
            _initial(hass)
        )
        _no_override(hass)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_l18_initial_decision_of_a_free_area_applies_the_clear_rule(
    hass: HomeAssistant, hass_storage
) -> None:
    """L18: restored on, the Area is free at availability: one OFF, no duplicate."""
    calls: Calls | None = None

    async def _before_start() -> None:
        nonlocal calls
        calls = Calls(hass)

    entry = await _setup(
        hass,
        hass_storage,
        lux=DARK,
        motion=STATE_OFF,
        restore=[
            State(BOOL, STATE_ON),
            State(PRESENCE, STATE_OFF, {"states": ["clear", "dark"]}),
        ],
        before_start=_before_start,
    )
    try:
        assert calls is not None and calls.booleans() == ["input_boolean.turn_off"]
        assert hass.states.get(LAMP).state == STATE_OFF
        assert hass.states.get(BOOL).state == STATE_OFF
        _no_override(hass)
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# L19, L20, L22: unknown inputs keep the initial decision open --------------------------


async def test_l19_l20_unknown_presence_waits_until_presence_is_known(
    hass: HomeAssistant, hass_storage
) -> None:
    """L19/L20: group available, presence unknown: no decision; known occupied: one ON."""
    entry = await _setup(hass, hass_storage, lux=DARK, motion=STATE_UNAVAILABLE)
    try:
        calls = Calls(hass)
        assert _completed(hass) == []
        assert hass.states.get(LAMP).state == STATE_OFF
        hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion"})
        await hass.async_block_till_done()
        assert hass.states.get(LAMP).state == STATE_ON
        assert calls.booleans() == ["input_boolean.turn_on"]
        assert len(_completed(hass)) == 1
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_l22_unknown_brightness_waits_for_a_reading(
    hass: HomeAssistant, hass_storage
) -> None:
    """L22: `dark_on_bright_off` needs the brightness for an ON; the first DARK switches on."""
    entry = await _setup(hass, hass_storage, lux="unknown")
    try:
        calls = Calls(hass)
        assert _completed(hass) == []
        assert ("no_action", "skipped", ["initial_pending", "unknown_input"]) in (
            _initial(hass)
        )
        await _lux(hass, DARK)
        assert hass.states.get(LAMP).state == STATE_ON
        assert calls.booleans() == ["input_boolean.turn_on"]
        assert len(_completed(hass)) == 1
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_l23_clear_with_unknown_brightness_still_switches_off(
    hass: HomeAssistant, hass_storage, freezer
) -> None:
    """L23: an unknown brightness never blocks the vacancy OFF."""
    entry = await _setup(hass, hass_storage)
    try:
        await _lux(hass, DARK)
        assert hass.states.get(LAMP).state == STATE_ON
        await _lux(hass, "unknown")
        calls = Calls(hass)
        await _clear(hass, freezer)
        assert hass.states.get(LAMP).state == STATE_OFF
        assert calls.booleans() == ["input_boolean.turn_off"]
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# L21, L24, L25: switch, target state, NO_ACTION -----------------------------------------


async def test_l21_switch_off_at_setup_then_on_uses_the_regular_rule(
    hass: HomeAssistant, hass_storage
) -> None:
    """L21: automation off at setup completes the decision; switching it on decides now."""
    entry = await _setup(hass, hass_storage, lux=DARK, switch=STATE_OFF)
    try:
        assert _completed(hass) == [("no_action", "skipped", ["automation_off"])]
        assert hass.states.get(LAMP).state == STATE_OFF
        calls = Calls(hass)
        await hass.services.async_call(
            "switch", "turn_on", {ATTR_ENTITY_ID: SWITCH}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get(LAMP).state == STATE_ON
        assert calls.booleans() == ["input_boolean.turn_on"]
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_l24_group_already_in_the_target_state_gets_no_call(
    hass: HomeAssistant, hass_storage
) -> None:
    """L24: restored on, dark and occupied: the initial ON is not sent again."""

    calls: Calls | None = None

    async def _before_start() -> None:
        nonlocal calls
        calls = Calls(hass)

    entry = await _setup(
        hass,
        hass_storage,
        lux=DARK,
        restore=[State(BOOL, STATE_ON), OCCUPIED_DARK],
        before_start=_before_start,
    )
    try:
        assert hass.states.get(LAMP).state == STATE_ON
        assert calls is not None and calls.plain() == []
        assert _completed(hass) == [("turn_on", "skipped", ["already_on"])]
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_l25_l30_all_group_initial_no_action_completes(
    hass: HomeAssistant, hass_storage
) -> None:
    """L25/L30: occupied: the ALL group decides NO_ACTION once; ALL and Meta ALL never ON."""
    entry = await _setup(hass, hass_storage, lux=DARK)
    try:
        assert _completed(hass, "all_lights") == [
            ("no_action", "skipped", ["automatic_on_disabled"])
        ]
        assert _groups(hass)[ALL]._initial_done is True
        calls = Calls(hass)
        await _lux(hass, BRIGHT)
        await _lux(hass, DARK)
        assert not [c for c in calls.plain() if c[1] in (ALL, META_ALL)]
        assert len(_completed(hass, "all_lights")) == 1
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# L26, L27: one initial decision per generation -----------------------------------------


async def test_l26_l27_one_initial_decision_despite_repeated_availability(
    hass: HomeAssistant, hass_storage
) -> None:
    """L26/L27: availability reports and a later dropout of the lamp add no decision."""
    entry = await _setup(hass, hass_storage, lux=DARK)
    try:
        group = _groups(hass)[GROUP]
        calls = Calls(hass)
        for _repeat in range(3):
            group.async_write_ha_state()
        (template_entry,) = hass.config_entries.async_entries("template")
        assert await hass.config_entries.async_reload(template_entry.entry_id)
        await hass.async_block_till_done()
        assert len(_completed(hass)) == 1
        assert [i for i in _initial(hass) if "initial_pending" in i[2]][-1:] == [
            ("no_action", "skipped", ["initial_pending", "group_unavailable"])
        ]
        assert calls.booleans() == []
        assert hass.states.get(LAMP).state == STATE_ON
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# L28: a real service failure is reported, never retried --------------------------------


async def test_l28_failed_initial_call_is_not_retried(
    hass: HomeAssistant, hass_storage, monkeypatch
) -> None:
    """L28: the initial ON fails; repeated identical events send no second ON."""
    attempts: list[str] = []

    async def _fail(_hass, target, service, *, context) -> None:
        attempts.append(f"{service} {target}")
        raise HomeAssistantError("device offline")

    install_group_command_fault(monkeypatch, hass, _fail)
    entry = await _setup(hass, hass_storage, lux=DARK)
    try:
        assert attempts == [f"turn_on {GROUP}"]
        assert _completed(hass) == [("turn_on", "failed", ["action_failed"])]
        hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion", "seq": 1})
        await hass.async_block_till_done()
        await _lux(hass, DARK)
        assert attempts == [f"turn_on {GROUP}"]
        assert hass.states.get(LAMP).state == STATE_OFF
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# L29: reload before the initial decision ----------------------------------------------


async def test_l29_reload_before_start_leaves_no_old_generation(
    hass: HomeAssistant, hass_storage
) -> None:
    """L29: reloaded before Home Assistant has started: exactly one ON, from the new one."""
    calls: Calls | None = None
    old: dict[str, Any] = {}

    async def _before_start() -> None:
        nonlocal calls
        (entry,) = hass.config_entries.async_entries("adaptive_areas")
        old.update(_groups(hass))
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        calls = Calls(hass)

    entry = await _setup(hass, hass_storage, lux=DARK, before_start=_before_start)
    try:
        assert calls is not None and calls.booleans() == ["input_boolean.turn_on"]
        assert all(group._active is False for group in old.values())
        assert all(group._initial_done is False for group in old.values())
        assert set(_groups(hass)) == set(old)
        assert not set(map(id, _groups(hass).values())) & set(map(id, old.values()))
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


# L31-L36: Meta presence lifecycle ------------------------------------------------------


def _presence_handles(hass: HomeAssistant) -> list[Any]:
    """Scheduled loop timers that call back into an Adaptive Areas presence entity."""
    return [
        handle
        for handle in hass.loop._scheduled  # noqa: SLF001 - test-only inspection
        if not handle.cancelled() and "AreaStateTrackerEntity" in repr(handle)
    ]


async def _extended(hass: HomeAssistant, freezer) -> None:
    await _advance(hass, freezer, 6)
    hass.states.async_set(MOTION, STATE_ON, {"device_class": "motion", "seq": 1})
    await hass.async_block_till_done()
    assert all(area.has_state("extended") for area in iter_runtime_areas(hass))


@pytest.mark.parametrize("floor", [False, True])
async def test_l31_l32_l34_unload_while_extended_leaves_no_timer(
    hass: HomeAssistant, hass_storage, freezer, floor: bool
) -> None:
    """L31/L32/L34: Global (and a floor Meta Area) extended at unload: nothing survives.

    On 8c605f3 the Meta presence entity started its 10-minute clear timer after its own
    cleanup (a pending evaluation ran after removal); the test harness reports it as a
    lingering timer.
    """
    entry = await _setup(hass, hass_storage, floor=floor)
    events: list[str] = []
    unsubscribe = async_dispatcher_connect(
        hass,
        EVENT_ADAPTIVEAREAS_AREA_STATE_CHANGED,
        callback(lambda area_id, _states: events.append(area_id)),
    )
    try:
        await _extended(hass, freezer)
        assert len(list(iter_runtime_areas(hass))) == (3 if floor else 2)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
        assert _presence_handles(hass) == []
        events.clear()
        await _advance(hass, freezer, 30)
        assert events == []
    finally:
        unsubscribe()


async def test_l33_l36_reloads_while_extended_keep_one_timer_generation(
    hass: HomeAssistant, hass_storage, freezer
) -> None:
    """L33/L36: three reloads while extended; then CLEAR works from the new generation."""
    entry = await _setup(hass, hass_storage)
    try:
        await _extended(hass, freezer)
        listeners: list[dict[str, int]] = []
        for _reload in range(3):
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
            assert len(_presence_handles(hass)) <= len(list(iter_runtime_areas(hass)))
            listeners.append(hass.bus.async_listeners())
        # No listener of an old generation survives a reload.
        assert listeners[0] == listeners[1] == listeners[2]
        await _lux(hass, DARK)
        assert hass.states.get(LAMP).state == STATE_ON
        hass.states.async_set(MOTION, STATE_OFF, {"device_class": "motion"})
        await hass.async_block_till_done()
        await _advance(hass, freezer, 11)
        assert hass.states.get(LAMP).state == STATE_OFF
        await _advance(hass, freezer, 11)
        assert not any(area.is_occupied() for area in iter_runtime_areas(hass))
    finally:
        await hass.config_entries.async_unload(entry.entry_id)


async def test_l35_failed_setup_rolls_back_presence_timers(
    hass: HomeAssistant, hass_storage, monkeypatch
) -> None:
    """L35: setup fails after every platform is up and a clear timer is running.

    The failure is injected after the real platform forward of Adaptive Areas, so the
    existing rollback path (`_async_rollback_setup`) has to stop the presence timers.
    """
    started: list[int] = []
    original_timer = aa_presence.AreaStateTrackerEntity._set_clear_timeout
    real_forward = hass.config_entries.async_forward_entry_setups

    def _set(self):
        started.append(1)
        return original_timer(self)

    async def _forward_then_fail(entry, platforms):
        await real_forward(entry, platforms)
        if entry.domain == "adaptive_areas":
            raise RuntimeError("injected failure after the platform setup")

    monkeypatch.setattr(aa_presence.AreaStateTrackerEntity, "_set_clear_timeout", _set)
    monkeypatch.setattr(
        hass.config_entries, "async_forward_entry_setups", _forward_then_fail
    )
    with pytest.raises(AssertionError):
        # Occupied restored, motion off now: presence schedules its clear timeout.
        await _setup(hass, hass_storage, motion=STATE_OFF, restore=[OCCUPIED_DARK])
    await hass.async_block_till_done()
    (entry,) = hass.config_entries.async_entries("adaptive_areas")
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert started
    assert _presence_handles(hass) == []
