"""One-shot dispatch of already evaluated Light policy decisions."""

from dataclasses import dataclass

from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import Context, HomeAssistant

from custom_components.adaptive_areas.helpers.light_policy import (
    LightPolicyAction,
    LightPolicyDecision,
)
from custom_components.adaptive_areas.helpers.sources import LightSourceSnapshot


@dataclass(frozen=True, slots=True)
class LightExecutionResult:
    """The successful dispatch outcome, not a physical-state verification."""

    executed: bool
    action: LightPolicyAction
    target_entity_ids: tuple[str, ...]


async def async_execute_light_decision(
    hass: HomeAssistant,
    snapshot: LightSourceSnapshot,
    decision: LightPolicyDecision,
    *,
    context: Context | None = None,
) -> LightExecutionResult:
    """Dispatch one on/off decision to the available snapshot targets only."""
    if decision.action not in (LightPolicyAction.TURN_ON, LightPolicyAction.TURN_OFF):
        return LightExecutionResult(False, decision.action, ())

    targets = tuple(
        sorted({target.entity_id for target in snapshot.targets if target.available})
    )
    if not targets:
        return LightExecutionResult(False, decision.action, ())

    service = (
        SERVICE_TURN_ON
        if decision.action is LightPolicyAction.TURN_ON
        else SERVICE_TURN_OFF
    )
    kwargs = {"blocking": True}
    if context is not None:
        kwargs["context"] = context
    await hass.services.async_call(
        LIGHT_DOMAIN, service, {ATTR_ENTITY_ID: targets}, **kwargs
    )
    return LightExecutionResult(True, decision.action, targets)


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
