"""Public illuminance threshold entity versus central Area brightness (Phase 6, characterisation).

The public `light` threshold entity (native HA ThresholdSensor, upper limit, absolute hysteresis
from the Aggregation feature) and the central brightness classification (DARK/BRIGHT/UNKNOWN from
the Light feature Lux limits) are two independent functions. These tests run the same numeric input
through both and pin the observed differences. They are not expected failures: each difference is
the documented contract of its function.

Native rule (homeassistant/components/threshold/binary_sensor.py): ON when value > upper + h,
OFF when value < upper - h, a value inside the band keeps the previous state, and the first value
inside the band (no previous state) gives OFF. An unavailable reading gives an unknown state.

Central rule (helpers/brightness.py): DARK when value <= turn_on_below, BRIGHT when value >=
turn_off_above, the band keeps the previous DARK or BRIGHT, and the band without a previous state is
UNKNOWN. An unavailable reading is UNKNOWN and forgets the previous state.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.sensor.const import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
)
from homeassistant.components.threshold.const import ATTR_HYSTERESIS, ATTR_UPPER
from homeassistant.const import LIGHT_LUX, STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD,
    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD_HYSTERESIS,
    CONF_AGGREGATES_MIN_ENTITIES,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_AGGREGATION,
    DOMAIN,
)
from custom_components.adaptive_areas.helpers.brightness import (
    BrightnessState,
    BrightnessTracker,
    LightPolicyConfig,
)
from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    setup_mock_entities,
    shutdown_integration,
)
from tests.mocks import MockSensor

THRESHOLD_ENTITY = (
    f"{BINARY_SENSOR_DOMAIN}.adaptive_areas_threshold_kitchen_threshold_light"
)
# The same numbers in both functions: native upper 600 with 10 % hysteresis gives 540..660.
CENTRAL = LightPolicyConfig(turn_on_below=540, turn_off_above=660)
SOURCE = "sensor.central_source"


@pytest.fixture(name="threshold_config_entry")
def _threshold_config_entry() -> MockConfigEntry:
    """Return the aggregation config: a 600 lx threshold with 10 % hysteresis."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_AGGREGATION: {
                    CONF_AGGREGATES_MIN_ENTITIES: 1,
                    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD: 600,
                    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD_HYSTERESIS: 10,
                },
            }
        }
    )
    return MockConfigEntry(domain=DOMAIN, data=data)


@pytest.fixture(name="_setup_integration_threshold")
async def _setup_threshold(
    hass: HomeAssistant, threshold_config_entry: MockConfigEntry
) -> AsyncGenerator[Any]:
    """Set up the integration with the threshold configuration."""
    await init_integration(hass, [threshold_config_entry])
    yield
    await shutdown_integration(hass, [threshold_config_entry])


@pytest.fixture(name="entities_sensor_illuminance_single")
async def _illuminance_single(hass: HomeAssistant) -> list[MockSensor]:
    """One illuminance source (the input of the public threshold entity)."""
    mock_sensor = MockSensor(
        name="illuminance_sensor",
        unique_id="illuminance_sensor",
        native_value=0.0,
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        unit_of_measurement=LIGHT_LUX,
        extra_state_attributes={"unit_of_measurement": LIGHT_LUX},
    )
    await setup_mock_entities(hass, SENSOR_DOMAIN, {DEFAULT_MOCK_AREA: [mock_sensor]})
    return [mock_sensor]


async def _set(hass: HomeAssistant, sensor: str, value: str) -> None:
    hass.states.async_set(sensor, value, attributes={"unit_of_measurement": LIGHT_LUX})
    await hass.async_block_till_done()


def _native_on(hass: HomeAssistant) -> str:
    return hass.states.get(THRESHOLD_ENTITY).state


async def test_public_entity_registration_and_configuration(
    hass: HomeAssistant,
    entities_sensor_illuminance_single,
    _setup_integration_threshold,
) -> None:
    """The public entity keeps its entity id, unique id and configured upper limit and hysteresis."""
    entry = er.async_get(hass).async_get(THRESHOLD_ENTITY)
    assert entry is not None
    assert entry.unique_id
    assert entry.domain == BINARY_SENSOR_DOMAIN
    state = hass.states.get(THRESHOLD_ENTITY)
    assert state is not None
    assert float(state.attributes[ATTR_UPPER]) == 600
    assert float(state.attributes[ATTR_HYSTERESIS]) == 60


