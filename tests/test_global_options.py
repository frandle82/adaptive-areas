"""Backend-only GlobalEntry option storage tests."""

from pytest_homeassistant_custom_component.common import MockConfigEntry
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.components.sensor.const import SensorDeviceClass

from custom_components.adaptive_areas.area_config import (
    get_global_options,
    update_global_options,
)
from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_GLOBAL_ENTRY,
    CONF_GLOBAL_OPTIONS,
    DOMAIN,
)
from tests.test_area_crud import _call
from custom_components.adaptive_areas.websocket import async_register_websocket_commands
from custom_components.adaptive_areas import migration as migration_module


def _entry(options: dict) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, data={CONF_GLOBAL_ENTRY: True}, options=options
    )


async def test_global_options_are_empty_safe_and_partially_updated(hass) -> None:
    """Global options are optional, isolated from Areas, and clearable."""
    entry = _entry(
        {CONF_AREAS: {"kitchen": {"name": "Kitchen"}}, CONF_GLOBAL_OPTIONS: {}}
    )
    entry.add_to_hass(hass)
    areas_before = dict(entry.options[CONF_AREAS])

    assert get_global_options(entry) == {}
    update_global_options(hass, entry, {"weather_entity": "weather.home"})
    assert get_global_options(entry) == {"weather_entity": "weather.home"}
    update_global_options(hass, entry, {"global_light_sensor": "sensor.outdoor_lux"})
    assert get_global_options(entry) == {
        "weather_entity": "weather.home",
        "global_light_sensor": "sensor.outdoor_lux",
    }
    update_global_options(
        hass, entry, {"weather_entity": "weather.city", "global_light_sensor": None}
    )
    assert get_global_options(entry) == {
        "weather_entity": "weather.city",
        "global_light_sensor": None,
    }
    assert entry.options[CONF_AREAS] == areas_before


async def test_global_options_missing_key_is_read_only(hass) -> None:
    """Older containers without the optional key read as empty without mutation."""
    entry = _entry({CONF_AREAS: {}})
    entry.add_to_hass(hass)

    assert get_global_options(entry) == {}
    assert CONF_GLOBAL_OPTIONS not in entry.options


async def test_global_options_websocket_is_partial_and_read_only(
    hass, monkeypatch
) -> None:
    """The production API exposes only container-owned partial updates."""
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
    areas_before = dict(entry.options[CONF_AREAS])
    migration_spy = AsyncMock()
    monkeypatch.setattr(
        migration_module, "async_run_single_global_entry_migration", migration_spy
    )

    with patch.object(
        hass.config_entries,
        "async_reload",
        wraps=hass.config_entries.async_reload,
    ) as reload:
        assert (await _call(hass, "adaptive_areas/get_global_configuration"))[
            "options"
        ] == {
            "weather_entity": None,
            "global_light_sensor": None,
        }
        assert reload.await_count == 0
        assert (
            await _call(
                hass,
                "adaptive_areas/update_global_configuration",
                options={"weather_entity": "weather.home"},
            )
        )["ok"]
        assert reload.await_count == 1
        result = await _call(
            hass,
            "adaptive_areas/update_global_configuration",
            options={"global_light_sensor": "sensor.outdoor_lux"},
        )
        assert result["options"] == {
            "weather_entity": "weather.home",
            "global_light_sensor": "sensor.outdoor_lux",
        }
        assert reload.await_count == 2
        assert (
            await _call(
                hass,
                "adaptive_areas/update_global_configuration",
                options={"global_light_sensor": None},
            )
        )["ok"]
        assert reload.await_count == 3
        assert (
            await _call(
                hass,
                "adaptive_areas/update_global_configuration",
                options={"global_light_sensor": None},
            )
        )["ok"]
        assert reload.await_count == 3
        assert not (
            await _call(
                hass,
                "adaptive_areas/update_global_configuration",
                options={"unknown": "value"},
            )
        )["ok"]
        assert reload.await_count == 3
    assert entry.options[CONF_AREAS] == areas_before
    migration_spy.assert_not_awaited()


async def test_global_options_websocket_rejects_ambiguous_containers(
    hass, monkeypatch
) -> None:
    """Settings never select or create a GlobalEntry implicitly."""
    async_register_websocket_commands(hass)
    migration_spy = AsyncMock()
    monkeypatch.setattr(
        migration_module, "async_run_single_global_entry_migration", migration_spy
    )
    for command, data in (
        ("adaptive_areas/get_global_configuration", {}),
        (
            "adaptive_areas/update_global_configuration",
            {"options": {"weather_entity": "weather.home"}},
        ),
    ):
        assert not (await _call(hass, command, **data))["ok"]

    entries = [_entry({CONF_AREAS: {}, CONF_GLOBAL_OPTIONS: {}}) for _ in range(2)]
    for entry in entries:
        entry.add_to_hass(hass)
    before = [dict(entry.options) for entry in entries]
    assert not (await _call(hass, "adaptive_areas/get_global_configuration"))["ok"]
    assert not (
        await _call(
            hass,
            "adaptive_areas/update_global_configuration",
            options={"weather_entity": "weather.home"},
        )
    )["ok"]
    assert [dict(entry.options) for entry in entries] == before
    migration_spy.assert_not_awaited()


