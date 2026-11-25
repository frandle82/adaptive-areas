"""Own automatic light group calls: a bounded registry of their Context ids.

A group call registers its Context id before the asynchronous service call. A state change whose
Context (or its parent) is a registered id belongs to this Area's own automation. Any other change
is handled by the group rules in light.py. The registry keeps the newest entries only (FIFO,
bounded). Nothing else is recorded: no signal numbers, no completion state, no listeners.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from homeassistant.core import Context

_REGISTRY = "light_request_registry"
_REGISTRY_LIMIT = 256
_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class OwnRequest:
    """One registered automatic group call of an Area."""

    context_id: str
    source: str
    service: str
    target: str
    group: str | None = None


def _locked(func):
    """Serialize registry access: group decisions may run in executor threads."""

    def _wrapper(*args, **kwargs):
        with _LOCK:
            return func(*args, **kwargs)

    _wrapper.__name__ = func.__name__
    _wrapper.__doc__ = func.__doc__
    return _wrapper


def _registry(area: Any) -> OrderedDict:
    registry = getattr(area, _REGISTRY, None)
    if not isinstance(registry, OrderedDict):
        registry = OrderedDict()
        setattr(area, _REGISTRY, registry)
    return registry


@_locked
def new_light_group_context(
    area: Any,
    *,
    service: str = "turn_on",
    target: str = "",
    group: str | None = None,
) -> Context:
    """Create the Context of one automatic group call and register its id."""
    context = Context()
    registry = _registry(area)
    registry[context.id] = OwnRequest(
        context_id=context.id,
        source="group",
        service=service,
        target=target,
        group=group,
    )
    while len(registry) > _REGISTRY_LIMIT:
        registry.popitem(last=False)
    return context


@_locked
def request_for_context(area: Any, context_id: str) -> OwnRequest | None:
    """Return the registered request of this Context id, if any (read only)."""
    return _registry(area).get(context_id)
