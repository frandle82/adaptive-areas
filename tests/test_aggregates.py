"""Test for aggregate (group) sensor behavior."""

from collections.abc import AsyncGenerator
import logging
from random import randint
from statistics import mean
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
)
from homeassistant.components.sensor.const import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    EVENT_STATE_CHANGED,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    UnitOfElectricCurrent,
    UnitOfTemperature,
)
from homeassistant.core import Event, HomeAssistant

from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_AGGREGATION,
    DATA_AREA_OBJECT,
    DOMAIN,
    MODULE_DATA,
)
from custom_components.adaptive_areas.sensor import AreaAggregateSensor

from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    assert_state,
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
    shutdown_integration,
)
from tests.mocks import MockBinarySensor, MockSensor

_LOGGER = logging.getLogger(__name__)


# Fixtures


@pytest.fixture(name="aggregates_config_entry")
def mock_config_entry_aggregates() -> MockConfigEntry:
    """Fixture for mock configuration entry."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}
            }
        }
    )
    return MockConfigEntry(domain=DOMAIN, data=data)


@pytest.fixture(name="_setup_integration_aggregates")
async def setup_integration_aggregates(
    hass: HomeAssistant,
    aggregates_config_entry: MockConfigEntry,
) -> AsyncGenerator[Any]:
    """Set up integration with secondary states config."""

    await init_integration(hass, [aggregates_config_entry])
    yield
    await shutdown_integration(hass, [aggregates_config_entry])


# Entities


@pytest.fixture(name="entities_binary_sensor_connectivity_multiple")
async def setup_entities_binary_sensor_connectivity_multiple(
    hass: HomeAssistant,
) -> list[MockBinarySensor]:
    """Create multiple mock sensor and setup the system with it."""
    nr_entities = 3
    mock_binary_sensor_entities = []
    for i in range(nr_entities):
        mock_binary_sensor_entities.append(
            MockBinarySensor(
                name=f"connectivity_sensor_{i}",
                unique_id=f"connectivity_sensor_{i}",
                device_class=BinarySensorDeviceClass.CONNECTIVITY,
            )
        )
    await setup_mock_entities(
        hass, BINARY_SENSOR_DOMAIN, {DEFAULT_MOCK_AREA: mock_binary_sensor_entities}
    )
    return mock_binary_sensor_entities


@pytest.fixture(name="entities_sensor_temperature_multiple")
async def setup_entities_sensor_temperature_multiple(
    hass: HomeAssistant,
) -> list[MockSensor]:
    """Create multiple mock sensor and setup the system with it."""
    nr_entities = 3
    mock_sensor_entities = []
    for i in range(nr_entities):
        random_value = randint(0, 100)
        mock_sensor_entities.append(
            MockSensor(
                name=f"temperature_sensor_{i}",
                unique_id=f"temperature_sensor_{i}",
                native_value=random_value,
                device_class=SensorDeviceClass.TEMPERATURE,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                unit_of_measurement=UnitOfTemperature.CELSIUS,
                extra_state_attributes={
                    "unit_of_measurement": UnitOfTemperature.CELSIUS,
                },
            )
        )
    await setup_mock_entities(
        hass, SENSOR_DOMAIN, {DEFAULT_MOCK_AREA: mock_sensor_entities}
    )
    return mock_sensor_entities


@pytest.fixture(name="entities_sensor_current_multiple")
async def setup_entities_sensor_current_multiple(
    hass: HomeAssistant,
) -> list[MockSensor]:
    """Create multiple mock sensor and setup the system with it."""
    nr_entities = 3
    mock_sensor_entities = []
    for i in range(nr_entities):
        random_value = randint(0, 100)
        mock_sensor_entities.append(
            MockSensor(
                name=f"current_sensor_{i}",
                unique_id=f"current_sensor_{i}",
                native_value=random_value,
                device_class=SensorDeviceClass.CURRENT,
                native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                extra_state_attributes={
                    "unit_of_measurement": UnitOfElectricCurrent.AMPERE,
                },
            )
        )
    await setup_mock_entities(
        hass, SENSOR_DOMAIN, {DEFAULT_MOCK_AREA: mock_sensor_entities}
    )
    return mock_sensor_entities


# Tests


async def test_aggregates_binary_sensor_regular(
    hass: HomeAssistant,
    entities_binary_sensor_motion_multiple: list[MockBinarySensor],
    _setup_integration_aggregates,
) -> None:
    """Test binary sensor aggregates with all=False."""

    aggregate_sensor_id = (
        f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_aggregates_kitchen_aggregate_motion"
    )

    # Init test & individual ON/OFF flip
    aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
    assert aggregate_sensor_state is not None
    assert aggregate_sensor_state.state == STATE_OFF
    assert hasattr(aggregate_sensor_state, "attributes")
    assert ATTR_ENTITY_ID in aggregate_sensor_state.attributes

    group_members: list[str] = aggregate_sensor_state.attributes[ATTR_ENTITY_ID]

    for mock_entity in entities_binary_sensor_motion_multiple:
        assert mock_entity.entity_id in group_members

        mock_state = hass.states.get(mock_entity.entity_id)
        assert_state(mock_state, STATE_OFF)

        # Test state flip ON
        hass.states.async_set(mock_entity.entity_id, STATE_ON)
        await hass.async_block_till_done()

        mock_state = hass.states.get(mock_entity.entity_id)
        assert_state(mock_state, STATE_ON)
        aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
        assert_state(aggregate_sensor_state, STATE_ON)

        # Test state flip OFF
        hass.states.async_set(mock_entity.entity_id, STATE_OFF)
        await hass.async_block_till_done()
        mock_state = hass.states.get(mock_entity.entity_id)
        assert_state(mock_state, STATE_OFF)
        aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
        assert_state(aggregate_sensor_state, STATE_OFF)

    # Turn all ON
    for mock_entity in entities_binary_sensor_motion_multiple:
        hass.states.async_set(mock_entity.entity_id, STATE_ON)
    await hass.async_block_till_done()

    # Turn all off and ensure only off when last off
    for entity_index, mock_entity in enumerate(entities_binary_sensor_motion_multiple):
        last_sensor = entity_index == (len(entities_binary_sensor_motion_multiple) - 1)
        hass.states.async_set(mock_entity.entity_id, STATE_OFF)
        await hass.async_block_till_done()
        aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
        assert_state(aggregate_sensor_state, STATE_OFF if last_sensor else STATE_ON)


async def test_aggregates_binary_sensor_all(
    hass: HomeAssistant,
    entities_binary_sensor_connectivity_multiple: list[MockBinarySensor],
    _setup_integration_aggregates,
) -> None:
    """Test binary sensor aggregates with all=True."""

    aggregate_sensor_id = f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_aggregates_kitchen_aggregate_connectivity"

    # Init test
    aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
    assert aggregate_sensor_state is not None
    assert aggregate_sensor_state.state == STATE_OFF
    assert hasattr(aggregate_sensor_state, "attributes")
    assert ATTR_ENTITY_ID in aggregate_sensor_state.attributes

    group_members: list[str] = aggregate_sensor_state.attributes[ATTR_ENTITY_ID]

    # ON test
    for entity_index, mock_entity in enumerate(
        entities_binary_sensor_connectivity_multiple
    ):
        last_sensor = entity_index == (
            len(entities_binary_sensor_connectivity_multiple) - 1
        )

        assert mock_entity.entity_id in group_members

        mock_state = hass.states.get(mock_entity.entity_id)
        assert_state(mock_state, STATE_OFF)

        # Test state flip ON
        hass.states.async_set(mock_entity.entity_id, STATE_ON)
        await hass.async_block_till_done()
        mock_state = hass.states.get(mock_entity.entity_id)
        assert_state(mock_state, STATE_ON)
        aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
        assert_state(aggregate_sensor_state, STATE_ON if last_sensor else STATE_OFF)

    # OFF test
    for entity_index, mock_entity in enumerate(
        entities_binary_sensor_connectivity_multiple
    ):
        last_sensor = entity_index == (
            len(entities_binary_sensor_connectivity_multiple) - 1
        )

        # Test state flip OFF
        hass.states.async_set(mock_entity.entity_id, STATE_OFF)
        await hass.async_block_till_done()
        mock_state = hass.states.get(mock_entity.entity_id)
        assert_state(mock_state, STATE_OFF)
        aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
        assert_state(aggregate_sensor_state, STATE_OFF)


async def test_aggregates_sensor_avg(
    hass: HomeAssistant,
    entities_sensor_temperature_multiple: list[MockSensor],
    _setup_integration_aggregates,
) -> None:
    """Test sensor aggregates with average mode."""

    aggregate_sensor_id = (
        f"{SENSOR_DOMAIN}.adaptive_areas_aggregates_kitchen_aggregate_temperature"
    )

    _LOGGER.warning(entities_sensor_temperature_multiple)

    entity_values = []

    # Read initial values
    for mock_entity in entities_sensor_temperature_multiple:
        mock_state = hass.states.get(mock_entity.entity_id)
        assert mock_state is not None
        entity_values.append(int(mock_state.state))

    # Init test
    aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
    assert aggregate_sensor_state is not None
    assert round(float(aggregate_sensor_state.state), 2) == round(
        mean(entity_values), 2
    )
    assert aggregate_sensor_state.attributes["source_count"] == len(entity_values)
    assert aggregate_sensor_state.attributes["available_count"] == len(entity_values)
    assert aggregate_sensor_state.attributes["unavailable_count"] == 0
    assert aggregate_sensor_state.attributes["minimum"] == min(entity_values)
    assert aggregate_sensor_state.attributes["maximum"] == max(entity_values)
    assert aggregate_sensor_state.attributes["spread"] == (
        max(entity_values) - min(entity_values)
    )

    unavailable_id = entities_sensor_temperature_multiple[0].entity_id
    hass.states.async_set(unavailable_id, "unavailable")
    await hass.async_block_till_done()
    remaining_values = entity_values[1:]
    aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
    assert round(float(aggregate_sensor_state.state), 2) == round(
        mean(remaining_values), 2
    )
    assert aggregate_sensor_state.attributes["available_count"] == len(remaining_values)
    assert aggregate_sensor_state.attributes["unavailable_count"] == 1

    # Change all the values
    changed_values = []
    for mock_entity in entities_sensor_temperature_multiple:
        random_value = randint(0, 100)
        changed_values.append(random_value)
        hass.states.async_set(
            mock_entity.entity_id,
            str(random_value),
            attributes={"unit_of_measurement": UnitOfTemperature.CELSIUS},
        )
        await hass.async_block_till_done()
        changed_state = hass.states.get(mock_entity.entity_id)
        assert changed_state is not None
        assert int(changed_state.state) == random_value

    # Check changed values
    aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
    assert aggregate_sensor_state is not None
    assert round(float(aggregate_sensor_state.state), 2) == round(
        mean(changed_values), 2
    )


async def test_aggregates_sensor_keeps_unavailable_start_source(
    hass: HomeAssistant,
    aggregates_config_entry: MockConfigEntry,
    entities_sensor_temperature_multiple: list[MockSensor],
) -> None:
    """Unavailable startup sources remain aggregate members."""

    unavailable_id = entities_sensor_temperature_multiple[0].entity_id
    assert unavailable_id is not None
    hass.states.async_set(
        unavailable_id,
        STATE_UNAVAILABLE,
        attributes={
            ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    await hass.async_block_till_done()

    await init_integration(hass, [aggregates_config_entry])
    try:
        aggregate_sensor_state = hass.states.get(
            f"{SENSOR_DOMAIN}.adaptive_areas_aggregates_kitchen_aggregate_temperature"
        )
        assert aggregate_sensor_state is not None
        assert unavailable_id in aggregate_sensor_state.attributes[ATTR_ENTITY_ID]
        assert aggregate_sensor_state.attributes["source_count"] == len(
            entities_sensor_temperature_multiple
        )
        assert aggregate_sensor_state.attributes["unavailable_count"] == 1
    finally:
        await shutdown_integration(hass, [aggregates_config_entry])


async def test_aggregates_sensor_adds_late_state_source(
    hass: HomeAssistant,
    aggregates_config_entry: MockConfigEntry,
    entities_sensor_temperature_multiple: list[MockSensor],
) -> None:
    """Registry-known sources are added when state metadata arrives later."""

    late_source_id = entities_sensor_temperature_multiple[-1].entity_id
    assert late_source_id is not None
    hass.states.async_remove(late_source_id)
    await hass.async_block_till_done()

    await init_integration(hass, [aggregates_config_entry])
    try:
        aggregate_sensor_id = (
            f"{SENSOR_DOMAIN}.adaptive_areas_aggregates_kitchen_aggregate_temperature"
        )
        aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
        assert aggregate_sensor_state is not None
        assert late_source_id not in aggregate_sensor_state.attributes[ATTR_ENTITY_ID]

        hass.states.async_set(
            late_source_id,
            "23",
            attributes={
                ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE,
                ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
            },
        )
        await hass.async_block_till_done()

        aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
        assert aggregate_sensor_state is not None
        assert late_source_id in aggregate_sensor_state.attributes[ATTR_ENTITY_ID]
        assert aggregate_sensor_state.attributes["source_count"] == len(
            entities_sensor_temperature_multiple
        )
    finally:
        await shutdown_integration(hass, [aggregates_config_entry])


async def test_aggregate_member_update_before_add_does_not_register_listener(
    hass: HomeAssistant,
    aggregates_config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dynamic members may change before add without state writes."""
    await init_integration(hass, [aggregates_config_entry])
    try:
        area = hass.data[MODULE_DATA][aggregates_config_entry.entry_id][
            DATA_AREA_OBJECT
        ]
        listener_calls: list[list[str]] = []
        writes: list[None] = []
        monkeypatch.setattr(
            "custom_components.adaptive_areas.sensor.base.async_track_state_change_event",
            lambda _hass, entity_ids, _callback: listener_calls.append(list(entity_ids))
            or (lambda: None),
        )
        sensor = AreaAggregateSensor(
            area=area,
            device_class=SensorDeviceClass.TEMPERATURE,
            entity_ids=["sensor.a"],
            unit_of_measurement=UnitOfTemperature.CELSIUS,
        )
        monkeypatch.setattr(sensor, "async_write_ha_state", lambda: writes.append(None))

        assert sensor.async_set_entity_ids(["sensor.a", "sensor.b"])

        assert sensor.source_entity_ids == ["sensor.a", "sensor.b"]
        assert listener_calls == []
        assert writes == []
    finally:
        await shutdown_integration(hass, [aggregates_config_entry])


