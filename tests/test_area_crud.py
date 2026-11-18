"""WebSocket CRUD coverage for GlobalEntry-owned Areas."""

from copy import deepcopy

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_OPTIONS,
    CONF_ENABLED_FEATURES,
    CONF_FEATURE_LIGHT,
    CONF_FEATURE_LIGHT_GROUPS,
    CONF_FEATURE_PRESENCE_HOLD,
    CONF_TURN_OFF_ABOVE,
    CONF_TURN_ON_BELOW,
    CONF_VACANCY_DELAY,
    DOMAIN,
)
from custom_components.adaptive_areas.helpers.area import get_runtime_areas_for_entry
from custom_components.adaptive_areas import migration as migration_module
from custom_components.adaptive_areas.area_config import update_global_options
from custom_components.adaptive_areas.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.adaptive_areas.websocket import async_register_websocket_commands


class _Connection:
    """Minimal admin connection for production WebSocket handlers."""

    user = SimpleNamespace(is_admin=True)

    def __init__(self) -> None:
        self.result = None

    def send_result(self, _message_id, result=None) -> None:
        self.result = result


async def _call(hass, command: str, **data):
    """Invoke one registered production command."""
    connection = _Connection()
    handler, schema = hass.data["websocket_api"][command]
    message = {"id": 1, "type": command, **data}
    handler(hass, connection, message if schema is False else schema(message))
    await hass.async_block_till_done()
    return connection.result


async def test_update_area_two_fields_persist_together(hass) -> None:
    """One Area update persists multiple schema fields with one reload."""
    area_registry = async_get_area_registry(hass)
    living = area_registry.async_create("Wohnzimmer")
    kitchen = area_registry.async_create("Küche")
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    entry = flow["result"]
    await hass.async_block_till_done()
    hass.states.async_set("weather.home", "sunny")
    hass.states.async_set(
        "sensor.outdoor_lux",
        "unavailable",
        {"device_class": SensorDeviceClass.ILLUMINANCE},
    )
    update_global_options(
        hass,
        entry,
        {
            "weather_entity": "weather.home",
            "global_light_sensor": "sensor.outdoor_lux",
        },
    )

    with patch.object(
        hass.config_entries,
        "async_reload",
        wraps=hass.config_entries.async_reload,
    ) as reload:
        assert (
            await _call(
                hass,
                "adaptive_areas/create_area",
                area_id=kitchen.id,
                options={
                    "include_entities": ["sensor.kitchen"],
                    "exclude_entities": ["sensor.kitchen_excluded"],
                    "clear_timeout": 3,
                    "secondary_states": {"dark_entity": "binary_sensor.kitchen_dark"},
                    "features": {CONF_FEATURE_PRESENCE_HOLD: {}},
                },
            )
        )["ok"]
        assert (
            await _call(
                hass,
                "adaptive_areas/create_area",
                area_id=living.id,
                options={
                    "include_entities": ["sensor.before"],
                    "exclude_entities": ["sensor.excluded"],
                    "presence_control_entities": ["binary_sensor.gate"],
                    "presence_device_platforms": ["binary_sensor"],
                    "presence_sensor_device_class": ["motion"],
                    "keep_only_entities": ["binary_sensor.confirm"],
                    "clear_timeout": 5,
                    "secondary_states": {
                        "dark_entity": "binary_sensor.dark",
                        "accent_entity": "binary_sensor.accent",
                        "sleep_entity": "binary_sensor.sleep",
                        "sleep_timeout": 10,
                        "extended_time": 5,
                        "extended_timeout": 10,
                    },
                    "features": {
                        CONF_FEATURE_LIGHT: {
                            "turn_on_below": 75.5,
                            "turn_off_above": 150.25,
                            "vacancy_delay": 30,
                        },
                        CONF_FEATURE_LIGHT_GROUPS: {
                            "overhead_lights": ["light.mock_light_1"],
                            "overhead_lights_act_on": ["occupancy_change"],
                            "overhead_lights_states": ["occupied"],
                        },
                        "climate_control": {
                            "entity_id": "climate.mock_climate",
                            "occupancy_threshold": 0,
                            "preset_occupied": "none",
                            "preset_clear": "away",
                        },
                    },
                },
            )
        )["ok"]
        before = deepcopy(entry.options[CONF_AREAS][living.id])
        kitchen_before = deepcopy(entry.options[CONF_AREAS][kitchen.id])
        global_before = deepcopy(entry.options[CONF_GLOBAL_OPTIONS])
        reload.reset_mock()

        assert (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={"include_entities": ["sensor.after"], "clear_timeout": 9},
            )
        )["ok"]
        assert reload.await_count == 1

    after = entry.options[CONF_AREAS][living.id]
    assert after["include_entities"] == ["sensor.after"]
    assert after["clear_timeout"] == 9
    for key in (
        "exclude_entities",
        "presence_control_entities",
        "presence_device_platforms",
        "presence_sensor_device_class",
        "keep_only_entities",
    ):
        assert after[key] == before[key]
    assert after["secondary_states"] == before["secondary_states"]
    assert after[CONF_ENABLED_FEATURES] == before[CONF_ENABLED_FEATURES]
    assert entry.options[CONF_AREAS][kitchen.id] == kitchen_before
    assert entry.options[CONF_GLOBAL_OPTIONS] == global_before


