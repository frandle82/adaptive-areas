"""Shared status and Cleaning Tracker summaries for Meta Areas."""

from typing import Any

from homeassistant.const import STATE_ON

from custom_components.adaptive_areas.base.adaptive import AdaptiveArea, AdaptiveMetaArea
from custom_components.adaptive_areas.const import (
    ATTR_STATES,
    DATA_AREA_OBJECT,
    MODULE_DATA,
    AreaStates,
    CleaningState,
)


def _child_area_objects(area: AdaptiveMetaArea) -> list[AdaptiveArea]:
    """Return the configured child Area objects in deterministic order."""
    child_slugs = set(area.get_child_areas())
    children = [
        runtime[DATA_AREA_OBJECT]
        for runtime in area.hass.data.get(MODULE_DATA, {}).values()
        if DATA_AREA_OBJECT in runtime
        and not runtime[DATA_AREA_OBJECT].is_meta()
        and runtime[DATA_AREA_OBJECT].slug in child_slugs
    ]
    return sorted(children, key=lambda child: child.id)


def meta_status_summary(area: AdaptiveMetaArea) -> dict[str, Any]:
    """Aggregate child occupancy and secondary state counts."""
    children = _child_area_objects(area)
    states_by_area: dict[str, set[str]] = {}
    for child in children:
        entity_id = (
            f"binary_sensor.adaptive_areas_presence_tracking_{child.slug}_area_state"
        )
        state = area.hass.states.get(entity_id)
        states_by_area[child.id] = (
            set(state.attributes.get(ATTR_STATES, [])) if state is not None else set()
        )
    occupied = {
        child.id
        for child in children
        if (state := area.hass.states.get(
            f"binary_sensor.adaptive_areas_presence_tracking_{child.slug}_area_state"
        ))
        and state.state == STATE_ON
    }
    mapping = {
        "dark_area_count": AreaStates.DARK,
        "sleeping_area_count": AreaStates.SLEEP,
        "extended_area_count": AreaStates.EXTENDED,
        "accented_area_count": AreaStates.ACCENT,
    }
    return {
        "child_area_count": len(children),
        "occupied_area_count": len(occupied),
        "clear_area_count": len(children) - len(occupied),
        **{
            attribute: sum(state in states for states in states_by_area.values())
            for attribute, state in mapping.items()
        },
        "occupied_areas": sorted(occupied),
        "dark_areas": sorted(
            area_id
            for area_id, states in states_by_area.items()
            if AreaStates.DARK in states
        ),
        "sleeping_areas": sorted(
            area_id
            for area_id, states in states_by_area.items()
            if AreaStates.SLEEP in states
        ),
        "extended_areas": sorted(
            area_id
            for area_id, states in states_by_area.items()
            if AreaStates.EXTENDED in states
        ),
    }


def meta_cleaning_summary(area: AdaptiveMetaArea) -> dict[str, Any]:
    """Aggregate existing child Cleaning Tracker results."""
    assessments = [
        (child.id, child.room_usage.assessment)
        for child in _child_area_objects(area)
        if child.room_usage is not None
    ]
    due = sorted(
        area_id for area_id, value in assessments if bool(value.get("due"))
    )
    soon_due = sorted(
        area_id
        for area_id, value in assessments
        if value.get("cleaning_state") == CleaningState.SOON_DUE
    )
    overdue = sorted(
        area_id
        for area_id, value in assessments
        if value.get("cleaning_state") == CleaningState.OVERDUE
    )
    ranked = sorted(
        assessments,
        key=lambda item: (
            -float(item[1].get("overdue_minutes", 0)),
            -float(item[1].get("score", 0)),
            item[0],
        ),
    )
    most_due = ranked[0] if ranked else None
    return {
        "cleaning_due_count": len(due),
        "cleaning_soon_due_count": len(soon_due),
        "cleaning_overdue_count": len(overdue),
        "cleaning_due_areas": due,
        "cleaning_soon_due_areas": soon_due,
        "cleaning_overdue_areas": overdue,
        "most_due_area": most_due[0] if most_due else None,
        "most_due_score": most_due[1].get("score") if most_due else None,
        "most_overdue_minutes": (
            most_due[1].get("overdue_minutes") if most_due else None
        ),
    }


def meta_area_summary(area: AdaptiveMetaArea) -> dict[str, Any]:
    """Return the complete reusable Meta Area summary."""
    return {**meta_status_summary(area), **meta_cleaning_summary(area)}