async def test_aggregate_listener_uses_latest_members_after_add(
    hass: HomeAssistant,
    aggregates_config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listener registered after add uses members updated before add."""
    await init_integration(hass, [aggregates_config_entry])
    try:
        area = hass.data[MODULE_DATA][aggregates_config_entry.entry_id][
            DATA_AREA_OBJECT
        ]
        listener_entity_ids: list[list[str]] = []

        def _track(_hass, entity_ids, _callback):
            listener_entity_ids.append(list(entity_ids))
            return lambda: None

        monkeypatch.setattr(
            "custom_components.adaptive_areas.sensor.base.async_track_state_change_event",
            _track,
        )
        sensor = AreaAggregateSensor(
            area=area,
            device_class=SensorDeviceClass.TEMPERATURE,
            entity_ids=["sensor.a"],
            unit_of_measurement=UnitOfTemperature.CELSIUS,
        )
        assert sensor.async_set_entity_ids(["sensor.a", "sensor.b"])

        await sensor.async_added_to_hass()

        assert listener_entity_ids == [["sensor.a", "sensor.b"]]
    finally:
        await shutdown_integration(hass, [aggregates_config_entry])


async def test_aggregate_member_update_after_add_replaces_listener(
    hass: HomeAssistant,
    aggregates_config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dynamic member refresh removes the old listener and registers one new listener."""
    await init_integration(hass, [aggregates_config_entry])
    try:
        area = hass.data[MODULE_DATA][aggregates_config_entry.entry_id][
            DATA_AREA_OBJECT
        ]
        listeners: list[dict] = []
        writes: list[None] = []

        def _track(_hass, entity_ids, callback):
            listener = {
                "entity_ids": list(entity_ids),
                "callback": callback,
                "removed": False,
            }
            listeners.append(listener)

            def _remove() -> None:
                listener["removed"] = True

            return _remove

        monkeypatch.setattr(
            "custom_components.adaptive_areas.sensor.base.async_track_state_change_event",
            _track,
        )
        sensor = AreaAggregateSensor(
            area=area,
            device_class=SensorDeviceClass.TEMPERATURE,
            entity_ids=["sensor.a", "sensor.b"],
            unit_of_measurement=UnitOfTemperature.CELSIUS,
        )
        monkeypatch.setattr(sensor, "async_write_ha_state", lambda: writes.append(None))

        await sensor.async_added_to_hass()
        assert sensor.async_set_entity_ids(["sensor.a", "sensor.b", "sensor.c"])

        assert listeners[0]["removed"] is True
        assert listeners[-1]["entity_ids"] == ["sensor.a", "sensor.b", "sensor.c"]
        assert sum(not listener["removed"] for listener in listeners) == 1

        listeners[-1]["callback"](Event(EVENT_STATE_CHANGED, {"entity_id": "sensor.c"}))
        assert len(writes) == 2
    finally:
        await shutdown_integration(hass, [aggregates_config_entry])


async def test_aggregate_listener_removed_before_entity_removal(
    hass: HomeAssistant,
    aggregates_config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source changes after removal do not write aggregate state."""
    await init_integration(hass, [aggregates_config_entry])
    try:
        area = hass.data[MODULE_DATA][aggregates_config_entry.entry_id][
            DATA_AREA_OBJECT
        ]
        listeners: list[dict] = []
        writes: list[None] = []

        def _track(_hass, entity_ids, callback):
            listener = {"callback": callback, "removed": False}
            listeners.append(listener)

            def _remove() -> None:
                listener["removed"] = True

            return _remove

        monkeypatch.setattr(
            "custom_components.adaptive_areas.sensor.base.async_track_state_change_event",
            _track,
        )
        sensor = AreaAggregateSensor(
            area=area,
            device_class=SensorDeviceClass.TEMPERATURE,
            entity_ids=["sensor.a"],
            unit_of_measurement=UnitOfTemperature.CELSIUS,
        )
        monkeypatch.setattr(sensor, "async_write_ha_state", lambda: writes.append(None))

        await sensor.async_added_to_hass()
        await sensor.async_will_remove_from_hass()
        listeners[-1]["callback"](Event(EVENT_STATE_CHANGED, {"entity_id": "sensor.a"}))

        assert listeners[-1]["removed"] is True
        assert writes == []
    finally:
        await shutdown_integration(hass, [aggregates_config_entry])


async def test_aggregates_sensor_sum(
    hass: HomeAssistant,
    entities_sensor_current_multiple: list[MockSensor],
    _setup_integration_aggregates,
) -> None:
    """Test sensor aggregates with sum mode."""

    aggregate_sensor_id = (
        f"{SENSOR_DOMAIN}.adaptive_areas_aggregates_kitchen_aggregate_current"
    )

    _LOGGER.warning(entities_sensor_current_multiple)

    entity_values = []

    # Read initial values
    for mock_entity in entities_sensor_current_multiple:
        mock_state = hass.states.get(mock_entity.entity_id)
        assert mock_state is not None
        entity_values.append(int(mock_state.state))

    # Init test
    aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
    assert aggregate_sensor_state is not None
    assert round(float(aggregate_sensor_state.state), 2) == round(sum(entity_values), 2)

    # Change all the values
    changed_values = []
    for mock_entity in entities_sensor_current_multiple:
        random_value = randint(0, 100)
        changed_values.append(random_value)
        hass.states.async_set(
            mock_entity.entity_id,
            str(random_value),
            attributes={"unit_of_measurement": UnitOfElectricCurrent.AMPERE},
        )
        await hass.async_block_till_done()
        changed_state = hass.states.get(mock_entity.entity_id)
        assert changed_state is not None
        assert int(changed_state.state) == random_value

    # Check changed values
    aggregate_sensor_state = hass.states.get(aggregate_sensor_id)
    assert aggregate_sensor_state is not None
    assert round(float(aggregate_sensor_state.state), 2) == round(
        sum(changed_values), 2
    )
