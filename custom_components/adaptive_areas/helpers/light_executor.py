"""Single automatic service call for one configured light group entity."""

from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant


async def async_execute_light_entity_action(
    hass: HomeAssistant,
    entity_id: str,
    service: str,
    *,
    context: Context,
) -> bool:
    """Send exactly one automatic service call to one configured light or light group entity.

    Used for explicitly configured light group entities (for example the ALL group on a
    clear transition). A single asynchronous call, no retry and no queue: a failure is
    raised to the caller, which reports it and does not repeat the command.
    """
    await hass.services.async_call(
        LIGHT_DOMAIN,
        service,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
        context=context,
    )
    return True
