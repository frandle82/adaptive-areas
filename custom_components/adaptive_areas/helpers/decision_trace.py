"""Privacy-safe, in-memory decision tracing for Adaptive Areas."""

from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

DEFAULT_TRACE_LENGTH = 20


class DecisionTrace:
    """Maintain a bounded history of automatic decisions for one area."""

    def __init__(self, maxlen: int = DEFAULT_TRACE_LENGTH) -> None:
        """Initialize an empty trace."""
        self._entries: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def record(
        self,
        *,
        feature: str,
        trigger: str,
        decision: str,
        outcome: str,
        area_state: Iterable[str] = (),
        reason_codes: Iterable[str] = (),
        target_count: int = 0,
        from_state: str | None = None,
        to_state: str | None = None,
        exception_class: str | None = None,
    ) -> None:
        """Append a structured entry without accepting identifying target data."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "feature": str(feature),
            "trigger": str(trigger),
            "area_state": sorted({str(state) for state in area_state}),
            "decision": str(decision),
            "outcome": str(outcome),
            "reason_codes": list(dict.fromkeys(str(code) for code in reason_codes)),
            "target_count": max(0, int(target_count)),
        }
        if from_state is not None:
            entry["from"] = str(from_state)
        if to_state is not None:
            entry["to"] = str(to_state)
        if exception_class is not None:
            entry["exception_class"] = str(exception_class)
        self._entries.append(entry)

    def export(self) -> list[dict[str, Any]]:
        """Return an oldest-first copy suitable for diagnostics."""
        return [dict(entry) for entry in self._entries]

    def clear(self) -> None:
        """Discard all runtime history."""
        self._entries.clear()


def safe_record(trace: DecisionTrace, **kwargs: Any) -> None:
    """Record a decision without allowing tracing to affect runtime behavior."""
    try:
        trace.record(**kwargs)
    # Observability must never interfere with automation.
    # pylint: disable-next=broad-exception-caught
    except Exception:
        return
