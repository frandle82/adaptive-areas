"""Unique light ownership: pure checks on configuration snapshots (no Home Assistant)."""

from __future__ import annotations

from custom_components.adaptive_areas.const import (
    CONF_ACCENT_LIGHTS,
    CONF_INCLUDE_ENTITIES,
    CONF_OVERHEAD_LIGHTS,
    CONF_SLEEP_LIGHTS,
)
from custom_components.adaptive_areas.helpers.light_ownership import (
    MAX_GROUP_NODES,
    describe,
    expand_members,
    find_ownership_conflicts,
    resolve_group_tree,
)

L1, L2, L3 = "light.one", "light.two", "light.three"
GROUP = "light.adaptive_areas_light_groups_kitchen_overhead_lights"


def test_distinct_lights_give_no_conflict() -> None:
    """Two Areas with different physical lights: no conflict (the regular case)."""
    areas = {
        "e1/kitchen": {CONF_OVERHEAD_LIGHTS: [L1]},
        "e1/living": {CONF_OVERHEAD_LIGHTS: [L2]},
    }
    assert find_ownership_conflicts(areas) == []


def test_same_light_in_two_areas_is_a_conflict() -> None:
    """A light as controllable member in two Areas is reported with both owners."""
    areas = {
        "e1/kitchen": {CONF_OVERHEAD_LIGHTS: [L1]},
        "e2/living": {CONF_SLEEP_LIGHTS: [L1]},
    }
    conflicts = find_ownership_conflicts(areas)
    assert [(c.light, c.areas) for c in conflicts] == [
        (L1, ("e1/kitchen", "e2/living"))
    ]
    assert describe(conflicts)[0].startswith(
        "light.one is a controllable group member of"
    )


def test_light_group_members_are_resolved_before_comparison() -> None:
    """A light group entity is expanded: its physical member collides with another Area."""
    areas = {
        "e1/kitchen": {CONF_OVERHEAD_LIGHTS: [GROUP]},
        "e1/living": {CONF_ACCENT_LIGHTS: [L1]},
    }
    members = {GROUP: [L1, L2]}
    conflicts = find_ownership_conflicts(areas, members)
    assert [c.light for c in conflicts] == [L1]
    assert all(c.light != GROUP for c in conflicts)


def test_group_entity_itself_is_never_compared_as_a_target() -> None:
    """Two Areas that both list the same group entity still compare only physical lights."""
    areas = {
        "e1/a": {CONF_OVERHEAD_LIGHTS: [GROUP]},
        "e1/b": {CONF_OVERHEAD_LIGHTS: [GROUP]},
    }
    members = {GROUP: [L1]}
    assert [c.light for c in find_ownership_conflicts(areas, members)] == [L1]


def test_include_entities_are_scope_not_group_membership() -> None:
    """A light only in another Area's include list is not a controllable member: no conflict."""
    areas = {
        "e1/kitchen": {CONF_OVERHEAD_LIGHTS: [L1]},
        "e1/living": {CONF_INCLUDE_ENTITIES: [L1]},
    }
    assert find_ownership_conflicts(areas) == []


def test_same_light_twice_in_one_area_is_not_a_conflict() -> None:
    """A light listed in two group lists of one Area belongs to that one Area."""
    areas = {"e1/kitchen": {CONF_OVERHEAD_LIGHTS: [L1], CONF_SLEEP_LIGHTS: [L1]}}
    assert find_ownership_conflicts(areas) == []


def test_multiple_entries_are_compared_by_their_full_keys() -> None:
    """Config Entries are separate owners: the same light in two entries is a conflict."""
    areas = {
        "entry-1/kitchen": {CONF_OVERHEAD_LIGHTS: [L3]},
        "entry-2/kitchen": {CONF_OVERHEAD_LIGHTS: [L3]},
    }
    assert [c.areas for c in find_ownership_conflicts(areas)] == [
        ("entry-1/kitchen", "entry-2/kitchen")
    ]


def test_unknown_group_entity_is_treated_as_physical_light() -> None:
    """A light group without a known membership cannot hide a conflict."""
    assert expand_members([GROUP], {}) == frozenset({GROUP})


