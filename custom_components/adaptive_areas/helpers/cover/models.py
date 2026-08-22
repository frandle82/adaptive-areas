"""Pure data models for Adaptive Areas cover decisions."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class CoverAction(StrEnum):
    """Actions understood by the cover actuator."""

    OPEN = "open"
    CLOSE = "close"
    SHADE = "shading"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class CoverDecision:
    """A deterministic strategy result, independent from Home Assistant I/O."""

    action: CoverAction = CoverAction.NONE
    target_position: int | None = None
    reason: str | None = None
    blocked_by: str | None = None
    priority: int = 8
    covers: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverInputs:
    """Normalized measurements consumed by the strategy."""

    now: datetime
    trigger: str
    sleep: bool = False
    windows_open: bool = False
    windows_known: bool = True
    brightness: float | None = None
    shading_brightness: float | None = None
    sun_elevation: float | None = None
    area_climate_enabled: bool = False
    area_climate_heat: str = "unknown"
    fallback_temperature: float | None = None
    forecast_temperature: float | None = None
    open_condition: bool = True
    close_condition: bool = True
    shading_condition: bool = True
    manual_override_until: datetime | None = None
    pending_close: bool = False
    covers_available: bool = True


@dataclass(slots=True)
class CoverRuntimeState:
    """Mutable state intentionally kept outside the pure strategy."""

    pending_close: bool = False
    manual_override_until: datetime | None = None
    own_commands: dict[str, datetime] = field(default_factory=dict)
    last_decision: CoverDecision = field(default_factory=CoverDecision)
    fallback_heat_active: bool = False
    brightness_gate_active: bool = False
    unsupported_covers: tuple[str, ...] = ()
    unavailable_covers: tuple[str, ...] = ()
    forecast_temperature: float | None = None
