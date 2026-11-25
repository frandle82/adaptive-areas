"""Fault injection at the Home Assistant service call for automatic group commands.

The automatic group command is one native `light.turn_on` / `light.turn_off` call with a single
entity target and a context. Tests inject a failure there; the native call is captured before the
injection, so a passthrough never recurses into the injected function.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant


def native_group_command(hass: HomeAssistant) -> Callable[..., Awaitable[bool]]:
    """Return the native light service call, captured before any injection."""
    real = hass.services.async_call

    async def _call(
        hass_: HomeAssistant, entity_id: str, service: str, *, context: Context
    ) -> bool:
        await real(
            LIGHT_DOMAIN,
            service,
            {ATTR_ENTITY_ID: entity_id},
            blocking=True,
            context=context,
        )
        return True

    return _call


def install_group_command_fault(
    monkeypatch: Any,
    hass: HomeAssistant,
    fault: Callable[..., Awaitable[Any]],
) -> None:
    """Route automatic single-entity light commands of this hass through `fault`.

    The class method is patched (the registry has slots); other registries and other calls keep the
    original method, and monkeypatch restores it after the test.
    """
    registry_class = type(hass.services)
    original = registry_class.async_call

    async def _wrapped(
        self, domain, service, service_data=None, blocking=False, context=None, **kwargs
    ):
        data = service_data or {}
        target = data.get(ATTR_ENTITY_ID)
        if (
            self is hass.services
            and domain == LIGHT_DOMAIN
            and blocking
            and context is not None
            and isinstance(target, str)
            and set(data) == {ATTR_ENTITY_ID}
            and not kwargs
        ):
            return await fault(hass, target, service, context=context)
        return await original(
            self,
            domain,
            service,
            service_data,
            blocking=blocking,
            context=context,
            **kwargs,
        )

    monkeypatch.setattr(registry_class, "async_call", _wrapped)
