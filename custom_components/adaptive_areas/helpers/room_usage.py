"""Persistent Cleaning Tracker driven by Adaptive Area presence events."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Self

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from custom_components.adaptive_areas.const import (
    CONF_FEATURE_ROOM_USAGE,
    CONF_PRESENCE_MINUTES_TO_DUE,
    CONF_PRESENCE_SECONDS_TO_DUE,
    DEFAULT_PRESENCE_MINUTES_TO_DUE,
    DOMAIN,
    AdaptiveAreasEvents,
    CleaningState,
)

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}.cleaning_tracker"


class RoomUsageEngine:
    """Track cumulative presence since an Area was last cleaned."""

    def __init__(self, area) -> None:
        """Initialize an unloaded tracker."""
        self.area = area
        self._store: Store[dict[str, Any]] = Store(
            area.hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY_PREFIX}.{area.id}",
        )
        feature_config = area.feature_config(CONF_FEATURE_ROOM_USAGE)
        if CONF_PRESENCE_MINUTES_TO_DUE in feature_config:
            presence_minutes_to_due = float(
                feature_config[CONF_PRESENCE_MINUTES_TO_DUE]
            )
            self._presence_seconds_to_due = max(1, presence_minutes_to_due * 60)
        else:
            self._presence_seconds_to_due = max(
                1,
                float(
                    feature_config.get(
                        CONF_PRESENCE_SECONDS_TO_DUE,
                        DEFAULT_PRESENCE_MINUTES_TO_DUE * 60,
                    )
                ),
            )
        self._cumulative_presence_seconds = 0.0
        self._last_cleaned: datetime | None = None
        # Presence can be unavailable during startup.  None is intentionally
        # different from unoccupied: no time may be added or discarded until
        # the first authoritative area-state transition arrives.
        self._occupied: bool | None = None
        self._occupied_since: datetime | None = None
        self._subscribers: list[Callable[[], None]] = []
        self._remove_listener: Callable[[], None] | None = None
        self._remove_deadline: Callable[[], None] | None = None
        self._last_persisted_snapshot: dict[str, float | str | None] | None = None
        now = dt_util.utcnow()
        self.assessment = self._evaluate(now)

    @classmethod
    async def async_create(cls, area) -> Self:
        """Load persisted state and start tracking an Area."""
        engine = cls(area)
        await engine._async_load()
        engine._remove_listener = async_dispatcher_connect(
            area.hass,
            AdaptiveAreasEvents.AREA_STATE_CHANGED,
            engine._area_state_changed,
        )
        engine.assessment = engine._evaluate(dt_util.utcnow())
        return engine

    async def _async_load(self) -> None:
        """Load and validate persisted tracker state."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        try:
            cumulative = float(stored.get("cumulative_presence_seconds", 0))
        except TypeError, ValueError:
            cumulative = 0
        self._cumulative_presence_seconds = max(0.0, cumulative)
        last_cleaned = stored.get("last_cleaned")
        if isinstance(last_cleaned, str):
            parsed = dt_util.parse_datetime(last_cleaned)
            if parsed is not None:
                self._last_cleaned = dt_util.as_utc(parsed)
        self._last_persisted_snapshot = self._serialize()

    def _serialize(self) -> dict[str, float | str | None]:
        """Return the persistent representation of current state."""
        return {
            "cumulative_presence_seconds": self._cumulative_presence_seconds,
            "last_cleaned": (
                self._last_cleaned.isoformat() if self._last_cleaned else None
            ),
        }

    async def _async_save(self) -> None:
        """Persist the current tracker state."""
        snapshot = self._serialize()
        await self._store.async_save(snapshot)
        self._last_persisted_snapshot = snapshot

    def _schedule_save(self) -> None:
        """Queue persistence only when the serialized state changed."""
        snapshot = self._serialize()
        if snapshot == self._last_persisted_snapshot:
            return
        self._last_persisted_snapshot = snapshot
        self._store.async_delay_save(lambda: snapshot, 1)

    def _effective_presence_seconds(self, now: datetime) -> float:
        """Return persisted usage plus the current, uncommitted session."""
        if self._occupied and self._occupied_since is not None:
            return self._cumulative_presence_seconds + max(
                0, (now - self._occupied_since).total_seconds()
            )
        return self._cumulative_presence_seconds

    def _commit_active_session(self, now: datetime) -> None:
        """Commit the active session once and stop tracking it."""
        if self._occupied and self._occupied_since is not None:
            self._cumulative_presence_seconds = self._effective_presence_seconds(now)
            self._occupied_since = None

    def _evaluate(self, now: datetime) -> dict[str, Any]:
        """Build the public tracker assessment without mutating counters."""
        effective_presence = self._effective_presence_seconds(now)
        score = min(
            100.0,
            effective_presence / self._presence_seconds_to_due * 100,
        )
        current_duration = (
            max(0, int((now - self._occupied_since).total_seconds()))
            if self._occupied and self._occupied_since
            else 0
        )
        presence_minutes = effective_presence / 60
        minutes_to_due = self._presence_seconds_to_due / 60
        remaining_minutes = max(0.0, minutes_to_due - presence_minutes)
        overdue_minutes = max(0.0, presence_minutes - minutes_to_due)
        if score <= 25:
            cleaning_state = CleaningState.CLEAN
        elif score <= 75:
            cleaning_state = CleaningState.USED
        elif score < 100:
            cleaning_state = CleaningState.SOON_DUE
        elif overdue_minutes > minutes_to_due * 0.25:
            cleaning_state = CleaningState.OVERDUE
        else:
            cleaning_state = CleaningState.DUE
        return {
            "score": round(score, 2),
            "cleaning_state": cleaning_state,
            "due": (effective_presence >= self._presence_seconds_to_due),
            "cumulative_presence_seconds": round(self._cumulative_presence_seconds, 3),
            "presence_minutes_since_cleaning": round(presence_minutes, 3),
            "presence_minutes_to_due": round(minutes_to_due, 3),
            "remaining_minutes_to_due": round(remaining_minutes, 3),
            "overdue_minutes": round(overdue_minutes, 3),
            "current_occupancy_duration_seconds": current_duration,
            "last_cleaned": (
                self._last_cleaned.isoformat() if self._last_cleaned else None
            ),
        }

    @callback
    def _publish(self, now: datetime) -> None:
        """Refresh the assessment and notify entities."""
        previous_public = tuple(sorted(self.assessment.items()))
        self.assessment = self._evaluate(now)
        if previous_public == tuple(sorted(self.assessment.items())):
            return
        for subscriber in list(self._subscribers):
            subscriber()
        async_dispatcher_send(
            self.area.hass, AdaptiveAreasEvents.CLEANING_UPDATED, self.area.id
        )

    @callback
    def _area_state_changed(self, area_id: str, _states_tuple) -> None:
        """Account for transitions reported by the existing Presence engine."""
        if area_id != self.area.id:
            return
        now = dt_util.utcnow()
        occupied = self.area.is_occupied()
        transitioned = occupied != self._occupied
        if not transitioned:
            return
        if self._occupied:
            self._commit_active_session(now)
        self._occupied = occupied
        self._occupied_since = now if occupied else None
        if occupied:
            self._schedule_deadline()
        elif self._remove_deadline is not None:
            self._remove_deadline()
            self._remove_deadline = None
        self.area.trace_decision(
            feature="room_usage",
            trigger="area_state_changed",
            decision="presence_started" if occupied else "presence_stopped",
            outcome="tracked",
            reason_codes=[
                "cleaning_presence_started" if occupied else "cleaning_presence_stopped"
            ],
        )
        self._publish(now)
        self._schedule_save()

    async def async_sync_presence_state(self, occupied: bool | None) -> None:
        """Synchronize a known runtime Presence state without guessing."""
        if occupied is None:
            if self._occupied:
                self._commit_active_session(dt_util.utcnow())
            self._occupied = None
            self._cancel_deadline()
            self._publish(dt_util.utcnow())
            return
        self._set_presence_state(occupied)

    def _set_presence_state(self, occupied: bool) -> None:
        """Apply an authoritative Presence transition."""
        now = dt_util.utcnow()
        if occupied == self._occupied:
            return
        if self._occupied:
            self._commit_active_session(now)
        self._occupied = occupied
        self._occupied_since = now if occupied else None
        if occupied:
            self._schedule_deadline()
        else:
            self._cancel_deadline()
        self._publish(now)
        self._schedule_save()

    def _schedule_deadline(self) -> None:
        """Schedule exactly one callback for the next cleaning deadline."""
        self._cancel_deadline()
        now = dt_util.utcnow()
        remaining = self._presence_seconds_to_due - self._effective_presence_seconds(
            now
        )
        if remaining <= 0:
            self._publish(now)
            return

        async def _deadline(_now: datetime) -> None:
            self._remove_deadline = None
            if self._occupied:
                self._publish(dt_util.utcnow())

        self._remove_deadline = async_call_later(self.area.hass, remaining, _deadline)

    async def async_mark_cleaned(self) -> None:
        """Clear accumulated presence and record the cleaning timestamp."""
        now = dt_util.utcnow()
        self._cumulative_presence_seconds = 0.0
        self._last_cleaned = now
        self._occupied_since = now if self._occupied else None
        if self._occupied:
            self._schedule_deadline()
        self._publish(now)
        await self._async_save()

    async def async_reset(self) -> None:
        """Reset runtime and stored state completely."""
        now = dt_util.utcnow()
        self._cumulative_presence_seconds = 0.0
        self._last_cleaned = None
        self._occupied_since = now if self._occupied else None
        if self._occupied:
            self._schedule_deadline()
        else:
            self._cancel_deadline()
        self._publish(now)
        await self._store.async_remove()

    async def async_set_score(self, score: float) -> None:
        """Set score and derive the underlying cumulative presence value."""
        now = dt_util.utcnow()
        self._cumulative_presence_seconds = self._presence_seconds_to_due * score / 100
        self._occupied_since = now if self._occupied else None
        if self._occupied:
            self._schedule_deadline()
        self._publish(now)
        await self._async_save()

    def register_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an assessment listener."""
        self._subscribers.append(listener)

        def remove() -> None:
            if listener in self._subscribers:
                self._subscribers.remove(listener)

        return remove

    def _stop(self) -> None:
        """Cancel all listeners and scheduled work idempotently."""
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        self._cancel_deadline()

    def _cancel_deadline(self) -> None:
        """Cancel the active deadline timer, if any."""
        if self._remove_deadline is not None:
            self._remove_deadline()
            self._remove_deadline = None

    async def async_unload(self) -> None:
        """Persist the final occupied interval and release resources."""
        self._stop()
        now = dt_util.utcnow()
        self._commit_active_session(now)
        await self._async_save()
        self._subscribers.clear()

    def unload(self) -> None:
        """Release resources for synchronous callers."""
        self._stop()
        self._subscribers.clear()
