"""Shared presence source: event order, UNKNOWN semantics, policy and group agreement.

The policy and the light groups read one occupancy: the Area state `occupied` after its
update. Both decide inside the same AREA_STATE_CHANGED callback. A presence source change
alone never evaluates. UNKNOWN (no usable source) never turns a group on or off.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    AdaptiveAreasEvents,
    AreaStates,
    LightGroupCategory,
)
from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    LightPolicyReason,
    evaluate_light_policy,
    light_policy_config_from_feature,
)
from custom_components.adaptive_areas.helpers import light_runtime
from custom_components.adaptive_areas.helpers.sources import (
    area_presence_available,
    light_source_snapshot,
    shared_presence_state,
)
from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import init_integration, setup_mock_entities, shutdown_integration
from tests.mocks import MockLight
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN

from custom_components.adaptive_areas.const import (
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_OVERHEAD_LIGHTS,
    CONF_OVERHEAD_LIGHTS_ACT_ON,
    CONF_OVERHEAD_LIGHTS_STATES,
    DOMAIN,
    LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE,
)
from custom_components.adaptive_areas.helpers.sources import (
    LightSourceSnapshot,
    LightTargetSource,
)
from tests.test_light_coordination_regression import LUX
from tests.helpers import get_basic_config_entry_data


def _group(hass: HomeAssistant, category: str):
    """Return the runtime light group of one category (lookup only, no decision)."""
    from homeassistant.components.light import DATA_COMPONENT

    from custom_components.adaptive_areas.light import AreaLightGroup

    for entity in hass.data[DATA_COMPONENT].entities:
        if isinstance(entity, AreaLightGroup) and str(entity.category) == str(category):
            return entity
    raise AssertionError(f"no runtime group for {category}")


def _area(hass: HomeAssistant):
    """Return the runtime Area object of the test entry."""
    return _group(hass, LightGroupCategory.OVERHEAD).area


SENSOR = "binary_sensor.presence_source_test"
SECOND_SENSOR = "binary_sensor.presence_source_test_two"


def _presence_entry() -> MockConfigEntry:
    """Area with an overhead group and a Lux configuration (as the shadow tests)."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_LIGHT: {"turn_on_below": 90.0, "turn_off_above": 110.0},
                CONF_FEATURE_LIGHT_GROUPS: {
                    CONF_OVERHEAD_LIGHTS: ["light.mock_light_1"],
                    CONF_OVERHEAD_LIGHTS_ACT_ON: [LIGHT_GROUP_ACT_ON_OCCUPANCY_CHANGE],
                    CONF_OVERHEAD_LIGHTS_STATES: [AreaStates.OCCUPIED],
                },
            }
        }
    )
    return MockConfigEntry(
        domain=DOMAIN,
        data=data,
        options={CONF_GLOBAL_OPTIONS: {CONF_GLOBAL_LIGHT_SENSOR: LUX}},
    )


@pytest.fixture(name="presence_runtime")
async def setup_presence_runtime(hass: HomeAssistant) -> AsyncGenerator[Any]:
    """Real policy listeners; evaluations are recorded with the snapshot they receive."""
    await setup_mock_entities(
        hass,
        LIGHT_DOMAIN,
        {
            DEFAULT_MOCK_AREA: [
                MockLight(name="mock_light_1", state="off", unique_id="unique_light")
            ]
        },
    )
    hass.states.async_set(LUX, "50", {"unit_of_measurement": "lx"})
    hass.states.async_set(SENSOR, STATE_OFF)
    hass.states.async_set(SECOND_SENSOR, STATE_OFF)
    recorded: list[tuple[bool, bool | None, bool]] = []
    original = light_runtime.evaluate_light_policy

    def _record(snapshot, policy_config):
        """Record what the real policy evaluation receives (after all guards)."""
        area = _area(hass)
        recorded.append(
            (
                area.is_occupied(),
                snapshot.presence_state,
                snapshot.presence_available,
            )
        )
        return original(snapshot, policy_config)

    entry = _presence_entry()
    with patch.object(light_runtime, "evaluate_light_policy", _record):
        await init_integration(hass, [entry])
        recorded.clear()
        hass.data["presence_recorded"] = recorded
        yield
    await shutdown_integration(hass, [entry])


