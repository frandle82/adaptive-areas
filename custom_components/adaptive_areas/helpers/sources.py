"""Shared entity-source discovery for Adaptive Areas features."""

from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Any

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
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from custom_components.adaptive_areas.const import (
    CONF_EXCLUDE_ENTITIES,
    CONF_FEATURE_LIGHT,
    CONF_GLOBAL_LIGHT_SENSOR,
    CONF_GLOBAL_OPTIONS,
    CONF_ID,
    CONF_INCLUDE_ENTITIES,
    CONF_PRESENCE_DEVICE_PLATFORMS,
    CONF_PRESENCE_SENSOR_DEVICE_CLASS,
    DEFAULT_PRESENCE_DEVICE_PLATFORMS,
    DOMAIN,
)

if TYPE_CHECKING:
    from custom_components.adaptive_areas.base.adaptive import AdaptiveArea

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
_INACTIVE_TRACKER_STATES = frozenset(("not_home", "work", "school"))


@dataclass(frozen=True, slots=True)
class LightTargetSource:
    """One discovered physical Light target and its current availability."""

    entity_id: str
    available: bool


@dataclass(frozen=True, slots=True)
class LightSourceSnapshot:
    """Read-only inputs available to a future Light policy."""

    area_id: str
    targets: tuple[LightTargetSource, ...]
    illuminance_entity_id: str | None
    illuminance_available: bool
    illuminance_value: float | None
    presence_source_entity_ids: tuple[str, ...]
    presence_available: bool
    presence_state: bool | None

    @property
    def target_light_entity_ids(self) -> tuple[str, ...]:
        """Return stable target IDs without exposing availability internals."""
        return tuple(target.entity_id for target in self.targets)


def device_belongs_to_area(
    hass: HomeAssistant,
    device_id: str | None,
    area_id: str | None,
) -> bool:
    """Return whether a device's own or inherited Area matches an Area."""
    if device_id is None or area_id is None:
        return False
    device_registry = async_get_device_registry(hass)
    visited: set[str] = set()
    device: DeviceEntry | None = device_registry.async_get(device_id)
    while device is not None and device.id not in visited:
        visited.add(device.id)
        if device.area_id is not None:
            return device.area_id == area_id
        parent_device_id = getattr(device, "parent_device_id", None)
        if parent_device_id is None:
            return False
        device = device_registry.async_get(parent_device_id)
    return False


def is_presence_source_active(
    hass: HomeAssistant,
    entity_id: str,
    state: State | str | None,
    *,
    area_id: str | None = None,
) -> bool:
    """Return whether a source has an active state for its entity domain."""
    state_value = state.state if isinstance(state, State) else state
    if state_value is None:
        return False
    normalized_state = state_value.casefold()
    if normalized_state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return False
    domain = entity_id.partition(".")[0]
    if domain == DEVICE_TRACKER_DOMAIN:
        if normalized_state == "home":
            return True
        if normalized_state in _INACTIVE_TRACKER_STATES or area_id is None:
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
            # Explicitly included entities may exist only as state (for example
            # template entities without unique_id). The panel offers every state,
            # so an explicit include must not be dropped silently.
            if (
                entity_id in explicit
                and hass.states.get(entity_id) is not None
                and (domain is None or entity_id.partition(".")[0] == domain)
            ):
                result.add(entity_id)
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
    for entry in entity_registry.entities.values():
        if entry.entity_id in result or entry.entity_id in excluded:
            continue
        if domain is not None and entry.domain != domain:
            continue
        if entry.disabled or entry.config_entry_id == config_entry.entry_id:
            continue
        if device_belongs_to_area(hass, entry.device_id, area_id):
            result.add(entry.entity_id)
    return result


def light_source_snapshot(area: AdaptiveArea) -> LightSourceSnapshot | None:
    """Resolve read-only Light inputs for one regular Area with the new feature."""
    if area.is_meta() or not area.has_feature(CONF_FEATURE_LIGHT):
        return None

    target_ids = sorted(
        area_entity_ids(
            area.hass,
            area.hass_config,
            area.config,
            domain="light",
        )
    )
    targets = tuple(
        LightTargetSource(
            entity_id=entity_id,
            available=_state_available(area.hass.states.get(entity_id)),
        )
        for entity_id in target_ids
    )
    global_options = area.hass_config.options.get(CONF_GLOBAL_OPTIONS, {})
    illuminance_entity_id = (
        global_options.get(CONF_GLOBAL_LIGHT_SENSOR)
        if isinstance(global_options, dict)
        else None
    )
    illuminance_entity_id = (
        illuminance_entity_id if isinstance(illuminance_entity_id, str) else None
    )
    illuminance_state = (
        area.hass.states.get(illuminance_entity_id)
        if illuminance_entity_id is not None
        else None
    )
    presence_source_entity_ids = tuple(sorted(set(area.get_presence_sensors())))
    presence_available = any(
        _state_available(area.hass.states.get(entity_id))
        for entity_id in presence_source_entity_ids
    )
    return LightSourceSnapshot(
        area_id=area.id,
        targets=targets,
        illuminance_entity_id=illuminance_entity_id,
        illuminance_available=_state_available(illuminance_state),
        illuminance_value=_numeric_state_value(illuminance_state),
        presence_source_entity_ids=presence_source_entity_ids,
        presence_available=presence_available,
        presence_state=area.is_occupied() if presence_available else None,
    )


def _state_available(state: State | None) -> bool:
    """Return availability without excluding a configured/discovered source."""
    return state is not None and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)


def _numeric_state_value(state: State | None) -> float | None:
    """Return a finite numeric source value without unit conversion or policy."""
    if not _state_available(state):
        return None
    try:
        value = float(state.state)
    except TypeError, ValueError:
        return None
    return value if isfinite(value) else None


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
    # An explicit include is a deliberate user choice: it bypasses only the
    # binary_sensor device-class filter. Exclusions were already applied by
    # area_entity_ids(), and unknown/unavailable states are never active.
    explicit = {
        entity_id
        for entity_id in config.get(CONF_INCLUDE_ENTITIES, [])
        if isinstance(entity_id, str)
    }
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
            and entity_id not in explicit
            and entity_device_class(hass, entity_id) not in device_classes
        ):
            continue
        result.append(entity_id)
    return result