def test_reconfiguration_removes_the_conflict() -> None:
    """After one Area drops the light, the snapshot is clean again (no automatic reassignment)."""
    before = {
        "e1/kitchen": {CONF_OVERHEAD_LIGHTS: [L1]},
        "e1/living": {CONF_OVERHEAD_LIGHTS: [L1]},
    }
    after = {
        "e1/kitchen": {CONF_OVERHEAD_LIGHTS: [L1]},
        "e1/living": {CONF_OVERHEAD_LIGHTS: []},
    }
    assert len(find_ownership_conflicts(before)) == 1
    assert find_ownership_conflicts(after) == []


def test_result_is_deterministic_and_does_not_change_input() -> None:
    """Same snapshot, same result; the input configuration is not modified."""
    areas = {
        "e1/b": {CONF_OVERHEAD_LIGHTS: [L2, L1]},
        "e1/a": {CONF_OVERHEAD_LIGHTS: [L1, L2]},
    }
    snapshot = {k: {f: list(v) for f, v in cfg.items()} for k, cfg in areas.items()}
    first = find_ownership_conflicts(areas)
    assert find_ownership_conflicts(areas) == first
    assert areas == snapshot
    assert [c.light for c in first] == [L1, L2]


def _states(mapping):
    """Attribute lookup: None for unknown state, attributes dict otherwise."""
    return lambda entity_id: mapping.get(entity_id)


def test_nested_groups_are_expanded_to_physical_lights() -> None:
    """A group in a group resolves to the physical lights at the bottom."""
    members = {"light.outer": ["light.inner"], "light.inner": [L1, L2]}
    assert expand_members(["light.outer"], members) == frozenset({L1, L2})


def test_cyclic_group_references_terminate() -> None:
    """A group that contains itself (directly or through another) is cut, not recursed."""
    members = {"light.a": ["light.b"], "light.b": ["light.a", L1]}
    assert expand_members(["light.a"], members) == frozenset({L1})
    assert expand_members(["light.b"], {"light.b": ["light.b"]}) == frozenset()


def test_depth_limit_stops_deep_chains_without_recursion_error() -> None:
    """A very deep chain is capped: no unbounded recursion."""
    members = {f"light.g{i}": [f"light.g{i + 1}"] for i in range(1000)}
    members["light.g1000"] = [L1]
    resolved = expand_members(["light.g0"], members)
    assert L1 not in resolved  # beyond the depth cap: a group id is kept, not expanded
    assert resolved


def test_tree_walk_separates_physical_unknown_and_unresolved() -> None:
    """Unavailable physical light is fine; unknown id and registry-only id are reported."""
    attrs = {
        L1: {"friendly_name": "one"},
        "light.group": {"entity_id": [L1, "light.ghost", "light.registered"]},
    }
    registry = {"light.registered"}
    members, unresolved, unknown = resolve_group_tree(
        ["light.group"], _states(attrs), lambda e: e in registry
    )
    assert members == {"light.group": [L1, "light.ghost", "light.registered"]}
    assert unknown == ["light.ghost"]
    assert unresolved == ["light.registered"]


def test_tree_walk_is_cycle_safe_and_bounded() -> None:
    """A cycle terminates; a huge tree is cut at MAX_GROUP_NODES and reported as unresolved."""
    attrs = {
        "light.x": {"entity_id": ["light.y"]},
        "light.y": {"entity_id": ["light.x"]},
    }
    members, unresolved, unknown = resolve_group_tree(
        ["light.x"], _states(attrs), lambda e: False
    )
    assert set(members) == {"light.x", "light.y"}
    assert unresolved == [] and unknown == []
    huge = {
        f"light.n{i}": {"entity_id": [f"light.n{i + 1}"]}
        for i in range(MAX_GROUP_NODES + 50)
    }
    _members, unresolved, _unknown = resolve_group_tree(
        ["light.n0"], _states(huge), lambda e: True
    )
    assert unresolved, "truncation must never look conflict-free"


def test_nested_group_conflict_is_detected_through_the_tree() -> None:
    """Area A's nested group reaches a light that Area B controls: conflict found."""
    areas = {
        "e1/a": {CONF_OVERHEAD_LIGHTS: ["light.outer"]},
        "e2/b": {CONF_SLEEP_LIGHTS: [L1]},
    }
    attrs = {
        "light.outer": {"entity_id": ["light.inner"]},
        "light.inner": {"entity_id": [L1]},
    }
    members, _u, _k = resolve_group_tree(
        ["light.outer"], _states(attrs), lambda e: True
    )
    conflicts = find_ownership_conflicts(areas, members)
    assert [c.light for c in conflicts] == [L1]
