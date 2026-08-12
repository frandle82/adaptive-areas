"""Independent Room Usage evaluation based on Area presence transitions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from custom_components.adaptive_areas.const import (
    AdaptiveAreasEvents,
    CleaningRecommendation,
    RoomUsageState,
)


@dataclass(frozen=True)
class UsagePolicy:
    """Deterministic home-automation usage bands."""

    normal_seconds: int = 30 * 60
    high_seconds: int = 2 * 60 * 60
    normal_sessions: int = 2
    high_sessions: int = 4


USAGE_POLICY = UsagePolicy()

USAGE_CONTEXT = {
    "en": {
        "cleaning_postponed_occupied": "Cleaning is postponed while the room is occupied.",
        "cleaning_preferred_room_clear": "The highly used room is clear; cleaning is preferred now.",
        "cleaning_allowed_room_clear": "The room is clear; cleaning is allowed.",
    },
    "de": {
        "cleaning_postponed_occupied": "Die Reinigung wird verschoben, solange der Raum belegt ist.",
        "cleaning_preferred_room_clear": "Der stark genutzte Raum ist frei; die Reinigung wird jetzt bevorzugt.",
        "cleaning_allowed_room_clear": "Der Raum ist frei; die Reinigung ist möglich.",
    },
}


class RoomUsageEngine:
    """Track bounded daily Room Usage from existing presence transitions."""

    def __init__(self, area) -> None:
        """Initialize usage state and subscribe to Area state changes."""
        self.area = area
        now = datetime.now(UTC)
        self._usage_day: date = now.date()
        self._occupied = area.is_occupied()
        self._occupied_since: datetime | None = now if self._occupied else None
        self._last_occupied: datetime | None = now if self._occupied else None
        self._last_cleared: datetime | None = None
        self._occupied_seconds_today = 0.0
        self._occupancy_sessions_today = 1 if self._occupied else 0
        self._subscribers: list[Callable[[], None]] = []
        self._remove_listener = async_dispatcher_connect(
            area.hass,
            AdaptiveAreasEvents.AREA_STATE_CHANGED,
            self._area_state_changed,
        )
        self.assessment = self._evaluate()

    def _reset_day(self, now: datetime) -> None:
        if now.date() == self._usage_day:
            return
        self._usage_day = now.date()
        self._occupied_seconds_today = 0.0
        self._occupancy_sessions_today = 1 if self._occupied else 0
        if self._occupied:
            self._occupied_since = now

    def _evaluate(self) -> dict:
        now = datetime.now(UTC)
        self._reset_day(now)
        current = (
            (now - self._occupied_since).total_seconds()
            if self._occupied and self._occupied_since
            else 0.0
        )
        total = self._occupied_seconds_today + current
        if total == 0 and self._occupancy_sessions_today == 0:
            usage = RoomUsageState.UNUSED
        elif (
            total >= USAGE_POLICY.high_seconds
            or self._occupancy_sessions_today >= USAGE_POLICY.high_sessions
        ):
            usage = RoomUsageState.HIGH
        elif (
            total >= USAGE_POLICY.normal_seconds
            or self._occupancy_sessions_today >= USAGE_POLICY.normal_sessions
        ):
            usage = RoomUsageState.NORMAL
        else:
            usage = RoomUsageState.LOW
        cleaning = (
            CleaningRecommendation.POSTPONE
            if self._occupied
            else (
                CleaningRecommendation.PREFERRED
                if usage == RoomUsageState.HIGH
                else CleaningRecommendation.ALLOWED
            )
        )
        reason = {
            CleaningRecommendation.POSTPONE: "cleaning_postponed_occupied",
            CleaningRecommendation.PREFERRED: "cleaning_preferred_room_clear",
            CleaningRecommendation.ALLOWED: "cleaning_allowed_room_clear",
        }[cleaning]
        language = (
            "de" if str(self.area.hass.config.language).startswith("de") else "en"
        )
        return {
            "room_usage": usage,
            "cleaning_recommendation": cleaning,
            "current_occupancy_duration": int(current),
            "occupied_duration_today": int(total),
            "occupancy_sessions_today": self._occupancy_sessions_today,
            "time_since_last_occupancy": (
                int((now - self._last_cleared).total_seconds())
                if self._last_cleared
                else None
            ),
            "last_occupied": (
                self._last_occupied.isoformat() if self._last_occupied else None
            ),
            "last_cleared": (
                self._last_cleared.isoformat() if self._last_cleared else None
            ),
            "context": USAGE_CONTEXT[language][reason],
            "reason_codes": [reason],
        }

    @callback
    def _area_state_changed(self, area_id: str, _states_tuple) -> None:
        if area_id != self.area.id:
            return
        now = datetime.now(UTC)
        self._reset_day(now)
        occupied = self.area.is_occupied()
        transitioned = occupied != self._occupied
        if transitioned:
            self._occupied = occupied
            if occupied:
                self._occupied_since = now
                self._last_occupied = now
                self._occupancy_sessions_today += 1
            else:
                if self._occupied_since:
                    self._occupied_seconds_today += (
                        now - self._occupied_since
                    ).total_seconds()
                self._occupied_since = None
                self._last_cleared = now
        self.assessment = self._evaluate()
        if transitioned:
            self.area.trace_decision(
                feature="room_usage",
                trigger="area_state_changed",
                decision=self.assessment["reason_codes"][0],
                outcome="evaluated",
                reason_codes=self.assessment["reason_codes"],
            )
        for subscriber in list(self._subscribers):
            subscriber()

    def register_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register assessment listener."""
        self._subscribers.append(listener)

        def remove() -> None:
            if listener in self._subscribers:
                self._subscribers.remove(listener)

        return remove

    def unload(self) -> None:
        """Release listener and subscribers."""
        self._remove_listener()
        self._subscribers.clear()