async def test_global_entry_area_crud_websocket_lifecycle(hass, monkeypatch) -> None:
    """Create, update, and remove Areas without creating ConfigEntries."""
    area_registry = async_get_area_registry(hass)
    living = area_registry.async_create("Wohnzimmer")
    kitchen = area_registry.async_create("Küche")
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    entry = flow["result"]
    await hass.async_block_till_done()
    migration_spy = AsyncMock()
    monkeypatch.setattr(
        migration_module, "async_run_single_global_entry_migration", migration_spy
    )

    with patch.object(
        hass.config_entries,
        "async_reload",
        wraps=hass.config_entries.async_reload,
    ) as reload:
        assert (
            await _call(
                hass, "adaptive_areas/create_area", area_id=living.id, options={}
            )
        )["ok"]
        assert reload.await_count == 1
        assert set(entry.options[CONF_AREAS]) == {living.id}
        assert [area.id for area in get_runtime_areas_for_entry(hass, entry)] == [
            living.id
        ]
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1

        living_entity_id = (
            "binary_sensor.adaptive_areas_presence_tracking_wohnzimmer_area_state"
        )
        living_entity = async_get_entity_registry(hass).async_get(living_entity_id)
        assert living_entity is not None
        assert living_entity.config_entry_id == entry.entry_id
        assert living_entity.area_id == living.id
        living_unique_id = living_entity.unique_id

        assert (
            await _call(
                hass, "adaptive_areas/create_area", area_id=kitchen.id, options={}
            )
        )["ok"]
        assert reload.await_count == 2
        assert set(entry.options[CONF_AREAS]) == {kitchen.id, living.id}
        assert {area.id for area in get_runtime_areas_for_entry(hass, entry)} == {
            living.id,
            kitchen.id,
        }

        duplicate = await _call(
            hass, "adaptive_areas/create_area", area_id=kitchen.id, options={}
        )
        assert not duplicate["ok"]
        assert reload.await_count == 2

        assert (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={"clear_timeout": 7},
            )
        )["ok"]
        assert reload.await_count == 3
        assert entry.options[CONF_AREAS][living.id]["clear_timeout"] == 7
        assert kitchen.id in entry.options[CONF_AREAS]
        living_entity = async_get_entity_registry(hass).async_get(living_entity_id)
        assert living_entity is not None and living_entity.unique_id == living_unique_id
        assert living_entity.config_entry_id == entry.entry_id
        assert living_entity.area_id == living.id

        before_options = dict(entry.options)
        assert not (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id="unknown",
                options={},
            )
        )["ok"]
        assert not (await _call(hass, "adaptive_areas/delete_area", area_id="unknown"))[
            "ok"
        ]
        assert dict(entry.options) == before_options
        assert reload.await_count == 3

        await _call(hass, "adaptive_areas/get_overview")
        await _call(hass, "adaptive_areas/get_area_configuration")
        await _call(hass, "adaptive_areas/get_light_runtime_status", area_id=living.id)
        await _call(hass, "adaptive_areas/get_area", area_id=living.id)
        assert reload.await_count == 3

        assert (await _call(hass, "adaptive_areas/delete_area", area_id=kitchen.id))[
            "ok"
        ]
        assert reload.await_count == 4
        assert set(entry.options[CONF_AREAS]) == {living.id}
        assert [area.id for area in get_runtime_areas_for_entry(hass, entry)] == [
            living.id
        ]

        assert (await _call(hass, "adaptive_areas/delete_area", area_id=living.id))[
            "ok"
        ]
        assert reload.await_count == 5
    assert entry.options[CONF_AREAS] == {}
    assert get_runtime_areas_for_entry(hass, entry) == []
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    migration_spy.assert_not_awaited()


