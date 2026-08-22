#!/usr/bin/env python3
"""Helpers for comparing Home Assistant release versions."""

from __future__ import annotations

import re

_VERSION_PATTERN = re.compile(
    r"^(?P<year>\d+)\.(?P<month>\d+)\.(?P<patch>\d+)"
    r"(?:(?P<phase>a|b|rc)(?P<phase_number>\d+))?$"
)
_PHASE_ORDER = {"a": 0, "b": 1, "rc": 2, None: 3}


def version_key(version: str) -> tuple[int, int, int, int, int]:
    """Return a sortable key for a Home Assistant version."""
    match = _VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"Invalid Home Assistant version: {version}")

    phase = match.group("phase")
    return (
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("patch")),
        _PHASE_ORDER[phase],
        int(match.group("phase_number") or 0),
    )


def is_newer_beta(stable: str, beta: str) -> bool:
    """Return whether beta is newer than the current stable release."""
    return version_key(beta) > version_key(stable)
