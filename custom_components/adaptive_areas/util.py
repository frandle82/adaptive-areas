"""Adaptive Areas Util Functions.

Small helper functions that are used more than once.
"""

from collections.abc import Sequence
import logging

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_registry import async_get as entityreg_async_get

_LOGGER = logging.getLogger(__name__)


def cleanup_removed_entries(
    hass: HomeAssistant, entity_list: Sequence[Entity], old_ids: list[dict[str, str]]
) -> None:
    """Remove generated entities of one Area that this setup no longer provides.

    `old_ids` lists the registered entities the Area owns. An entity is kept when this
    setup creates an entity with the same unique ID: the registry entity ID may differ
    from the generated default (renamed by the user, or suffixed by Home Assistant).
    """
    new_unique_ids = {entity.unique_id for entity in entity_list}
    _LOGGER.debug(
        "Checking for cleanup. Old entity list: %s, New unique IDs: %s",
        old_ids,
        new_unique_ids,
    )
    entity_registry = entityreg_async_get(hass)
    for entity_dict in old_ids:
        entity_id = entity_dict[ATTR_ENTITY_ID]
        entry = entity_registry.async_get(entity_id)
        if entry is None or entry.unique_id in new_unique_ids:
            continue
        _LOGGER.debug("Cleaning up old entity %s", entity_id)
        entity_registry.async_remove(entity_id)
