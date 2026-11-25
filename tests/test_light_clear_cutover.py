"""Direct Home Assistant regression tests for the CLEAR cutover of the ALL light group.

Real integration, real states, real service events. Automatic light OFF calls are counted on
the ALL group entity with an automation context (no user id). No sleeps.
"""

from __future__ import annotations

import pytest
from homeassistant.const import ATTR_ENTITY_ID, EVENT_CALL_SERVICE, STATE_ON
from homeassistant.core import Context, Event, HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests import test_light_coordination_regression as regression
from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import init_integration, shutdown_integration
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_coordination_regression import (  # noqa: F401
    LIGHT,
    _entry,
    _free,
    _manual_off,
    _occupy,
    _dark,
    probe_devices,
)

pytestmark = pytest.mark.usefixtures("probe_devices")

ALL_GROUP = f"light.adaptive_areas_light_groups_{DEFAULT_MOCK_AREA.value}_all_lights"
EVENTS: list[dict] = []


@callback
def _record(event: Event) -> None:
    data = event.data
    if data.get("domain") != "light":
        return
    EVENTS.append(
        {
            "service": data.get("service"),
            "target": str(data.get("service_data", {}).get(ATTR_ENTITY_ID)),
            "context": event.context.id if event.context else None,
            "user": bool(event.context and event.context.user_id),
        }
    )


def _auto_off_on_all(events: list[dict]) -> list[dict]:
    return [
        e
        for e in events
        if e["service"] == "turn_off" and e["target"] == ALL_GROUP and not e["user"]
    ]


async def _step(hass: HomeAssistant, step) -> None:
    await step(hass)
    await hass.async_block_till_done()


async def _run(hass: HomeAssistant, entry: MockConfigEntry, steps) -> list[list[dict]]:
    """Run steps; return the bus events recorded per step."""
    EVENTS.clear()
    regression.CURRENT_ENTRY[:] = [entry.entry_id]
    hass.bus.async_listen(EVENT_CALL_SERVICE, _record)
    await init_integration(hass, [entry])
    await regression._enable_group_control(hass)
    per_step: list[list[dict]] = []
    try:
        for step in steps:
            start = len(EVENTS)
            await _step(hass, step)
            per_step.append(list(EVENTS[start:]))
    finally:
        await shutdown_integration(hass, [entry])
    return per_step


async def test_occupied_to_clear_sends_exactly_one_automatic_off(hass) -> None:
    """Occupied -> clear: one automatic OFF on the ALL group entity (automation context)."""
    per_step = await _run(hass, _entry(), [_dark, _occupy, _free])
    assert len(_auto_off_on_all(per_step[2])) == 1


async def test_repeated_clear_sends_no_second_automatic_off(hass) -> None:
    """A clear event that follows a clear state never repeats the OFF."""
    per_step = await _run(hass, _entry(), [_dark, _occupy, _free, _free])
    assert len(_auto_off_on_all(per_step[2])) == 1
    assert _auto_off_on_all(per_step[3]) == []


async def test_override_ends_with_the_occupation_and_clear_sends_one_off(hass) -> None:
    """Override during OCCUPIED blocks commands; the CLEAR transition ends it: one OFF."""

    async def _manual_on(hass_: HomeAssistant) -> None:
        await hass_.services.async_call(
            "light",
            "turn_on",
            {ATTR_ENTITY_ID: LIGHT},
            blocking=True,
            context=Context(user_id=regression.PROBE_USER[0]),
        )
        await hass_.async_block_till_done()

    per_step = await _run(hass, _entry(), [_dark, _occupy, _manual_on, _free])
    assert len(_auto_off_on_all(per_step[3])) == 1


async def test_start_while_already_clear_sends_no_artificial_off(hass) -> None:
    """No occupation before: the start in CLEAR creates no OCCUPIED -> CLEAR transition."""
    per_step = await _run(hass, _entry(), [_free])
    assert _auto_off_on_all(per_step[0]) == []


async def test_disabled_automation_sends_no_automatic_off(hass) -> None:
    """The light group automation switch is off: a clear event sends no automatic OFF."""

    async def _disable(hass_: HomeAssistant) -> None:
        hass_.states.async_set(regression.CONTROL_SWITCH, STATE_ON)
        await hass_.services.async_call(
            "switch",
            "turn_off",
            {ATTR_ENTITY_ID: regression.CONTROL_SWITCH},
            blocking=True,
        )
        await hass_.async_block_till_done()

    per_step = await _run(hass, _entry(), [_dark, _occupy, _disable, _free])
    assert _auto_off_on_all(per_step[3]) == []


async def test_group_forward_is_not_a_second_automatic_decision(hass) -> None:
    """The group entity call may forward to its members; only the group call is counted."""
    per_step = await _run(hass, _entry(), [_dark, _occupy, _free])
    forwards = [e for e in per_step[2] if e["service"] == "turn_off" and not e["user"]]
    assert len({e["context"] for e in forwards}) <= 2  # group call (and its forward)
    assert len(_auto_off_on_all(per_step[2])) == 1


async def test_failed_automatic_off_is_not_retried(hass, monkeypatch) -> None:
    """A failing automatic OFF is attempted once; no retry follows."""
    from tests.service_faults import install_group_command_fault, native_group_command

    attempts: list[str] = []
    original = native_group_command(hass)

    async def failing(hass_, entity_id, service, *, context):
        attempts.append(entity_id)
        if entity_id == ALL_GROUP:
            raise RuntimeError("service unavailable")
        return await original(hass_, entity_id, service, context=context)

    install_group_command_fault(monkeypatch, hass, failing)
    await _run(hass, _entry(), [_dark, _occupy, _free])
    assert attempts.count(ALL_GROUP) == 1


async def test_manual_group_service_still_works(hass) -> None:
    """A user switches the group entity: the call is user-context and not blocked."""

    async def _manual_group(hass_: HomeAssistant) -> None:
        await hass_.services.async_call(
            "light",
            "turn_off",
            {ATTR_ENTITY_ID: ALL_GROUP},
            blocking=True,
            context=Context(user_id=regression.PROBE_USER[0]),
        )

    per_step = await _run(hass, _entry(), [_dark, _occupy, _manual_group])
    manual = [e for e in per_step[2] if e["target"] == ALL_GROUP and e["user"]]
    assert manual and manual[0]["service"] == "turn_off"
