"""Manual override states of a light target.

Only the Override enum is used by the production light path. The former dispatcher
decision model (requests, vetoes and conflicts) was observation-only and has been removed
with the removed shadow simulation; the production decision path is helpers/light_transition.py.
"""

from __future__ import annotations

from enum import StrEnum


class Override(StrEnum):
    """Confirmed manual override state for one target."""

    NONE = "none"
    FORCE_ON = "force_on"
    FORCE_OFF = "force_off"
