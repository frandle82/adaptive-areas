"""Boundary of the automatic group Context registry (helpers/light_origin.py).

Calls the production functions directly with a plain Area-like object; no decision logic is replaced.
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.adaptive_areas.helpers.light_origin import (
    _REGISTRY,
    _REGISTRY_LIMIT,
    new_light_group_context,
    request_for_context,
)


def test_newest_group_contexts_stay_recognised_and_older_ones_are_dropped() -> None:
    """Older group calls are dropped beyond the bound; the newest ones stay recognised."""
    area = SimpleNamespace()
    contexts = [
        new_light_group_context(area, group="overhead")
        for _ in range(_REGISTRY_LIMIT + 40)
    ]
    assert request_for_context(area, contexts[0].id) is None
    assert request_for_context(area, contexts[39].id) is None
    assert request_for_context(area, contexts[40].id) is not None
    assert request_for_context(area, contexts[-1].id) is not None
    assert len(getattr(area, _REGISTRY)) == _REGISTRY_LIMIT


def test_the_last_sixty_four_group_calls_are_recognised_without_a_second_list() -> None:
    """The newest 64 group calls stay recognised; no second bounded list is needed."""
    area = SimpleNamespace()
    contexts = [new_light_group_context(area, group="overhead") for _ in range(200)]
    assert all(request_for_context(area, c.id) is not None for c in contexts[-64:])


def test_request_fields_are_kept_for_the_registered_call() -> None:
    """The registered request keeps the service, target and group of the call."""
    area = SimpleNamespace()
    context = new_light_group_context(
        area, service="turn_off", target="light.group_a", group="all"
    )
    request = request_for_context(area, context.id)
    assert request is not None
    assert (request.source, request.service, request.target, request.group) == (
        "group",
        "turn_off",
        "light.group_a",
        "all",
    )