async def test_light_feature_crud_is_configuration_only(hass, monkeypatch) -> None:
    """The future light feature persists without activating legacy light groups."""
    area_registry = async_get_area_registry(hass)
    living = area_registry.async_create("Wohnzimmer")
    kitchen = area_registry.async_create("Küche")
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    entry = flow["result"]
    await hass.async_block_till_done()
    migration_spy = AsyncMock()
    monkeypatch.setattr(
        migration_module, "async_run_single_global_entry_migration", migration_spy
    )

    with patch.object(
        hass.config_entries,
        "async_reload",
        wraps=hass.config_entries.async_reload,
    ) as reload:
        assert (
            await _call(
                hass,
                "adaptive_areas/create_area",
                area_id=living.id,
                options={CONF_ENABLED_FEATURES: {CONF_FEATURE_PRESENCE_HOLD: {}}},
            )
        )["ok"]
        assert (
            await _call(
                hass, "adaptive_areas/create_area", area_id=kitchen.id, options={}
            )
        )["ok"]
        assert reload.await_count == 2

        global_options_before = dict(entry.options[CONF_GLOBAL_OPTIONS])
        entities_before = {
            registry_entry.entity_id
            for registry_entry in async_get_entity_registry(hass).entities.values()
            if registry_entry.config_entry_id == entry.entry_id
        }
        living_features = dict(
            entry.options[CONF_AREAS][living.id][CONF_ENABLED_FEATURES]
        )
        living_features[CONF_FEATURE_LIGHT] = {}

        assert (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={CONF_ENABLED_FEATURES: living_features},
            )
        )["ok"]
        assert reload.await_count == 3
        assert set(entry.options[CONF_AREAS][living.id][CONF_ENABLED_FEATURES]) == {
            CONF_FEATURE_PRESENCE_HOLD,
            CONF_FEATURE_LIGHT,
        }
        assert (
            CONF_FEATURE_LIGHT
            not in entry.options[CONF_AREAS][kitchen.id][CONF_ENABLED_FEATURES]
        )
        assert entry.options[CONF_GLOBAL_OPTIONS] == global_options_before
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1
        assert {
            registry_entry.entity_id
            for registry_entry in async_get_entity_registry(hass).entities.values()
            if registry_entry.config_entry_id == entry.entry_id
        } == entities_before

        configurations = await _call(hass, "adaptive_areas/get_area_configuration")
        living_configuration = next(
            item for item in configurations["areas"] if item["area_id"] == living.id
        )
        assert CONF_FEATURE_LIGHT in living_configuration["available_features"]
        assert (
            CONF_FEATURE_LIGHT in living_configuration["options"][CONF_ENABLED_FEATURES]
        )
        overview = await _call(hass, "adaptive_areas/get_overview")
        assert CONF_FEATURE_LIGHT in next(
            item["enabled_features"]
            for item in overview["areas"]
            if item["id"] == living.id
        )
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert CONF_FEATURE_LIGHT in diagnostics["areas"][living.id]["enabled_features"]

        living_features[CONF_FEATURE_LIGHT] = {
            CONF_TURN_ON_BELOW: 75.5,
            CONF_TURN_OFF_ABOVE: 150.25,
        }
        assert (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={CONF_ENABLED_FEATURES: living_features},
            )
        )["ok"]
        assert reload.await_count == 4
        assert entry.options[CONF_AREAS][living.id][CONF_ENABLED_FEATURES][
            CONF_FEATURE_LIGHT
        ] == {CONF_TURN_ON_BELOW: 75.5, CONF_TURN_OFF_ABOVE: 150.25}

        living_features[CONF_FEATURE_LIGHT][CONF_VACANCY_DELAY] = 30
        assert (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={CONF_ENABLED_FEATURES: living_features},
            )
        )["ok"]
        assert reload.await_count == 5
        assert (
            entry.options[CONF_AREAS][living.id][CONF_ENABLED_FEATURES][
                CONF_FEATURE_LIGHT
            ][CONF_VACANCY_DELAY]
            == 30
        )
        assert entry.options[CONF_AREAS][kitchen.id][CONF_ENABLED_FEATURES] == {}

        living_features[CONF_FEATURE_LIGHT][CONF_VACANCY_DELAY] = 30.5
        assert (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={CONF_ENABLED_FEATURES: living_features},
            )
        )["ok"]
        assert reload.await_count == 6
        assert (
            entry.options[CONF_AREAS][living.id][CONF_ENABLED_FEATURES][
                CONF_FEATURE_LIGHT
            ][CONF_VACANCY_DELAY]
            == 30.5
        )

        invalid_features = dict(living_features)
        invalid_features[CONF_FEATURE_LIGHT] = {
            CONF_TURN_ON_BELOW: 75.5,
            CONF_TURN_OFF_ABOVE: 150.25,
            CONF_VACANCY_DELAY: -1,
        }
        before_invalid = dict(entry.options)
        assert not (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={CONF_ENABLED_FEATURES: invalid_features},
            )
        )["ok"]
        assert entry.options == before_invalid
        assert reload.await_count == 6

        living_features[CONF_FEATURE_LIGHT].pop(CONF_VACANCY_DELAY)
        assert (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={CONF_ENABLED_FEATURES: living_features},
            )
        )["ok"]
        assert reload.await_count == 7

        before_invalid = dict(entry.options)
        living_features[CONF_FEATURE_LIGHT] = {CONF_TURN_ON_BELOW: 100}
        assert not (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={CONF_ENABLED_FEATURES: living_features},
            )
        )["ok"]
        assert entry.options == before_invalid
        assert reload.await_count == 7

        living_features[CONF_FEATURE_LIGHT] = {}
        assert (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={CONF_ENABLED_FEATURES: living_features},
            )
        )["ok"]
        assert reload.await_count == 8
        assert (
            entry.options[CONF_AREAS][living.id][CONF_ENABLED_FEATURES][
                CONF_FEATURE_LIGHT
            ]
            == {}
        )

        assert (
            await _call(
                hass,
                "adaptive_areas/update_area",
                area_id=living.id,
                options={
                    CONF_ENABLED_FEATURES: {
                        CONF_FEATURE_PRESENCE_HOLD: living_features[
                            CONF_FEATURE_PRESENCE_HOLD
                        ]
                    }
                },
            )
        )["ok"]
        assert reload.await_count == 9

    assert (
        CONF_FEATURE_LIGHT
        not in entry.options[CONF_AREAS][living.id][CONF_ENABLED_FEATURES]
    )
    assert (
        CONF_FEATURE_PRESENCE_HOLD
        in entry.options[CONF_AREAS][living.id][CONF_ENABLED_FEATURES]
    )
    migration_spy.assert_not_awaited()


