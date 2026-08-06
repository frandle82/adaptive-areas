"""Climate control feature switch."""

import logging
from time import monotonic

from homeassistant.components.climate.const import (
    ATTR_PRESET_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_PRESET_MODE,
)
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import CALLBACK_TYPE
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_call_later

from custom_components.magic_areas.base.magic import MagicArea
from custom_components.magic_areas.const import (
    CONF_CLIMATE_CONTROL_ENTITY_ID,
    CONF_CLIMATE_CONTROL_OCCUPANCY_THRESHOLD,
    CONF_CLIMATE_CONTROL_PRESET_CLEAR,
    CONF_CLIMATE_CONTROL_PRESET_EXTENDED,
    CONF_CLIMATE_CONTROL_PRESET_OCCUPIED,
    CONF_CLIMATE_CONTROL_PRESET_SLEEP,
    DEFAULT_CLIMATE_CONTROL_PRESET_CLEAR,
    DEFAULT_CLIMATE_CONTROL_PRESET_EXTENDED,
    DEFAULT_CLIMATE_CONTROL_OCCUPANCY_THRESHOLD,
    DEFAULT_CLIMATE_CONTROL_PRESET_OCCUPIED,
    DEFAULT_CLIMATE_CONTROL_PRESET_SLEEP,
    AreaStates,
    MagicAreasEvents,
    MagicAreasFeatureInfoClimateControl,
    MagicAreasFeatures,
)
from custom_components.magic_areas.switch.base import SwitchBase

_LOGGER = logging.getLogger(__name__)


class ClimateControlSwitch(SwitchBase):
    """Switch to enable/disable climate control."""

    feature_info = MagicAreasFeatureInfoClimateControl()
    _attr_entity_category = EntityCategory.CONFIG

    preset_map: dict[str, str]
    climate_entity_id: str | None

    def __init__(self, area: MagicArea) -> None:
        """Initialize the Climate control switch."""

        SwitchBase.__init__(self, area)
        feature_config = self.area.feature_config(MagicAreasFeatures.CLIMATE_CONTROL)

        self.climate_entity_id = feature_config.get(
            CONF_CLIMATE_CONTROL_ENTITY_ID, None
        )

        if not self.climate_entity_id:
            raise ValueError("Climate entity not set")

        self.preset_map = {
            AreaStates.CLEAR: feature_config.get(
                CONF_CLIMATE_CONTROL_PRESET_CLEAR, DEFAULT_CLIMATE_CONTROL_PRESET_CLEAR
            ),
            AreaStates.OCCUPIED: feature_config.get(
                CONF_CLIMATE_CONTROL_PRESET_OCCUPIED,
                DEFAULT_CLIMATE_CONTROL_PRESET_OCCUPIED,
            ),
            AreaStates.SLEEP: feature_config.get(
                CONF_CLIMATE_CONTROL_PRESET_SLEEP, DEFAULT_CLIMATE_CONTROL_PRESET_SLEEP
            ),
            AreaStates.EXTENDED: feature_config.get(
                CONF_CLIMATE_CONTROL_PRESET_EXTENDED,
                DEFAULT_CLIMATE_CONTROL_PRESET_EXTENDED,
            ),
        }
        self.occupancy_threshold_minutes = feature_config.get(
            CONF_CLIMATE_CONTROL_OCCUPANCY_THRESHOLD,
            DEFAULT_CLIMATE_CONTROL_OCCUPANCY_THRESHOLD,
        )
        self._occupied_since: float | None = None
        self._occupancy_threshold_callback: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to hass."""
        await super().async_added_to_hass()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, MagicAreasEvents.AREA_STATE_CHANGED, self.area_state_changed
            )
        )
        self.async_on_remove(self._clear_occupancy_threshold_timer)

    async def area_state_changed(self, area_id, states_tuple):
        """Handle area state change event."""

        if not self.is_on:
            self.logger.debug("%s: Control disabled. Skipping.", self.name)
            return

        if area_id != self.area.id:
            _LOGGER.debug(
                "%s: Area state change event not for us. Skipping. (event: %s/self: %s)",
                self.name,
                area_id,
                self.area.id,
            )
            return

        if self.area.has_state(AreaStates.OCCUPIED):
            if self._occupied_since is None:
                self._occupied_since = monotonic()
                self._set_occupancy_threshold_timer()
        else:
            self._reset_occupancy_tracking()

        priority_states: list[str] = [
            AreaStates.SLEEP,
            AreaStates.EXTENDED,
            AreaStates.OCCUPIED,
        ]

        # Handle area clear because the other states doesn't matter
        if self.area.has_state(AreaStates.CLEAR):
            self._reset_occupancy_tracking()
            if self.preset_map[AreaStates.CLEAR]:
                await self.apply_preset(AreaStates.CLEAR)
            return

        # Handle each state top priority to last, returning early
        for p_state in priority_states:
            if p_state == AreaStates.OCCUPIED and not self._occupancy_threshold_met():
                self.logger.debug(
                    "%s: Occupancy threshold not met. Skipping occupied preset.",
                    self.name,
                )
                continue

            if self.area.has_state(p_state) and self.preset_map[p_state]:
                return await self.apply_preset(p_state)

    def _occupancy_threshold_met(self) -> bool:
        """Return True if the room has been occupied long enough to heat."""
        if self.occupancy_threshold_minutes <= 0:
            return True
        if self._occupied_since is None:
            return False

        occupied_duration = (monotonic() - self._occupied_since) / 60
        return occupied_duration >= self.occupancy_threshold_minutes

    def _set_occupancy_threshold_timer(self) -> None:
        """Schedule a local re-check when the occupancy threshold expires."""
        self._clear_occupancy_threshold_timer()

        if self.occupancy_threshold_minutes <= 0:
            return

        self._occupancy_threshold_callback = async_call_later(
            self.hass,
            self.occupancy_threshold_minutes * 60,
            self._occupancy_threshold_elapsed,
        )

    def _clear_occupancy_threshold_timer(self) -> None:
        """Clear the local occupancy threshold timer."""
        if self._occupancy_threshold_callback is None:
            return

        self._occupancy_threshold_callback()
        self._occupancy_threshold_callback = None

    def _reset_occupancy_tracking(self) -> None:
        """Reset occupancy timing state."""
        self._occupied_since = None
        self._clear_occupancy_threshold_timer()

    def _occupancy_threshold_elapsed(self, _now) -> None:
        """Re-evaluate climate presets after a short occupancy delay."""
        self._occupancy_threshold_callback = None
        self.hass.async_create_task(
            self.area_state_changed(self.area.id, (self.area.states, []))
        )

    async def apply_preset(self, state_name: str):
        """Set climate entity to given preset."""

        selected_preset: str = self.preset_map[state_name]

        try:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_PRESET_MODE,
                {
                    ATTR_ENTITY_ID: self.climate_entity_id,
                    ATTR_PRESET_MODE: selected_preset,
                },
            )
        # pylint: disable-next=broad-exception-caught
        except Exception as e:
            self.logger.error("%s: Error applying preset: %s", self.name, str(e))
