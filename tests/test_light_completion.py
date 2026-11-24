"""Policy-only lamps: failing, repeated and superseded policy commands (real HA, real calls).

Policy rule (approved): a new decision sends at most one service call. A failed call is
never repeated for an unchanged decision basis; only a real change of the basis (for example a
vacancy followed by an occupation) allows a new attempt. Service calls are counted on the
policy-only lamp (automatic context, no user). Lamps of an automatic group are not policy
targets. No sleeps.
"""

from __future__ import annotations

import pytest
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant

from custom_components.adaptive_areas.helpers import light_runtime
from tests import test_light_coordination_regression as regression
from tests.test_light import setup_entities_light_one  # noqa: F401
from tests.test_light_coordination_regression import (  # noqa: F401
    probe_devices,
)
from tests.test_light_ownership_runtime import (  # noqa: F401
    LIGHT,
    LIGHT_B,
    POLICY_LAMP,
    _area_entry,
    _dark,
    _free,
    _occupy,
    _run,
    setup_lamps,
)

pytestmark = pytest.mark.usefixtures("probe_devices", "lamps")


def _policy_entries(**overrides):
    """Kitchen: the policy-only lamp is in the Area but in no group; the group has LIGHT."""
    entries = {
        "a": _area_entry("a", [LIGHT, POLICY_LAMP], [LIGHT]),
        "b": _area_entry("b", [LIGHT_B], [LIGHT_B]),
    }
    entries.update(overrides)
    return entries


def _policy_calls(events: list[dict], service: str) -> list[dict]:
    return [
        e
        for e in events
        if e["service"] == service and POLICY_LAMP in e["targets"] and not e["user"]
    ]


def _failing_policy(monkeypatch, services: set[str], attempts: list[str]) -> None:
    """Fail the policy command of the policy-only lamp for the given services only."""
    original = light_runtime.async_execute_light_decision

    async def failing(hass_, snapshot, decision, *, context):
        if (
            any(t.entity_id == POLICY_LAMP for t in snapshot.targets)
            and decision.action.value in services
        ):
            attempts.append(decision.action.value)
            raise RuntimeError("service unavailable")
        return await original(hass_, snapshot, decision, context=context)

    monkeypatch.setattr(light_runtime, "async_execute_light_decision", failing)


async def _user_on_policy_lamp(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: POLICY_LAMP},
        blocking=True,
        context=Context(user_id=regression.PROBE_USER[0]),
    )
    await hass.async_block_till_done()


async def test_failing_policy_on_is_attempted_once_and_not_repeated(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A failing policy ON: one attempt; an identical later occupation sends nothing more."""
    attempts: list[str] = []
    _failing_policy(monkeypatch, {"turn_on"}, attempts)
    await _run(hass, _policy_entries(), [_dark, _occupy("a"), _occupy("a")])
    assert attempts == ["turn_on"]


async def test_failing_policy_off_is_attempted_once_and_not_repeated(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A failing policy OFF: one attempt; an identical later vacancy sends nothing more."""
    attempts: list[str] = []
    _failing_policy(monkeypatch, {"turn_off"}, attempts)
    per = await _run(
        hass,
        _policy_entries(),
        [_dark, _user_on_policy_lamp, _free("a"), _free("a")],
    )
    assert attempts == ["turn_off"]
    # The identical second vacancy is not a new decision: no further OFF is attempted.
    assert _policy_calls(per[3], "turn_off") == []


async def test_real_change_after_failed_on_allows_a_new_attempt(
    hass: HomeAssistant, monkeypatch
) -> None:
    """Failed ON, then a vacancy, then an occupation again: the new decision may try again."""
    attempts: list[str] = []
    _failing_policy(monkeypatch, {"turn_on"}, attempts)
    await _run(
        hass,
        _policy_entries(),
        [_dark, _occupy("a"), _free("a"), _occupy("a")],
    )
    assert attempts == ["turn_on", "turn_on"]


async def test_successful_policy_command_is_not_repeated(hass: HomeAssistant) -> None:
    """A successful policy ON: exactly one call; identical events add none."""
    per = await _run(hass, _policy_entries(), [_dark, _occupy("a"), _occupy("a")])
    assert len(_policy_calls(per[1], "turn_on")) == 1
    assert _policy_calls(per[2], "turn_on") == []


async def test_policy_command_carries_the_automatic_context(
    hass: HomeAssistant,
) -> None:
    """The policy command for the policy-only lamp is automatic: no user context."""
    per = await _run(hass, _policy_entries(), [_dark, _occupy("a")])
    calls = _policy_calls(per[1], "turn_on")
    assert len(calls) == 1
    assert calls[0]["user"] is False


async def test_lamp_of_an_automatic_group_gets_no_policy_command(
    hass: HomeAssistant, monkeypatch
) -> None:
    """LIGHT is a group member: no policy snapshot ever lists it as a target."""
    from custom_components.adaptive_areas.helpers import light_runtime as runtime

    seen: list[list[str]] = []
    original = runtime.async_execute_light_decision

    async def recording(hass_, snapshot, decision, *, context):
        seen.append([t.entity_id for t in snapshot.targets])
        return await original(hass_, snapshot, decision, context=context)

    monkeypatch.setattr(runtime, "async_execute_light_decision", recording)
    await _run(hass, _policy_entries(), [_dark, _occupy("a"), _free("a")])
    assert seen, "the policy must have evaluated the policy-only lamp"
    assert all(LIGHT not in targets for targets in seen)
    assert any(POLICY_LAMP in targets for targets in seen)


async def test_unload_drops_the_policy_for_later_occupations(
    hass: HomeAssistant,
) -> None:
    """After unload of the Area no policy command follows a later occupation."""
    entries = _policy_entries()

    async def _unload_a(hass_: HomeAssistant) -> None:
        assert await hass_.config_entries.async_unload(entries["a"].entry_id)
        await hass_.async_block_till_done()

    per = await _run(hass, entries, [_dark, _unload_a, _occupy("a")])
    assert _policy_calls(per[2], "turn_on") == []
