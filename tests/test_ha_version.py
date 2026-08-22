"""Tests for Home Assistant version selection."""

import pytest

from scripts.ha_version import is_newer_beta, version_key


@pytest.mark.parametrize(
    ("stable", "beta", "expected"),
    [
        ("2026.8.1", "2026.8.0b6", False),
        ("2026.8.0", "2026.8.1b1", True),
        ("2026.8.1", "2026.9.0b0", True),
        ("2026.9.0", "2026.9.0b6", False),
    ],
)
def test_is_newer_beta(stable: str, beta: str, expected: bool) -> None:
    """Only an actual upcoming beta should enter the beta test gate."""
    assert is_newer_beta(stable, beta) is expected


def test_version_key_orders_prerelease_phases() -> None:
    """Prerelease phases should sort in release order."""
    assert version_key("2026.9.0a1") < version_key("2026.9.0b1")
    assert version_key("2026.9.0b1") < version_key("2026.9.0rc1")
    assert version_key("2026.9.0rc1") < version_key("2026.9.0")


def test_version_key_rejects_invalid_version() -> None:
    """Unexpected PyPI version formats should fail explicitly."""
    with pytest.raises(ValueError, match="Invalid Home Assistant version"):
        version_key("latest")