async def test_identical_input_gives_the_documented_differences(
    hass: HomeAssistant,
    entities_sensor_illuminance_single,
    _setup_integration_threshold,
) -> None:
    """Same input sequence: public entity (ON/OFF) against central classification.

    The native entity keeps its state strictly inside (540, 660); the central classification
    switches at 540 (DARK) and 660 (BRIGHT) inclusive. Two steps therefore differ:
    660 from DARK and 540 from BRIGHT.
    """
    sensor = entities_sensor_illuminance_single[0].entity_id
    tracker = BrightnessTracker()
    sequence = ["0", "660", "661", "600", "540", "539", "600", "661", "660"]
    # Expected: (native on-state, central state)
    expected = [
        (STATE_OFF, BrightnessState.DARK),
        (STATE_OFF, BrightnessState.BRIGHT),  # native differs at the upper boundary
        (STATE_ON, BrightnessState.BRIGHT),
        (STATE_ON, BrightnessState.BRIGHT),
        (STATE_ON, BrightnessState.DARK),  # native differs at the lower boundary
        (STATE_OFF, BrightnessState.DARK),
        (STATE_OFF, BrightnessState.DARK),
        (STATE_ON, BrightnessState.BRIGHT),
        (STATE_ON, BrightnessState.BRIGHT),
    ]
    observed = []
    for raw in sequence:
        await _set(hass, sensor, raw)
        central = tracker.update(value=float(raw), config=CENTRAL, source_id=SOURCE)
        observed.append((_native_on(hass), central.state))
    assert observed == expected


async def test_unavailable_then_band_reading(
    hass: HomeAssistant,
    entities_sensor_illuminance_single,
    _setup_integration_threshold,
) -> None:
    """After an outage, a band reading: the native entity turns OFF, the central value is UNKNOWN."""
    sensor = entities_sensor_illuminance_single[0].entity_id
    tracker = BrightnessTracker()
    await _set(hass, sensor, "661")
    tracker.update(value=661.0, config=CENTRAL, source_id=SOURCE)
    assert _native_on(hass) == STATE_ON

    await _set(hass, sensor, "unavailable")
    central = tracker.update(value=None, config=CENTRAL, source_id=SOURCE)
    assert _native_on(hass) == STATE_UNKNOWN
    assert central.state == BrightnessState.UNKNOWN

    await _set(hass, sensor, "600")
    central = tracker.update(value=600.0, config=CENTRAL, source_id=SOURCE)
    assert _native_on(hass) == STATE_OFF
    assert central.state == BrightnessState.UNKNOWN


async def test_zero_lux_is_a_valid_dark_reading(
    hass: HomeAssistant,
    entities_sensor_illuminance_single,
    _setup_integration_threshold,
) -> None:
    """A numeric 0 is a valid reading: both functions report not-bright (native OFF, central DARK)."""
    sensor = entities_sensor_illuminance_single[0].entity_id
    await _set(hass, sensor, "0")
    central = BrightnessTracker().update(value=0.0, config=CENTRAL, source_id=SOURCE)
    assert _native_on(hass) == STATE_OFF
    assert central.state == BrightnessState.DARK


async def test_invalid_reading_is_unknown_in_both(
    hass: HomeAssistant,
    entities_sensor_illuminance_single,
    _setup_integration_threshold,
) -> None:
    """A non-numeric state gives an unknown native state and an UNKNOWN central state."""
    sensor = entities_sensor_illuminance_single[0].entity_id
    await _set(hass, sensor, "not-a-number")
    assert _native_on(hass) == STATE_UNKNOWN
    central = BrightnessTracker().update(value=None, config=CENTRAL, source_id=SOURCE)
    assert central.state == BrightnessState.UNKNOWN


async def test_zero_threshold_creates_no_public_entity(
    hass: HomeAssistant,
    entities_sensor_illuminance_single,
) -> None:
    """Activation: a threshold of 0 (disabled) creates no public light threshold entity."""
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_AGGREGATION: {
                    CONF_AGGREGATES_MIN_ENTITIES: 1,
                    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD: 0,
                },
            }
        }
    )
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])
    try:
        assert hass.states.get(THRESHOLD_ENTITY) is None
    finally:
        await shutdown_integration(hass, [entry])


async def test_initial_band_reading_is_off_native_and_unknown_central(
    hass: HomeAssistant,
) -> None:
    """First valid reading inside the band: native starts OFF, central starts UNKNOWN."""
    mock_sensor = MockSensor(
        name="illuminance_sensor",
        unique_id="illuminance_sensor",
        native_value=600.0,
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        unit_of_measurement=LIGHT_LUX,
        extra_state_attributes={"unit_of_measurement": LIGHT_LUX},
    )
    await setup_mock_entities(hass, SENSOR_DOMAIN, {DEFAULT_MOCK_AREA: [mock_sensor]})
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    data.update(
        {
            CONF_ENABLED_FEATURES: {
                CONF_FEATURE_AGGREGATION: {
                    CONF_AGGREGATES_MIN_ENTITIES: 1,
                    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD: 600,
                    CONF_AGGREGATES_ILLUMINANCE_THRESHOLD_HYSTERESIS: 10,
                },
            }
        }
    )
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    await init_integration(hass, [entry])
    try:
        assert _native_on(hass) == STATE_OFF
        central = BrightnessTracker().update(
            value=600.0, config=CENTRAL, source_id=SOURCE
        )
        assert central.state == BrightnessState.UNKNOWN
    finally:
        await shutdown_integration(hass, [entry])
