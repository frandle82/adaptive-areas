"""Pure vacancy-delay state transitions for a future Light runtime."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LightVacancyState:
    """A pending vacancy deadline represented in caller-provided seconds."""

    detected_at: float | None = None
    due_at: float | None = None

    @property
    def pending(self) -> bool:
        """Return whether a vacancy-off remains scheduled conceptually."""
        return self.due_at is not None


@dataclass(frozen=True, slots=True)
class LightVacancyResult:
    """The next pure vacancy state and whether off is currently permitted."""

    state: LightVacancyState
    off_due: bool


def evaluate_vacancy_delay(
    *,
    occupied: bool | None,
    now: float,
    delay: float | None,
    previous_state: LightVacancyState,
) -> LightVacancyResult:
    """Evaluate vacancy timing without scheduling, side effects, or system time."""
    if occupied is None or occupied:
        return LightVacancyResult(LightVacancyState(), False)
    if delay is None or delay == 0:
        return LightVacancyResult(LightVacancyState(), True)
    if delay < 0:
        raise ValueError("Vacancy delay must be non-negative")
    if previous_state.pending:
        return LightVacancyResult(previous_state, now >= previous_state.due_at)
    return LightVacancyResult(
        LightVacancyState(detected_at=now, due_at=now + delay), False
    )