async def test_global_options_websocket_validates_entities_atomically(hass) -> None:
    """Weather and illuminance validation rejects invalid updates before mutation."""
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    entry = flow["result"]
    await hass.async_block_till_done()
    hass.states.async_set("weather.home", "unavailable")
    hass.states.async_set("weather.city", "sunny")
    hass.states.async_set(
        "sensor.lux", "unknown", {"device_class": SensorDeviceClass.ILLUMINANCE}
    )
    hass.states.async_set(
        "sensor.temperature", "20", {"device_class": SensorDeviceClass.TEMPERATURE}
    )
    with patch.object(hass.config_entries, "async_reload") as reload:
        assert not (
            await _call(
                hass,
                "adaptive_areas/update_global_configuration",
                options={"weather_entity": "sensor.temperature"},
            )
        )["ok"]
        assert not (
            await _call(
                hass,
                "adaptive_areas/update_global_configuration",
                options={"weather_entity": "weather.unknown"},
            )
        )["ok"]
        assert not (
            await _call(
                hass,
                "adaptive_areas/update_global_configuration",
                options={"global_light_sensor": "sensor.temperature"},
            )
        )["ok"]
        assert not (
            await _call(
                hass,
                "adaptive_areas/update_global_configuration",
                options={"global_light_sensor": "sensor.unknown"},
            )
        )["ok"]
        assert not (
            await _call(
                hass,
                "adaptive_areas/update_global_configuration",
                options={
                    "weather_entity": "weather.city",
                    "global_light_sensor": "sensor.temperature",
                },
            )
        )["ok"]
        reload.assert_not_awaited()
        assert entry.options[CONF_GLOBAL_OPTIONS] == {}


async def test_global_options_save_keeps_unavailable_stored_entity(hass) -> None:
    """Saving one global field keeps an unavailable stored weather entity intact."""
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    entry = flow["result"]
    await hass.async_block_till_done()
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_GLOBAL_OPTIONS: {"weather_entity": "weather.gone"},
        },
    )
    hass.states.async_set(
        "sensor.lux", "10", {"device_class": SensorDeviceClass.ILLUMINANCE}
    )
    with patch.object(hass.config_entries, "async_reload"):
        result = await _call(
            hass,
            "adaptive_areas/update_global_configuration",
            options={
                "weather_entity": "weather.gone",
                "global_light_sensor": "sensor.lux",
            },
        )

    assert result["ok"], result["errors"]
    assert entry.options[CONF_GLOBAL_OPTIONS] == {
        "weather_entity": "weather.gone",
        "global_light_sensor": "sensor.lux",
    }


async def test_global_options_stale_entities_follow_explicit_change_rules(hass) -> None:
    """Unchanged stale ids survive; new ids are validated; removal and replacement work."""
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    entry = flow["result"]
    await hass.async_block_till_done()
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_GLOBAL_OPTIONS: {
                "weather_entity": "weather.gone",
                "global_light_sensor": "sensor.gone",
            },
        },
    )
    hass.states.async_set("weather.city", "sunny")
    hass.states.async_set(
        "sensor.lux", "10", {"device_class": SensorDeviceClass.ILLUMINANCE}
    )
    with patch.object(hass.config_entries, "async_reload") as reload:
        # Both stale fields sent unchanged: accepted, nothing reloaded.
        result = await _call(
            hass,
            "adaptive_areas/update_global_configuration",
            options={
                "weather_entity": "weather.gone",
                "global_light_sensor": "sensor.gone",
            },
        )
        assert result["ok"], result["errors"]
        reload.assert_not_awaited()

        # New invalid id is rejected; the other valid change in the same call is not persisted.
        result = await _call(
            hass,
            "adaptive_areas/update_global_configuration",
            options={
                "weather_entity": "weather.unknown",
                "global_light_sensor": "sensor.lux",
            },
        )
        assert not result["ok"]
        assert "weather_entity" in result["errors"]
        assert (
            entry.options[CONF_GLOBAL_OPTIONS]["global_light_sensor"] == "sensor.gone"
        )
        reload.assert_not_awaited()

        # Valid replacement of the stale weather id; the unsent sensor value is kept.
        result = await _call(
            hass,
            "adaptive_areas/update_global_configuration",
            options={"weather_entity": "weather.city"},
        )
        assert result["ok"], result["errors"]
        assert entry.options[CONF_GLOBAL_OPTIONS] == {
            "weather_entity": "weather.city",
            "global_light_sensor": "sensor.gone",
        }

        # Explicit removal is allowed without validation.
        result = await _call(
            hass,
            "adaptive_areas/update_global_configuration",
            options={"global_light_sensor": None},
        )
        assert result["ok"], result["errors"]
        assert entry.options[CONF_GLOBAL_OPTIONS] == {
            "weather_entity": "weather.city",
            "global_light_sensor": None,
        }
