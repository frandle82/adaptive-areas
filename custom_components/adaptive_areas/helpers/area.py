"""Adaptive Areas Area Helper Functions.

Small helper functions for area and Adaptive Area objects.
"""

import importlib.util
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ID, ATTR_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.area_registry import (
    AreaEntry,
    async_get as areareg_async_get,
)
from homeassistant.helpers.device_registry import (
    async_entries_for_config_entry as devicereg_entries_for_config_entry,
)
from homeassistant.helpers.device_registry import async_get as devicereg_async_get
from homeassistant.helpers.entity_registry import (
    RegistryEntry,
    async_get as entityreg_async_get,
)

from custom_components.adaptive_areas.base.adaptive import (
    BasicArea,
    AdaptiveArea,
    AdaptiveMetaArea,
)
from custom_components.adaptive_areas.const import (
    CONF_AREAS,
    CONF_TYPE,
    AREA_TYPE_META,
    ADAPTIVE_DEVICE_ID_PREFIX,
    DOMAIN,
    DATA_AREAS,
    DATA_AREA_OBJECT,
    MODULE_DATA,
    MetaAreaIcons,
    MetaAreaType,
)

_LOGGER = logging.getLogger(__name__)
HAS_FLOOR_REGISTRY = (
    importlib.util.find_spec("homeassistant.helpers.floor_registry") is not None
)


def basic_area_from_meta(area_id: str, name: str | None = None) -> BasicArea:
    """Create a BasicArea from a name."""

    basic_area = BasicArea()
    if not name:
        basic_area.name = area_id.capitalize()
    basic_area.id = area_id
    basic_area.is_meta = True

    meta_area_icon_map: dict[str, str] = {}
    meta_area_icon_map = {
        MetaAreaType.EXTERIOR.value: MetaAreaIcons.EXTERIOR.value,
        MetaAreaType.INTERIOR.value: MetaAreaIcons.INTERIOR.value,
        MetaAreaType.GLOBAL.value: MetaAreaIcons.GLOBAL.value,
    }

    basic_area.icon = meta_area_icon_map.get(area_id, None)

    return basic_area


def basic_area_from_object(area: AreaEntry) -> BasicArea:
    """Create a BasicArea from an AreaEntry object."""

    basic_area = BasicArea()
    basic_area.name = area.name
    basic_area.id = area.id
    basic_area.icon = area.icon
    basic_area.floor_id = area.floor_id

    return basic_area


def basic_area_from_floor(floor: Any) -> BasicArea:
    """Create a BasicArea from an AreaEntry object."""

    basic_area = BasicArea()
    basic_area.name = floor.name
    basic_area.id = floor.floor_id
    default_icon = (
        f"mdi:home-floor-{floor.level}"  # noqa: E231
        if floor.level is not None
        else "mdi:home"  # noqa: E231
    )
    basic_area.icon = floor.icon or default_icon
    basic_area.floor_id = floor.floor_id
    basic_area.is_meta = True

    return basic_area


def get_adaptive_area_for_config_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, area_config: dict | None = None
) -> AdaptiveArea | None:
    """Return adaptive area object for given config entry."""

    config = area_config or {**config_entry.data, **config_entry.options}
    area_id = config[ATTR_ID]
    area_name = config[ATTR_NAME]

    adaptive_area: AdaptiveArea | None = None

    _LOGGER.debug("%s: Setting up entry.", area_name)

    # Load floors (if supported by the running HA version)
    floors = []
    floor_registry = None
    if HAS_FLOOR_REGISTRY:
        from homeassistant.helpers.floor_registry import (
            async_get as floorreg_async_get,
        )

        floor_registry = floorreg_async_get(hass)
        floors = floor_registry.async_list_floors()

    non_floor_meta_ids = [
        meta_area_type
        for meta_area_type in MetaAreaType
        if meta_area_type != MetaAreaType.FLOOR
    ]
    floor_ids = [f.floor_id for f in floors]

    if area_id in non_floor_meta_ids:
        # Non-floor Meta-Area (Global/Interior/Exterior)
        meta_area = basic_area_from_meta(area_id)
        adaptive_area = AdaptiveMetaArea(hass, meta_area, config_entry, config)
    elif area_id in floor_ids and floor_registry is not None:
        # Floor Meta-Area
        floor_entry = floor_registry.async_get_floor(area_id)
        assert floor_entry is not None
        meta_area = basic_area_from_floor(floor_entry)
        adaptive_area = AdaptiveMetaArea(hass, meta_area, config_entry, config)
    else:
        # Regular Area
        area_registry = areareg_async_get(hass)
        area = area_registry.async_get_area(area_id)

        if not area:
            _LOGGER.warning("%s: ID '%s' not found on registry", area_name, area_id)
            return None

        _LOGGER.debug("%s: Got area from registry: %s", area_name, str(area))

        adaptive_area = AdaptiveArea(
            hass,
            basic_area_from_object(area),
            config_entry,
            config,
        )

    return adaptive_area


