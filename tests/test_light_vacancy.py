"""Pure vacancy-delay timing coverage."""

import pytest

from custom_components.adaptive_areas.helpers.light_vacancy import (
    LightVacancyState,
    evaluate_vacancy_delay,
)


def test_vacancy_without_delay_is_immediately_due() -> None:
    """Absent and zero delays preserve the current immediate-off semantics."""
    for delay in (None, 0):
        result = evaluate_vacancy_delay(
            occupied=False, now=10, delay=delay, previous_state=LightVacancyState()
        )
        assert result.off_due
        assert not result.state.pending


def test_vacancy_delay_has_stable_deadline_until_due() -> None:
    """Repeated vacancy observations never move the original deadline."""
    first = evaluate_vacancy_delay(
        occupied=False, now=10, delay=30, previous_state=LightVacancyState()
    )
    before = evaluate_vacancy_delay(
        occupied=False, now=39, delay=30, previous_state=first.state
    )
    exact = evaluate_vacancy_delay(
        occupied=False, now=40, delay=30, previous_state=first.state
    )
    after = evaluate_vacancy_delay(
        occupied=False, now=41, delay=30, previous_state=first.state
    )
    assert first.state == LightVacancyState(detected_at=10, due_at=40)
    assert not before.off_due and before.state == first.state
    assert exact.off_due and after.off_due


def test_occupied_and_unavailable_clear_pending_vacancy() -> None:
    """Presence recovery or uncertainty never permits an automatic off."""
    pending = LightVacancyState(detected_at=10, due_at=40)
    for occupied in (True, None):
        result = evaluate_vacancy_delay(
            occupied=occupied, now=20, delay=30, previous_state=pending
        )
        assert result.state == LightVacancyState()
        assert not result.off_due


def test_occupied_reset_creates_a_new_vacancy_deadline() -> None:
    """A later vacancy starts a new independent delay period."""
    first = evaluate_vacancy_delay(
        occupied=False, now=10, delay=30, previous_state=LightVacancyState()
    )
    cleared = evaluate_vacancy_delay(
        occupied=True, now=20, delay=30, previous_state=first.state
    )
    second = evaluate_vacancy_delay(
        occupied=False, now=25, delay=30, previous_state=cleared.state
    )
    assert second.state == LightVacancyState(detected_at=25, due_at=55)


def test_vacancy_delay_rejects_negative_values() -> None:
    """Invalid delays cannot silently become timing semantics."""
    with pytest.raises(ValueError):
        evaluate_vacancy_delay(
            occupied=False, now=0, delay=-1, previous_state=LightVacancyState()
        )
