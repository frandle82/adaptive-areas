"""Tests for config flow behavior."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_NAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.area_registry import async_get as async_get_area_registry

from custom_components.adaptive_areas.config_flow import (
    LEGACY_DOMAIN,
    LEGACY_IMPORT_PREFIX,
    ConfigFlow,
    OptionsFlowHandler,
    _replace_legacy_entity_ids,
)
from custom_components.adaptive_areas.const import (
    AREA_STATE_BRIGHT,
    AREA_STATE_EXTENDED,
    CONF_AREA_HUMIDITY_SENSOR,
    CONF_AREA_TEMPERATURE_SENSOR,
    CONF_OVERHEAD_LIGHTS_ACTIVATION,
    CONF_ENABLED_FEATURES,
    CONF_DARK_ENTITY,
    CONF_ENVIRONMENT_CIRCULATION_FANS,
    CONF_ENVIRONMENT_OUTDOOR_HUMIDITY,
    CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE,
    CONF_ENVIRONMENT_SURFACE_TEMPERATURE,
    CONF_ENVIRONMENT_VENTILATION_FANS,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_FEATURE_ENVIRONMENT,
    CONF_EXCLUDE_ENTITIES,
    CONF_INCLUDE_ENTITIES,
    CONF_ID,
    CONF_OVERHEAD_LIGHTS_BLOCKING_STATES,
    CONF_OVERHEAD_LIGHTS_BRIGHTNESS,
    CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT,
    CONF_ROOM_CATEGORY,
    CONF_TRACK_ROOM_USAGE,
    DATA_AREA_OBJECT,
    DOMAIN,
    LIGHT_GROUP_ACTIVATION_EXTENDED,
    LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF,
    LIGHT_GROUP_BRIGHTNESS_OPTIONS,
    OPTIONS_AREA_META,
    MODULE_DATA,
    AdaptiveConfigEntryVersion,
    RoomCategory,
)
from tests.const import DEFAULT_MOCK_AREA
from tests.helpers import (
    get_basic_config_entry_data,
    init_integration,
    shutdown_integration,
)


def test_room_usage_is_not_a_meta_area_option() -> None:
    """Cleaning suitability remains limited to physical regular Areas."""
    assert CONF_TRACK_ROOM_USAGE not in {option[0] for option in OPTIONS_AREA_META}


async def test_user_flow_imports_legacy_magic_areas_entry(hass) -> None:
    """Test importing a legacy entry without modifying the original."""
    area_registry = async_get_area_registry(hass)
    area_registry.async_create("Kitchen")

    legacy_data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    legacy_options = {
        **legacy_data,
        CONF_DARK_ENTITY: "binary_sensor.magic_areas_aggregates_kitchen_light",
    }
    legacy_entry = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Kitchen",
        unique_id=str(DEFAULT_MOCK_AREA),
        data=legacy_data,
        options=legacy_options,
        version=2,
        minor_version=1,
    )
    legacy_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    import_label = f"{LEGACY_IMPORT_PREFIX} Kitchen"
    choice_validator = next(iter(result["data_schema"].schema.values()))
    assert import_label in choice_validator.container

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {ATTR_NAME: import_label},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen"
    assert result["data"] == legacy_data
    assert result["options"][CONF_DARK_ENTITY] == (
        "binary_sensor.adaptive_areas_aggregates_kitchen_light"
    )

    imported_entry = result["result"]
    assert imported_entry.unique_id == str(DEFAULT_MOCK_AREA)
    assert imported_entry.version == AdaptiveConfigEntryVersion.MAJOR
    assert imported_entry.minor_version == AdaptiveConfigEntryVersion.MINOR
    assert legacy_entry in hass.config_entries.async_entries(LEGACY_DOMAIN)


async def test_legacy_entry_is_hidden_after_area_was_imported(hass) -> None:
    """Test that an imported area cannot be imported twice."""
    legacy_data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    legacy_entry = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Kitchen",
        unique_id=str(DEFAULT_MOCK_AREA),
        data=legacy_data,
    )
    legacy_entry.add_to_hass(hass)
    imported_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen",
        unique_id=str(DEFAULT_MOCK_AREA),
        data={**legacy_data, CONF_ID: str(DEFAULT_MOCK_AREA)},
    )
    imported_entry.add_to_hass(hass)

    flow = ConfigFlow()
    flow.hass = hass

    assert flow._legacy_import_choices() == {}


def test_legacy_entity_ids_are_replaced_recursively() -> None:
    """Test legacy IDs in nested mappings and lists are replaced safely."""
    value = {
        "entity": "binary_sensor.magic_areas_kitchen_area_state",
        "nested": [
            "light.magic_areas_kitchen_all_lights",
            {"adaptive": "light.adaptive_areas_kitchen_all_lights"},
        ],
        "unrelated": "sensor.kitchen_temperature",
    }

    assert _replace_legacy_entity_ids(value) == {
        "entity": "binary_sensor.adaptive_areas_kitchen_area_state",
        "nested": [
            "light.adaptive_areas_kitchen_all_lights",
            {"adaptive": "light.adaptive_areas_kitchen_all_lights"},
        ],
        "unrelated": "sensor.kitchen_temperature",
    }


async def test_legacy_import_choices_disambiguate_duplicate_titles(hass) -> None:
    """Test legacy entries with duplicate titles remain independently importable."""
    first_entry = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Kitchen",
        unique_id="first-kitchen",
        data={CONF_ID: "first-kitchen"},
    )
    second_entry = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Kitchen",
        unique_id="second-kitchen",
        data={CONF_ID: "second-kitchen"},
    )
    first_entry.add_to_hass(hass)
    second_entry.add_to_hass(hass)

    flow = ConfigFlow()
    flow.hass = hass
    choices = flow._legacy_import_choices()
    first_choice, second_choice = sorted(
        (first_entry, second_entry), key=lambda entry: entry.entry_id
    )

    assert choices[f"{LEGACY_IMPORT_PREFIX} Kitchen"] is first_choice
    assert (
        choices[f"{LEGACY_IMPORT_PREFIX} Kitchen [{second_choice.entry_id[:8]}]"]
        is second_choice
    )


async def test_invalid_legacy_entry_without_area_id_is_hidden(hass) -> None:
    """Test a legacy entry without an area ID cannot be imported."""
    legacy_entry = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Invalid",
        unique_id=None,
        data={},
    )
    legacy_entry.add_to_hass(hass)

    flow = ConfigFlow()
    flow.hass = hass

    assert flow._legacy_import_choices() == {}


async def test_options_flow_migrates_legacy_light_group_options(hass) -> None:
    """Test that legacy light-group options are migrated before reopening the flow."""

    config_entry_options = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    config_entry_options[CONF_ENABLED_FEATURES] = {
        CONF_FEATURE_LIGHT_GROUPS: {
            CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: [AREA_STATE_BRIGHT],
            CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT: True,
        }
    }

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=str(config_entry_options[ATTR_NAME]),
        data=get_basic_config_entry_data(DEFAULT_MOCK_AREA),
        options=config_entry_options,
    )
    await init_integration(hass, [config_entry])

    flow = OptionsFlowHandler()
    flow.hass = hass
    flow.handler = config_entry.entry_id

    result = await flow.async_step_init()

    assert result["type"] == "menu"
    light_config = flow.area_options[CONF_ENABLED_FEATURES][CONF_FEATURE_LIGHT_GROUPS]
    assert light_config[CONF_OVERHEAD_LIGHTS_BLOCKING_STATES] == []
    assert (
        light_config[CONF_OVERHEAD_LIGHTS_BRIGHTNESS]
        == LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF
    )
    assert CONF_OVERHEAD_LIGHTS_TURN_OFF_WHEN_BRIGHT not in light_config

    await shutdown_integration(hass, [config_entry])


async def test_light_group_form_only_exposes_room_state_rules(hass) -> None:
    """Test that light groups use the simplified room-state configuration."""
    config_entry_options = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    config_entry_options[CONF_ENABLED_FEATURES] = {CONF_FEATURE_LIGHT_GROUPS: {}}
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=str(config_entry_options[ATTR_NAME]),
        data=get_basic_config_entry_data(DEFAULT_MOCK_AREA),
        options=config_entry_options,
    )
    await init_integration(hass, [config_entry])

    flow = OptionsFlowHandler()
    flow.hass = hass
    flow.handler = config_entry.entry_id
    await flow.async_step_init()
    result = await flow.async_step_feature_conf_light_groups()

    assert result["type"] == "form"
    field_names = {marker.schema for marker in result["data_schema"].schema}
    assert "overhead_lights_activation" in field_names
    assert "overhead_lights_blocking_states" in field_names
    assert "overhead_lights_brightness" in field_names
    assert "overhead_lights_states" not in field_names
    assert "overhead_lights_require_dark" not in field_names
    assert "overhead_lights_turn_off_when_bright" not in field_names
    assert "overhead_lights_act_on" not in field_names
    assert "overhead_lights_state_rules_rule_1" not in field_names
    assert "overhead_lights_states_logic" not in field_names
    assert LIGHT_GROUP_BRIGHTNESS_DARK_ON_BRIGHT_OFF in LIGHT_GROUP_BRIGHTNESS_OPTIONS

    invalid_result = await flow.async_step_feature_conf_light_groups(
        {CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: [AREA_STATE_BRIGHT]}
    )
    assert invalid_result["type"] == "form"
    assert invalid_result["errors"] == {
        CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: "malformed_input"
    }

    conflicting_result = await flow.async_step_feature_conf_light_groups(
        {
            CONF_OVERHEAD_LIGHTS_ACTIVATION: LIGHT_GROUP_ACTIVATION_EXTENDED,
            CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: [AREA_STATE_EXTENDED],
        }
    )
    assert conflicting_result["type"] == "form"
    assert conflicting_result["errors"] == {
        CONF_OVERHEAD_LIGHTS_BLOCKING_STATES: "malformed_input"
    }

    await shutdown_integration(hass, [config_entry])


async def test_area_evaluation_form(hass) -> None:
    """Intrinsic Area Evaluation exposes sources but no manual comfort band."""
    config_entry_options = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    config_entry_options[CONF_ENABLED_FEATURES] = {CONF_FEATURE_ENVIRONMENT: {}}
    config_entry_options[CONF_INCLUDE_ENTITIES] = [
        "sensor.room_temperature",
        "sensor.room_humidity",
    ]
    config_entry_options[CONF_AREA_TEMPERATURE_SENSOR] = "sensor.room_temperature"
    config_entry_options[CONF_AREA_HUMIDITY_SENSOR] = "sensor.room_humidity"
    hass.states.async_set(
        "sensor.room_temperature",
        "21",
        {ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE},
    )
    hass.states.async_set(
        "sensor.room_humidity",
        "50",
        {ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY},
    )
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=str(config_entry_options[ATTR_NAME]),
        data=get_basic_config_entry_data(DEFAULT_MOCK_AREA),
        options=config_entry_options,
    )
    await init_integration(hass, [config_entry])

    flow = OptionsFlowHandler()
    flow.hass = hass
    flow.handler = config_entry.entry_id
    await flow.async_step_init()

    feature_result = await flow.async_step_select_features()
    feature_fields = {marker.schema for marker in feature_result["data_schema"].schema}
    assert CONF_FEATURE_ENVIRONMENT in feature_fields

    area_result = await flow.async_step_area_config()
    area_fields = {marker.schema for marker in area_result["data_schema"].schema}
    assert CONF_TRACK_ROOM_USAGE in area_fields
    assert CONF_ROOM_CATEGORY in area_fields
    assert CONF_AREA_TEMPERATURE_SENSOR in area_fields
    assert CONF_AREA_HUMIDITY_SENSOR in area_fields

    environment_result = await flow.async_step_area_evaluation()
    environment_fields = {
        marker.schema for marker in environment_result["data_schema"].schema
    }
    assert CONF_ENVIRONMENT_OUTDOOR_TEMPERATURE in environment_fields
    assert CONF_ENVIRONMENT_OUTDOOR_HUMIDITY in environment_fields
    assert CONF_ENVIRONMENT_SURFACE_TEMPERATURE in environment_fields
    assert CONF_AREA_TEMPERATURE_SENSOR not in environment_fields
    assert CONF_AREA_HUMIDITY_SENSOR not in environment_fields

    excluded_primary = await flow.async_step_area_config(
        {
            CONF_AREA_TEMPERATURE_SENSOR: "sensor.room_temperature",
            CONF_AREA_HUMIDITY_SENSOR: "sensor.room_humidity",
            CONF_INCLUDE_ENTITIES: [
                "sensor.room_temperature",
                "sensor.room_humidity",
            ],
            CONF_EXCLUDE_ENTITIES: ["sensor.room_temperature"],
        }
    )
    assert excluded_primary["errors"] == {
        CONF_AREA_TEMPERATURE_SENSOR: "excluded_primary_source"
    }

    invalid = await flow.async_step_area_evaluation(
        {
            CONF_ENVIRONMENT_VENTILATION_FANS: ["fan.shared"],
            CONF_ENVIRONMENT_CIRCULATION_FANS: ["fan.shared"],
        }
    )
    assert invalid["type"] == "form"
    assert invalid["errors"] == {CONF_ENVIRONMENT_CIRCULATION_FANS: "malformed_input"}

    await shutdown_integration(hass, [config_entry])


async def test_options_primary_sources_reach_enabled_runtime(hass) -> None:
    """Saved general sources survive reload into an explicitly enabled engine."""
    temperature_id = "sensor.options_temperature"
    humidity_id = "sensor.options_humidity"
    hass.states.async_set(
        temperature_id, "21.5", {ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE}
    )
    hass.states.async_set(
        humidity_id, "50", {ATTR_DEVICE_CLASS: SensorDeviceClass.HUMIDITY}
    )
    data = get_basic_config_entry_data(DEFAULT_MOCK_AREA)
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=str(data[ATTR_NAME]),
        data=data,
        version=AdaptiveConfigEntryVersion.MAJOR,
        minor_version=AdaptiveConfigEntryVersion.MINOR,
    )
    await init_integration(hass, [config_entry])

    flow = OptionsFlowHandler()
    flow.hass = hass
    flow.handler = config_entry.entry_id
    await flow.async_step_init()
    result = await flow.async_step_area_config(
        {
            CONF_ROOM_CATEGORY: RoomCategory.LIVING_SEDENTARY,
            CONF_AREA_TEMPERATURE_SENSOR: temperature_id,
            CONF_AREA_HUMIDITY_SENSOR: humidity_id,
            CONF_INCLUDE_ENTITIES: [temperature_id, humidity_id],
        }
    )
    assert result["type"] == "menu"
    result = await flow.async_step_select_features({CONF_FEATURE_ENVIRONMENT: True})
    assert result["type"] == "menu"
    result = await flow.async_step_finish()
    assert result["type"] == "create_entry"

    hass.config_entries.async_update_entry(config_entry, options=result["data"])
    await hass.async_block_till_done()
    area = hass.data[MODULE_DATA][config_entry.entry_id][DATA_AREA_OBJECT]
    assert area.config[CONF_AREA_TEMPERATURE_SENSOR] == temperature_id
    assert area.config[CONF_AREA_HUMIDITY_SENSOR] == humidity_id
    assert area.environment is not None
    assert area.environment.assessment["state"] != "unknown"

    await shutdown_integration(hass, [config_entry])
