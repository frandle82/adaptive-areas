"""Tests for the bounded in-memory Decision Trace."""

from unittest.mock import Mock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.adaptive_areas.const import DATA_AREA_OBJECT, MODULE_DATA

from custom_components.adaptive_areas.helpers.decision_trace import (
    DEFAULT_TRACE_LENGTH,
    DecisionTrace,
    safe_record,
)


def test_trace_is_bounded_and_oldest_first() -> None:
    """The oldest entry is discarded when the ring buffer overflows."""
    trace = DecisionTrace()
    for index in range(DEFAULT_TRACE_LENGTH + 1):
        trace.record(
            feature="presence",
            trigger="test",
            decision=str(index),
            outcome="observed",
        )

    entries = trace.export()
    assert len(entries) == DEFAULT_TRACE_LENGTH
    assert entries[0]["decision"] == "1"
    assert entries[-1]["decision"] == str(DEFAULT_TRACE_LENGTH)


def test_traces_are_separate_and_clearable() -> None:
    """Each area-owned trace has independent runtime state."""
    first = DecisionTrace()
    second = DecisionTrace()
    first.record(
        feature="light_groups",
        trigger="test",
        decision="turn_on",
        outcome="executed",
        reason_codes=["action_executed"],
        target_count=3,
    )
    assert second.export() == []
    assert first.export()[0]["target_count"] == 3
    first.clear()
    assert first.export() == []


def test_safe_record_never_raises() -> None:
    """A trace failure cannot escape into automation logic."""
    broken_trace = Mock()
    broken_trace.record.side_effect = RuntimeError("trace failed")
    safe_record(
        broken_trace,
        feature="test",
        trigger="test",
        decision="no_action",
        outcome="skipped",
    )
    broken_trace.record.assert_called_once()


def test_trace_never_accepts_targets() -> None:
    """Trace entries contain counts, not identifying target values."""
    trace = DecisionTrace()
    trace.record(
        feature="media_player_control",
        trigger="test",
        decision="turn_off",
        outcome="failed",
        reason_codes=["action_failed"],
        target_count=1,
        exception_class="RuntimeError",
    )
    serialized = str(trace.export())
    assert "entity_id" not in serialized
    assert "target" not in serialized.replace("target_count", "")
    assert trace.export()[0]["exception_class"] == "RuntimeError"


async def test_unload_clears_area_trace(
    hass: HomeAssistant, basic_config_entry: MockConfigEntry, _setup_integration_basic
) -> None:
    """The existing config-entry unload lifecycle discards trace history."""
    area = hass.data[MODULE_DATA][basic_config_entry.entry_id][DATA_AREA_OBJECT]
    area.trace_decision(
        feature="test",
        trigger="test",
        decision="no_action",
        outcome="skipped",
    )
    assert area.decision_trace.export()
    assert await hass.config_entries.async_unload(basic_config_entry.entry_id)
    assert area.decision_trace.export() == []
