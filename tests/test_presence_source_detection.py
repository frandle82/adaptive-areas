"""Automatic presence-source detection: device classes, contacts and domains."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.adaptive_areas.const import (
    CONF_EXCLUDE_ENTITIES,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    CONF_PRESENCE_SENSOR_DEVICE_CLASS,
    DEFAULT_PRESENCE_DEVICE_PLATFORMS,
    DEFAULT_PRESENCE_DEVICE_SENSOR_CLASS,
    DOMAIN,
)
from custom_components.adaptive_areas.helpers.sources import (
    is_presence_source_active,
    physical_presence_source_ids,
)


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    return entry


def _config(**overrides) -> dict:
    config = {
        CONF_ID: "living_room",
        CONF_PRESENCE_DEVICE_PLATFORMS: list(DEFAULT_PRESENCE_DEVICE_PLATFORMS),
        CONF_PRESENCE_SENSOR_DEVICE_CLASS: list(DEFAULT_PRESENCE_DEVICE_SENSOR_CLASS),
        CONF_INCLUDE_ENTITIES: [],
        CONF_EXCLUDE_ENTITIES: [],
    }
    config.update(overrides)
    return config


def _set_binary(
    hass: HomeAssistant, entity_id: str, state: str, device_class: str | None
) -> None:
    attributes = {} if device_class is None else {"device_class": device_class}
    hass.states.async_set(entity_id, state, attributes)


def test_default_device_classes_are_motion_and_occupancy() -> None:
    """D05: the default device classes are motion and occupancy, not an empty filter."""
    assert list(DEFAULT_PRESENCE_DEVICE_SENSOR_CLASS) == [
        BinarySensorDeviceClass.MOTION,
        BinarySensorDeviceClass.OCCUPANCY,
    ]


async def test_motion_sensor_is_detected_without_manual_include(
    hass: HomeAssistant,
) -> None:
    """A motion sensor is a presence source with no include list at all."""
    entry = _entry(hass)
    _set_binary(hass, "binary_sensor.hall_motion", STATE_OFF, "motion")
    result = physical_presence_source_ids(
        hass,
        entry,
        _config(),
        loaded_entity_ids=["binary_sensor.hall_motion"],
    )
    assert result == ["binary_sensor.hall_motion"]


async def test_missing_device_class_key_falls_back_to_presence_defaults(
    hass: HomeAssistant,
) -> None:
    """A config without the device-class key must not drop every motion sensor."""
    entry = _entry(hass)
    _set_binary(hass, "binary_sensor.hall_motion", STATE_OFF, "motion")
    config = _config()
    config.pop(CONF_PRESENCE_SENSOR_DEVICE_CLASS)
    result = physical_presence_source_ids(
        hass,
        entry,
        config,
        loaded_entity_ids=["binary_sensor.hall_motion"],
    )
    assert result == ["binary_sensor.hall_motion"]


async def test_window_and_door_contacts_are_not_presence_sources(
    hass: HomeAssistant,
) -> None:
    """Contacts stay out of presence even when they are open."""
    entry = _entry(hass)
    _set_binary(hass, "binary_sensor.kitchen_window", STATE_ON, "window")
    _set_binary(hass, "binary_sensor.kitchen_door", STATE_ON, "door")
    _set_binary(hass, "binary_sensor.kitchen_humidity", STATE_ON, "moisture")
    _set_binary(hass, "binary_sensor.kitchen_smoke", STATE_ON, "smoke")
    result = physical_presence_source_ids(
        hass,
        entry,
        _config(),
        loaded_entity_ids=[
            "binary_sensor.kitchen_window",
            "binary_sensor.kitchen_door",
            "binary_sensor.kitchen_humidity",
            "binary_sensor.kitchen_smoke",
        ],
    )
    assert result == []


async def test_explicit_include_bypasses_device_class_only(
    hass: HomeAssistant,
) -> None:
    """A deliberately included supported entity counts even without a device class."""
    entry = _entry(hass)
    _set_binary(hass, "binary_sensor.custom_beam", STATE_ON, None)
    config = _config(**{CONF_INCLUDE_ENTITIES: ["binary_sensor.custom_beam"]})
    result = physical_presence_source_ids(
        hass,
        entry,
        config,
        loaded_entity_ids=["binary_sensor.custom_beam"],
    )
    assert result == ["binary_sensor.custom_beam"]


async def test_exclusion_wins_over_explicit_include(hass: HomeAssistant) -> None:
    """exclude_entities takes precedence over include_entities."""
    entry = _entry(hass)
    _set_binary(hass, "binary_sensor.hall_motion", STATE_ON, "motion")
    config = _config(
        **{
            CONF_INCLUDE_ENTITIES: ["binary_sensor.hall_motion"],
            CONF_EXCLUDE_ENTITIES: ["binary_sensor.hall_motion"],
        }
    )
    result = physical_presence_source_ids(
        hass,
        entry,
        config,
        loaded_entity_ids=["binary_sensor.hall_motion"],
    )
    assert result == []


async def test_empty_domain_selection_detects_nothing(hass: HomeAssistant) -> None:
    """An empty domain choice is stored and yields no automatic sources."""
    entry = _entry(hass)
    _set_binary(hass, "binary_sensor.hall_motion", STATE_ON, "motion")
    config = _config(**{CONF_PRESENCE_DEVICE_PLATFORMS: []})
    result = physical_presence_source_ids(
        hass,
        entry,
        config,
        loaded_entity_ids=["binary_sensor.hall_motion"],
    )
    assert result == []


async def test_all_four_domains_are_considered(hass: HomeAssistant) -> None:
    """Each of the four domains is accepted when selected and not otherwise."""
    entry = _entry(hass)
    hass.states.async_set("device_tracker.phone", "home", {})
    hass.states.async_set("media_player.tv", "playing", {})
    hass.states.async_set("remote.living", "on", {})
    _set_binary(hass, "binary_sensor.hall_motion", STATE_OFF, "motion")
    loaded = [
        "device_tracker.phone",
        "media_player.tv",
        "remote.living",
        "binary_sensor.hall_motion",
    ]
    config = _config(
        **{
            CONF_PRESENCE_DEVICE_PLATFORMS: [
                "device_tracker",
                "media_player",
                "remote",
                "binary_sensor",
            ]
        }
    )
    result = physical_presence_source_ids(hass, entry, config, loaded_entity_ids=loaded)
    # Remote is selectable but never discovered automatically.
    assert result == sorted(
        entity_id for entity_id in loaded if not entity_id.startswith("remote.")
    )

    only_media = _config(**{CONF_PRESENCE_DEVICE_PLATFORMS: ["media_player"]})
    assert physical_presence_source_ids(
        hass, entry, only_media, loaded_entity_ids=loaded
    ) == ["media_player.tv"]


async def test_remote_is_never_discovered_automatically(hass: HomeAssistant) -> None:
    """Remote `on` has no presence semantics, so a remote in the Area is ignored."""
    entry = _entry(hass)
    hass.states.async_set("remote.living", "on", {})
    config = _config(**{CONF_PRESENCE_DEVICE_PLATFORMS: ["remote", "binary_sensor"]})
    assert (
        physical_presence_source_ids(
            hass, entry, config, loaded_entity_ids=["remote.living"]
        )
        == []
    )


async def test_remote_counts_only_with_explicit_include(hass: HomeAssistant) -> None:
    """A deliberately included remote is a source, following its `on` state."""
    entry = _entry(hass)
    hass.states.async_set("remote.living", "on", {})
    config = _config(
        **{
            CONF_PRESENCE_DEVICE_PLATFORMS: ["remote"],
            CONF_INCLUDE_ENTITIES: ["remote.living"],
        }
    )
    assert physical_presence_source_ids(
        hass, entry, config, loaded_entity_ids=["remote.living"]
    ) == ["remote.living"]


def test_media_player_on_without_playback_is_not_presence(hass: HomeAssistant) -> None:
    """`on` alone is idle, not presence. `playing` is an activity indicator."""
    assert not is_presence_source_active(hass, "media_player.tv", STATE_ON)
    assert is_presence_source_active(hass, "media_player.tv", "playing")


def test_unknown_and_unavailable_are_never_active(hass: HomeAssistant) -> None:
    """Unknown and unavailable states are not negative or positive presence."""
    for domain_entity in (
        "binary_sensor.x",
        "media_player.x",
        "remote.x",
        "device_tracker.x",
    ):
        assert not is_presence_source_active(hass, domain_entity, STATE_UNKNOWN)
        assert not is_presence_source_active(hass, domain_entity, STATE_UNAVAILABLE)


def test_off_is_not_active_for_motion_sources(hass: HomeAssistant) -> None:
    """A suitable source reporting off is a valid inactive state, not presence."""
    assert not is_presence_source_active(hass, "binary_sensor.hall_motion", STATE_OFF)
    assert is_presence_source_active(hass, "binary_sensor.hall_motion", STATE_ON)