def get_adaptive_areas_for_config_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> list[AdaptiveArea]:
    """Build every runtime Area owned by one Global ConfigEntry."""
    areas = config_entry.options.get(CONF_AREAS, config_entry.data.get(CONF_AREAS))
    if not isinstance(areas, dict):
        area = get_adaptive_area_for_config_entry(hass, config_entry)
        return [area] if area is not None else []
    ordered_areas = sorted(
        areas.items(),
        key=lambda item: (item[1].get(CONF_TYPE) == AREA_TYPE_META, item[0]),
    )
    return [
        area
        for _area_id, area_config in ordered_areas
        if isinstance(area_config, dict)
        and (
            area := get_adaptive_area_for_config_entry(hass, config_entry, area_config)
        )
        is not None
    ]


def get_runtime_areas_for_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> list[AdaptiveArea]:
    """Return loaded Areas for an entry, including legacy single-Area entries."""
    runtime = hass.data.get(MODULE_DATA, {}).get(config_entry.entry_id, {})
    if areas := runtime.get(DATA_AREAS):
        return list(areas.values())
    if area := runtime.get(DATA_AREA_OBJECT):
        return [area]
    return []


def iter_runtime_areas(hass: HomeAssistant):
    """Yield every loaded Adaptive Area across legacy and container runtimes."""
    for runtime in hass.data.get(MODULE_DATA, {}).values():
        if areas := runtime.get(DATA_AREAS):
            yield from areas.values()
        elif area := runtime.get(DATA_AREA_OBJECT):
            yield area


def refresh_meta_area_sources(hass: HomeAssistant) -> None:
    """Reconcile every loaded Meta Area after an Adaptive Areas entity registered.

    A Meta Area snapshots the generated entities of its children. Children can
    register those entities after the Meta Area loaded, so each registration
    refreshes all Meta Areas. The refresh is idempotent and does not reload entries.
    """
    for area in iter_runtime_areas(hass):
        if area.is_meta():
            area.async_refresh_sources()


def entity_belongs_to_area(entity: RegistryEntry, area: AdaptiveArea) -> bool:
    """Return whether an Adaptive Areas registry entity belongs to one Area.

    The generated unique ID is the stable Area-specific identity; the config entry
    only identifies its current container owner.
    """
    return entity.platform == DOMAIN and f"_{area.slug}_" in f"_{entity.unique_id}_"


def generated_entities_for_area(
    hass: HomeAssistant, area: AdaptiveArea
) -> list[RegistryEntry]:
    """Return generated entities for one Area, scoped independently of owner ID."""
    registry = entityreg_async_get(hass)
    return [
        entity
        for entity in registry.entities.get_entries_for_config_entry_id(
            area.hass_config.entry_id
        )
        if entity_belongs_to_area(entity, area)
    ]


def transfer_area_entities_to_container(
    hass: HomeAssistant,
    *,
    old_entry_id: str,
    global_entry_id: str,
    area: AdaptiveArea,
) -> list[str]:
    """Transfer verified Area entity ownership without changing entity identity."""
    registry = entityreg_async_get(hass)
    candidates = [
        entity
        for entity in registry.entities.get_entries_for_config_entry_id(old_entry_id)
        if entity_belongs_to_area(entity, area)
    ]
    for entity in candidates:
        conflict = next(
            (
                other
                for other in registry.entities.get_entries_for_config_entry_id(
                    global_entry_id
                )
                if other.entity_id != entity.entity_id
                and other.platform == entity.platform
                and other.unique_id == entity.unique_id
            ),
            None,
        )
        if conflict is not None:
            raise ValueError(
                f"Conflicting generated entity unique ID: {entity.unique_id}"
            )
    for entity in candidates:
        registry.async_update_entity(entity.entity_id, config_entry_id=global_entry_id)
    return [entity.entity_id for entity in candidates]


def transfer_area_devices_to_container(
    hass: HomeAssistant,
    *,
    old_entry_id: str,
    global_entry_id: str,
    area_id: str,
) -> list[str]:
    """Transfer only the stable Adaptive Areas device for one Area."""
    registry = devicereg_async_get(hass)
    identifier = (DOMAIN, f"{ADAPTIVE_DEVICE_ID_PREFIX}{area_id}")
    candidates = [
        device
        for device in devicereg_entries_for_config_entry(registry, old_entry_id)
        if identifier in device.identifiers
    ]
    for device in candidates:
        registry.async_update_device(device.id, new_config_entry_id=global_entry_id)
    return [device.id for device in candidates]


def get_area_from_config_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> AdaptiveArea | AdaptiveMetaArea | None:
    """Return area object for given config entry."""

    areas = get_runtime_areas_for_entry(hass, config_entry)
    return areas[0] if len(areas) == 1 else None
