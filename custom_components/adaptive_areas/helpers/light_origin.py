"""Own light calls as requests: registration, completion, and signal correlation.

Four states are kept apart on purpose:
- registered request: the integration decided to issue a call and registered it before
  the asynchronous service execution (state "pending");
- observed service call: EVENT_CALL_SERVICE was seen for the request's Context;
- completed execution: the policy's awaited dispatch returned, or a group call's own
  events (group entity and forwarded member list) were observed;
- confirmed light state: read separately and never used as proof of a call.

A request carries the number of the area signal that was dispatched when it was
registered. Nothing else is changed: no Context parent, no payload, no call order, no
target. The registry is bounded. Manual-action detection keeps its own structures.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import Context

_SEQUENCE = "light_signal_sequence"
_CURRENT = "light_signal_current"
_PRE_STATES = "light_signal_pre_states"
_REGISTRY = "light_request_registry"
_LISTENERS = "light_request_listeners"
_REGISTRY_LIMIT = 256
_EXECUTOR_JOBS = "light_executor_jobs"
_UNFINISHED = "light_unfinished_requests"

PENDING = "pending"
COMPLETED = "completed"
FAILED = "failed"

_LOCK = threading.RLock()
_THREAD = threading.local()
_UNBOUND = object()


@dataclass(slots=True)
class OwnRequest:
    """One registered integration light call."""

    context_id: str
    signal_id: int | None
    source: str  # "group" (the only automatic source since policy-only was removed)
    service: str
    target: str
    group: str | None = None
    state: str = PENDING
    entity_seen: bool = False
    members_seen: bool = False
    observed_targets: list[str] = field(default_factory=list)
    confirmation: str | None = None

    def summary(self) -> dict[str, Any]:
        """Privacy-minimal view of one request (no context ids)."""
        return {
            "source": self.source,
            "group": self.group,
            "service": self.service,
            "target": self.target,
            "state": self.state,
            "observed": len(self.observed_targets),
        }


# -- Signal numbering --------------------------------------------------------------


def begin_area_signal(area: Any) -> int:
    """Assign the next signal number, make it current, and freeze the light states."""
    previous = getattr(area, _SEQUENCE, 0)
    sequence = (previous if isinstance(previous, int) else 0) + 1
    setattr(area, _SEQUENCE, sequence)
    setattr(area, _CURRENT, sequence)
    setattr(area, _PRE_STATES, _read_light_states(area))
    return sequence


def end_area_signal(area: Any) -> None:
    """Clear the current signal number and its frozen light states."""
    setattr(area, _CURRENT, None)
    setattr(area, _PRE_STATES, None)


@contextmanager
def signal_bound_to_thread(signal: int | None):
    """Bind the signal number of a dispatch to the thread that runs its listener."""
    previous = getattr(_THREAD, "bound", _UNBOUND)
    _THREAD.bound = signal
    try:
        yield
    finally:
        _THREAD.bound = previous


def run_with_signal(signal: int | None, func: Any, *args: Any) -> Any:
    """Run one listener in its executor thread with the dispatch's signal number bound."""
    with signal_bound_to_thread(signal):
        return func(*args)


def current_area_signal(area: Any) -> int | None:
    """Return the signal number of the dispatch this code belongs to, if known.

    A listener running in an executor thread sees the number bound by run_with_signal;
    the loop-side number is only used when nothing is bound to the thread.
    """
    bound = getattr(_THREAD, "bound", _UNBOUND)
    if bound is not _UNBOUND:
        return bound
    value = getattr(area, _CURRENT, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _read_light_states(area: Any) -> dict[str, str | None]:
    hass = getattr(area, "hass", None)
    entries = getattr(area, "entities", None)
    states: dict[str, str | None] = {}
    if not isinstance(entries, dict) or hass is None:
        return states
    for entry in entries.get("light", []):
        entity_id = entry.get("entity_id") if isinstance(entry, dict) else None
        if not isinstance(entity_id, str):
            continue
        state = hass.states.get(entity_id)
        states[entity_id] = state.state if state is not None else None
    return states


# -- Registry ----------------------------------------------------------------------


def _locked(func):
    """Serialize registry access: group listeners may run in executor threads."""

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


def _unfinished(area: Any) -> dict[str, OwnRequest]:
    """Return the unfinished requests; the bounded registry never drops them."""
    unfinished = getattr(area, _UNFINISHED, None)
    if not isinstance(unfinished, dict):
        unfinished = {}
        setattr(area, _UNFINISHED, unfinished)
    return unfinished


def _register(area: Any, request: OwnRequest, context: Context) -> Context:
    """Register a request. Unfinished requests stay in their own table, never evicted."""
    registry = _registry(area)
    registry[context.id] = request
    _unfinished(area)[context.id] = request
    # The bounded registry only forgets finished entries; an unfinished one is kept.
    for key in list(registry):
        if len(registry) <= _REGISTRY_LIMIT:
            break
        if key not in _unfinished(area):
            del registry[key]
    return context


@_locked
def new_light_group_context(
    area: Any,
    *,
    service: str = "turn_on",
    target: str = "",
    group: str | None = None,
) -> Context:
    """Context for one group call, registered as a pending request of the current signal."""
    context = Context()
    request = OwnRequest(
        context_id=context.id,
        signal_id=current_area_signal(area),
        source="group",
        service=service,
        target=target,
        group=group,
    )
    return _register(area, request, context)


@_locked
def request_for_context(area: Any, context_id: str) -> OwnRequest | None:
    """Return the registered request of this Context id, if any (read only)."""
    return _unfinished(area).get(context_id) or _registry(area).get(context_id)


@_locked
@_locked
@_locked
def complete_request(area: Any, context_id: str) -> None:
    """Mark a request completed: the execution finished (proof: awaited return)."""
    request = request_for_context(area, context_id)
    if request is not None and request.state == PENDING:
        request.state = COMPLETED
        _unfinished(area).pop(context_id, None)
        _notify(area, request.signal_id)


@_locked
def fail_request(area: Any, context_id: str) -> None:
    """Mark a request failed and finished (proof: the call raised)."""
    request = request_for_context(area, context_id)
    if request is not None and request.state == PENDING:
        request.state = FAILED
        _unfinished(area).pop(context_id, None)
        _notify(area, request.signal_id)


@_locked
@_locked
@_locked
@_locked
@_locked
# -- Completion listeners ---------------------------------


def _notify(area: Any, signal_id: int | None) -> None:
    """Tell listeners about a change; hop to the loop thread when called from a worker."""
    hass = getattr(area, "hass", None)
    loop_thread = getattr(hass, "loop_thread_id", None)
    if (
        hass is not None
        and loop_thread is not None
        and threading.get_ident() != loop_thread
    ):
        hass.loop.call_soon_threadsafe(_call_listeners, area, signal_id)
        return
    _call_listeners(area, signal_id)


def _call_listeners(area: Any, signal_id: int | None) -> None:
    listeners = getattr(area, _LISTENERS, None)
    if not isinstance(listeners, list):
        return
    for listener in list(listeners):
        listener(signal_id)


@_locked
@_locked
@_locked
def track_executor_job(area: Any, future: Any) -> Any:
    """Remember a listener's executor job until it is done (observation and tests only).

    The job is a background task of Home Assistant; nothing waits for it unless asked.
    Tracking changes no behaviour: the future is only stored and released on completion.
    """
    jobs = getattr(area, _EXECUTOR_JOBS, None)
    if not isinstance(jobs, set):
        jobs = set()
        setattr(area, _EXECUTOR_JOBS, jobs)
    jobs.add(future)
    future.add_done_callback(jobs.discard)
    return future