def _use_sources(hass: HomeAssistant, area) -> None:
    """Declare the two test sensors as the Area's presence sources."""
    area.get_presence_sensors = lambda: [SENSOR, SECOND_SENSOR]  # type: ignore[method-assign]


def _recorded(hass: HomeAssistant) -> list[tuple[bool, bool | None, bool]]:
    return hass.data["presence_recorded"]


async def _signal(hass: HomeAssistant, area, states: list[str], lost=()) -> None:
    """Update the Area state and send the signal, as the presence update does."""
    from custom_components.adaptive_areas.helpers.light_origin import (
        begin_area_signal,
        end_area_signal,
    )

    area.states = list(states)
    begin_area_signal(area)
    try:
        async_dispatcher_send(
            hass,
            AdaptiveAreasEvents.AREA_STATE_CHANGED,
            area.id,
            (set(states), set(lost)),
        )
    finally:
        end_area_signal(area)
    await hass.async_block_till_done()


# -- Event order --------------------------------------------------------------------


async def test_source_change_alone_does_not_evaluate(
    hass: HomeAssistant, presence_runtime
) -> None:
    """A source event before the Area update never triggers the policy (no race)."""
    area = _area(hass)
    _use_sources(hass, area)
    hass.states.async_set(SENSOR, STATE_ON)
    await hass.async_block_till_done()
    assert _recorded(hass) == []


async def test_policy_evaluates_after_area_update(
    hass: HomeAssistant, presence_runtime
) -> None:
    """After the Area update and signal, the policy reads the updated occupancy."""
    area = _area(hass)
    _use_sources(hass, area)
    hass.states.async_set(SENSOR, STATE_ON)
    await _signal(hass, area, [AreaStates.OCCUPIED])
    assert _recorded(hass) == [(True, True, True)]


async def test_occupancy_end_is_read_as_vacancy(
    hass: HomeAssistant, presence_runtime
) -> None:
    """A vacancy after occupancy reads presence False with the source still available."""
    area = _area(hass)
    _use_sources(hass, area)
    hass.states.async_set(SENSOR, STATE_OFF)
    await _signal(hass, area, [AreaStates.OCCUPIED])
    await _signal(hass, area, [], lost=[AreaStates.OCCUPIED])
    assert _recorded(hass)[-1] == (False, False, True)


async def test_policy_uses_occupancy_captured_at_signal(
    hass: HomeAssistant, presence_runtime
) -> None:
    """A change after the signal but before the policy task runs does not leak in.

    The light groups decide synchronously in the signal callback, so the policy must
    use the same captured occupancy, not the value at task time.
    """
    area = _area(hass)
    _use_sources(hass, area)
    hass.states.async_set(SENSOR, STATE_ON)
    area.states = [AreaStates.OCCUPIED]
    async_dispatcher_send(
        hass,
        AdaptiveAreasEvents.AREA_STATE_CHANGED,
        area.id,
        ({AreaStates.OCCUPIED}, set()),
    )
    area.states = []  # changed again before the scheduled policy task runs
    await hass.async_block_till_done()
    assert _recorded(hass)[0][1] is True


async def test_several_sources_in_one_tick_are_one_consistent_decision(
    hass: HomeAssistant, presence_runtime
) -> None:
    """Two source changes in one tick: no evaluation before the Area update, one after."""
    area = _area(hass)
    _use_sources(hass, area)
    hass.states.async_set(SENSOR, STATE_ON)
    hass.states.async_set(SECOND_SENSOR, STATE_ON)
    assert _recorded(hass) == []
    await _signal(hass, area, [AreaStates.OCCUPIED])
    assert _recorded(hass) == [(True, True, True)]