async def test_crud_rejects_zero_or_multiple_global_entries(hass, monkeypatch) -> None:
    """CRUD never creates or selects a container when it is ambiguous."""
    async_register_websocket_commands(hass)
    area = async_get_area_registry(hass).async_create("Wohnzimmer")
    migration_spy = AsyncMock()
    monkeypatch.setattr(
        migration_module, "async_run_single_global_entry_migration", migration_spy
    )
    with patch.object(hass.config_entries, "async_reload") as reload:
        for command, data in (
            ("adaptive_areas/create_area", {"area_id": area.id, "options": {}}),
            ("adaptive_areas/update_area", {"area_id": area.id, "options": {}}),
            ("adaptive_areas/delete_area", {"area_id": area.id}),
        ):
            assert not (await _call(hass, command, **data))["ok"]
        reload.assert_not_awaited()
    assert hass.config_entries.async_entries(DOMAIN) == []

    entries = [
        MockConfigEntry(
            domain=DOMAIN,
            data={CONF_GLOBAL_ENTRY: True},
            options={CONF_GLOBAL_OPTIONS: {}, CONF_AREAS: {}},
        )
        for _ in range(2)
    ]
    for entry in entries:
        entry.add_to_hass(hass)
    before = [dict(entry.options) for entry in entries]
    with patch.object(hass.config_entries, "async_reload") as reload:
        for command, data in (
            ("adaptive_areas/create_area", {"area_id": area.id, "options": {}}),
            ("adaptive_areas/update_area", {"area_id": area.id, "options": {}}),
            ("adaptive_areas/delete_area", {"area_id": area.id}),
        ):
            assert not (await _call(hass, command, **data))["ok"]
        reload.assert_not_awaited()
    assert [dict(entry.options) for entry in entries] == before
    migration_spy.assert_not_awaited()
