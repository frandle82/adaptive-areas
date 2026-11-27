"""Fixtures for tests."""

from collections.abc import AsyncGenerator
import logging
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
)
from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_AGGREGATION,
    CONF_TYPE,
    DOMAIN,
    AreaType,
)

from tests.const import DEFAULT_MOCK_AREA, MOCK_AREAS, MockAreaIds
from tests.helpers import (
    get_basic_config_entry_data,
    immediate_call_factory,
    init_integration,
    setup_mock_entities,
    shutdown_integration,
)
from tests.mocks import MockBinarySensor

_LOGGER = logging.getLogger(__name__)

# Fixtures


@pytest.fixture(autouse=True)
async def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> AsyncGenerator[None]:
    """Enable custom integration."""
    _ = enable_custom_integrations  # unused
    yield


# Timer-related


@pytest.fixture
def patch_async_call_later(hass):
    """Automatically patch async_call_later for ReusableTimer tests."""
    with patch(
        "custom_components.adaptive_areas.helpers.timer.async_call_later",
        side_effect=immediate_call_factory(hass),
    ):
        yield


# Config entries


@pytest.fixture(name="basic_config_entry")
async def mock_config_entry() -> MockConfigEntry:
    """Fixture for mock configuration entry."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    return MockConfigEntry(domain=DOMAIN, data=data)


@pytest.fixture(name="all_areas_with_meta_config_entry")
async def mock_config_entry_all_areas_with_meta_config_entry() -> list[MockConfigEntry]:
    """Fixture for mock configuration entry."""

    config_entries: list[MockConfigEntry] = []
    for area_entry in MockAreaIds:
        data = get_basic_config_entry_data(area_entry)
        data.update(
            {
                CONF_ENABLED_FEATURES: {
                    CONF_FEATURE_AGGREGATION: {CONF_AGGREGATES_MIN_ENTITIES: 1}
                }
            }
        )
        config_entries.append(MockConfigEntry(domain=DOMAIN, data=data))

    return config_entries


# Entities


@pytest.fixture(name="entities_binary_sensor_motion_one")
async def setup_entities_binary_sensor_motion_one(
    hass: HomeAssistant,
) -> list[MockBinarySensor]:
    """Create one mock sensor and setup the system with it."""
    mock_binary_sensor_entities = [
        MockBinarySensor(
            name="motion_sensor",
            unique_id="unique_motion",
            device_class=BinarySensorDeviceClass.MOTION,
        )
    ]
    await setup_mock_entities(
        hass, BINARY_SENSOR_DOMAIN, {DEFAULT_MOCK_AREA: mock_binary_sensor_entities}
    )
    return mock_binary_sensor_entities


@pytest.fixture(name="entities_binary_sensor_motion_multiple")
async def setup_entities_binary_sensor_motion_multiple(
    hass: HomeAssistant,
) -> list[MockBinarySensor]:
    """Create multiple mock sensor and setup the system with it."""
    nr_entities = 3
    mock_binary_sensor_entities = []
    for i in range(nr_entities):
        mock_binary_sensor_entities.append(
            MockBinarySensor(
                name=f"motion_sensor_{i}",
                unique_id=f"motion_sensor_{i}",
                device_class=BinarySensorDeviceClass.MOTION,
            )
        )
    await setup_mock_entities(
        hass, BINARY_SENSOR_DOMAIN, {DEFAULT_MOCK_AREA: mock_binary_sensor_entities}
    )
    return mock_binary_sensor_entities


@pytest.fixture(name="entities_binary_sensor_motion_all_areas_with_meta")
async def setup_entities_binary_sensor_motion_all_areas_with_meta(
    hass: HomeAssistant,
) -> dict[MockAreaIds, list[MockBinarySensor]]:
    """Create multiple mock sensor and setup the system with it."""

    mock_binary_sensor_entities: dict[MockAreaIds, list[MockBinarySensor]] = {}

    for area in MockAreaIds:
        assert area is not None
        area_object = MOCK_AREAS[area]
        assert area_object is not None
        if area_object[CONF_TYPE] == AreaType.META:
            continue

        mock_sensor = MockBinarySensor(
            name=f"motion_sensor_{area.value}",
            unique_id=f"motion_sensor_{area.value}",
            device_class=BinarySensorDeviceClass.MOTION,
        )

        mock_binary_sensor_entities[area] = [
            mock_sensor,
        ]

    await setup_mock_entities(hass, BINARY_SENSOR_DOMAIN, mock_binary_sensor_entities)

    return mock_binary_sensor_entities


# Integration setups


@pytest.fixture(name="_setup_integration_basic")
async def setup_integration(
    hass: HomeAssistant,
    basic_config_entry: MockConfigEntry,
) -> AsyncGenerator[Any]:
    """Set up integration with basic config."""

    await init_integration(hass, [basic_config_entry])
    yield
    await shutdown_integration(hass, [basic_config_entry])


@pytest.fixture(name="_setup_integration_all_areas_with_meta")
async def setup_integration_all_areas_with_meta(
    hass: HomeAssistant,
    all_areas_with_meta_config_entry: list[MockConfigEntry],
) -> AsyncGenerator[Any]:
    """Set up integration with all areas and meta-areas."""

    non_meta_areas: list[MockAreaIds] = []

    for area in MockAreaIds:
        area_object = MOCK_AREAS[area]
        assert area_object is not None
        if area_object[CONF_TYPE] == AreaType.META:
            continue
        non_meta_areas.append(area)

    assert len(non_meta_areas) > 0

    await init_integration(
        hass,
        all_areas_with_meta_config_entry,
        areas=non_meta_areas,
    )
    yield
    await shutdown_integration(
        hass,
        all_areas_with_meta_config_entry,
    )


# Temporary CI diagnosis (Phase H): the stable job intermittently stalls in
# asyncio.Runner.close() of a test's event loop, waiting for a task that does not
# finish after cancellation. This reports those tasks with their stacks and the test
# directly on the original stderr, so the CI log shows them even if the run stalls.
# Remove once the cause is fixed.
_DIAG: dict[str, Any] = {"test": None, "fd": None}


def pytest_configure(config) -> None:
    """Remember the original stderr that pytest keeps for faulthandler."""
    from _pytest.faulthandler import fault_handler_stderr_fd_key

    _DIAG["fd"] = config.stash.get(fault_handler_stderr_fd_key, None)

    import asyncio
    import asyncio.runners as runners
    import io
    import os

    original = runners._cancel_all_tasks

    def _cancel_all_tasks(loop) -> None:
        left = [task for task in asyncio.all_tasks(loop) if not task.done()]
        if left and _DIAG["fd"] is not None:
            out = io.StringIO()
            out.write(f"\n=== AA DIAG {_DIAG['test']}: {len(left)} task(s) left\n")
            for task in left:
                out.write(f"--- {task!r}\n")
                task.print_stack(file=out)
            os.write(_DIAG["fd"], out.getvalue().encode())
        return original(loop)

    runners._cancel_all_tasks = _cancel_all_tasks


def pytest_runtest_setup(item) -> None:
    """Record the running test for the diagnosis above."""
    _DIAG["test"] = item.nodeid