async def test_signals_in_one_tick_keep_their_own_occupancy(
    hass: HomeAssistant, presence_runtime
) -> None:
    """Two Area updates in one tick: each evaluation keeps the occupancy of its own signal."""
    area = _area(hass)
    _use_sources(hass, area)
    hass.states.async_set(SENSOR, STATE_ON)
    area.states = [AreaStates.OCCUPIED]
    async_dispatcher_send(
        hass,
        AdaptiveAreasEvents.AREA_STATE_CHANGED,
        area.id,
        ({AreaStates.OCCUPIED}, set()),
    )
    area.states = []
    async_dispatcher_send(
        hass,
        AdaptiveAreasEvents.AREA_STATE_CHANGED,
        area.id,
        (set(), {AreaStates.OCCUPIED}),
    )
    await hass.async_block_till_done()
    assert [entry[1] for entry in _recorded(hass)] == [True, False]


async def test_unload_during_scheduled_update_skips_evaluation(
    hass: HomeAssistant, presence_runtime
) -> None:
    """A scheduled update waiting for the lock is dropped when the manager unloads."""
    area = _area(hass)
    _use_sources(hass, area)
    manager = area.light_runtime_manager
    area.states = [AreaStates.OCCUPIED]
    async with manager._lock:
        # The lock is held, so the scheduled evaluation waits instead of running eagerly.
        async_dispatcher_send(
            hass,
            AdaptiveAreasEvents.AREA_STATE_CHANGED,
            area.id,
            ({AreaStates.OCCUPIED}, set()),
        )
        for _ in range(3):
            await asyncio.sleep(0)
        assert _recorded(hass) == []
        manager.unload()
    await hass.async_block_till_done()
    assert _recorded(hass) == []


# -- UNKNOWN semantics --------------------------------------------------------------


def test_unknown_presence_is_no_action_for_the_policy() -> None:
    """The policy maps unknown presence to NO_ACTION, never to TURN_OFF or TURN_ON."""
    config = light_policy_config_from_feature(
        {"turn_on_below": 90.0, "turn_off_above": 110.0}
    )
    snapshot = LightSourceSnapshot(
        area_id="kitchen",
        targets=(LightTargetSource("light.a", True),),
        illuminance_entity_id=None,
        illuminance_available=True,
        illuminance_value=50.0,
        presence_source_entity_ids=(),
        presence_available=False,
        presence_state=None,
    )
    decision = evaluate_light_policy(snapshot, config)
    assert decision.action is LightPolicyAction.NO_ACTION
    assert decision.reason is LightPolicyReason.PRESENCE_UNAVAILABLE


async def test_unknown_at_start_reads_no_presence(
    hass: HomeAssistant, presence_runtime
) -> None:
    """Without any usable source the shared occupancy is unknown and never True."""
    area = _area(hass)
    area.get_presence_sensors = lambda: []  # type: ignore[method-assign]
    assert area_presence_available(area) is False
    snapshot = light_source_snapshot(area)
    assert snapshot.presence_state is None


async def test_source_loss_reads_unknown_not_clear(
    hass: HomeAssistant, presence_runtime
) -> None:
    """An unavailable source gives unknown presence, not an occupied or vacant reading."""
    area = _area(hass)
    _use_sources(hass, area)
    hass.states.async_set(SENSOR, STATE_UNAVAILABLE)
    hass.states.async_set(SECOND_SENSOR, STATE_UNAVAILABLE)
    assert area_presence_available(area) is False
    assert light_source_snapshot(area).presence_state is None


def test_shared_presence_state_reads_area_state() -> None:
    """The shared reading is the Area state; availability is checked separately."""

    class _Area:
        def __init__(self, occupied: bool) -> None:
            self._occupied = occupied

        def is_occupied(self) -> bool:
            return self._occupied

    assert shared_presence_state(_Area(True)) is True
    assert shared_presence_state(_Area(False)) is False
