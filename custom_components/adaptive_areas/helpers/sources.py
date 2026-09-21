"""Shared entity-source discovery for Adaptive Areas features."""

from collections.abc import Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.device_tracker.const import (
    DOMAIN as DEVICE_TRACKER_DOMAIN,
)
from homeassistant.components.media_player.const import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.components.remote import DOMAIN as REMOTE_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    STATE_ON,
    STATE_OPEN,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.area_registry import async_get as async_get_area_registry
from homeassistant.helpers.device_registry import (
    async_entries_for_area,
    async_get as async_get_device_registry,
)
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.const import (
    CONF_EXCLUDE_ENTITIES,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    CONF_PRESENCE_SENSOR_DEVICE_CLASS,
    DEFAULT_PRESENCE_DEVICE_PLATFORMS,
    DOMAIN,
)

_PRESENCE_SOURCE_ACTIVE_STATES: dict[str, frozenset[str]] = {
    BINARY_SENSOR_DOMAIN: frozenset((STATE_ON, STATE_OPEN)),
    MEDIA_PLAYER_DOMAIN: frozenset((STATE_ON, STATE_PLAYING)),
    REMOTE_DOMAIN: frozenset((STATE_ON,)),
    # Presence Hold is an integration-owned source, not a discoverable platform.
    SWITCH_DOMAIN: frozenset((STATE_ON,)),
}

SUPPORTED_PHYSICAL_PRESENCE_SOURCE_DOMAINS = frozenset(
    (
        BINARY_SENSOR_DOMAIN,
        DEVICE_TRACKER_DOMAIN,
        MEDIA_PLAYER_DOMAIN,
        REMOTE_DOMAIN,
    )
)
_NON_ROOM_TRACKER_STATES = frozenset(("home", "not_home", "work", "school"))


def is_presence_source_active(
    hass: HomeAssistant,
    entity_id: str,
    state: State | str | None,
    *,
    area_id: str | None = None,
) -> bool:
    """Return whether a source has an active state for its entity domain."""
    state_value = state.state if isinstance(state, State) else state
    if state_value in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
        return False
    domain = entity_id.partition(".")[0]
    if domain == DEVICE_TRACKER_DOMAIN:
        if area_id is None or state_value.casefold() in _NON_ROOM_TRACKER_STATES:
            return False
        if state_value == area_id:
            return True
        matched_area = async_get_area_registry(hass).async_get_area_by_name(state_value)
        return matched_area is not None and matched_area.id == area_id
    return state_value in _PRESENCE_SOURCE_ACTIVE_STATES.get(domain, frozenset())


def entity_device_class(hass: HomeAssistant, entity_id: str) -> str | None:
    """Return an entity's current or registered device class."""
    state = hass.states.get(entity_id)
    device_class = (
        state.attributes.get(ATTR_DEVICE_CLASS) if state is not None else None
    )
    if device_class is not None:
        return str(device_class)
    entry = async_get_entity_registry(hass).async_get(entity_id)
    if entry is None:
        return None
    return entry.device_class or entry.original_device_class


def area_entity_ids(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    config: dict[str, Any],
    *,
    domain: str | None = None,
) -> set[str]:
    """Return usable registered Area entities plus explicit includes."""
    area_id = config.get(CONF_ID)
    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    explicit = {
        entity_id
        for entity_id in config.get(CONF_INCLUDE_ENTITIES, [])
        if isinstance(entity_id, str)
    }
    candidates = {
        entry.entity_id
        for entry in entity_registry.entities.get_entries_for_area_id(area_id)
    }
    for device in async_entries_for_area(device_registry, area_id):
        candidates.update(
            entry.entity_id
            for entry in entity_registry.entities.get_entries_for_device_id(device.id)
        )
    candidates.update(explicit)
    excluded = set(config.get(CONF_EXCLUDE_ENTITIES, []))
    result: set[str] = set()
    for entity_id in candidates - excluded:
        entry = entity_registry.async_get(entity_id)
        if entry is None:
            continue
        if domain is not None and entry.domain != domain:
            continue
        if entity_id not in explicit and (
            entry.disabled or entry.config_entry_id == config_entry.entry_id
        ):
            continue
        if entry.platform == DOMAIN and entry.config_entry_id == config_entry.entry_id:
            continue
        result.add(entity_id)
    return result


def physical_presence_source_ids(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    config: dict[str, Any],
    *,
    loaded_entity_ids: Iterable[str] = (),
) -> list[str]:
    """Return physical entities accepted by Adaptive Area presence tracking."""
    platforms = config.get(
        CONF_PRESENCE_DEVICE_PLATFORMS, DEFAULT_PRESENCE_DEVICE_PLATFORMS
    )
    device_classes = config.get(CONF_PRESENCE_SENSOR_DEVICE_CLASS, [])
    result: list[str] = []
    candidates = area_entity_ids(hass, config_entry, config)
    candidates.update(loaded_entity_ids)
    for entity_id in sorted(candidates):
        domain = entity_id.partition(".")[0]
        if (
            domain not in platforms
            or domain not in SUPPORTED_PHYSICAL_PRESENCE_SOURCE_DOMAINS
        ):
            continue
        if (
            domain == "binary_sensor"
            and entity_device_class(hass, entity_id) not in device_classes
        ):
            continue
        result.append(entity_id)
    return result
