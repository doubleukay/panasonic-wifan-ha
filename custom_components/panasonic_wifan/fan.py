"""Fan platform for Panasonic WIFAN integration."""

from __future__ import annotations

from datetime import timedelta
import logging
import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.components.fan import DIRECTION_FORWARD, DIRECTION_REVERSE
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .const import DOMAIN, MAX_SPEED, MIN_SPEED
from .types import Fan, FanState

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Panasonic WIFAN platform from configuration.yaml."""
    # Not supported for configuration.yaml
    pass


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Panasonic WIFAN entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    fans = data["fans"]

    entities = [PanasonicWiFiFan(api, fan) for fan in fans]

    async_add_entities(entities)


class PanasonicWiFiFan(FanEntity):  # type: ignore[misc]
    """Representation of a Panasonic WIFAN."""

    _attr_icon = "mdi:fan"
    _attr_speed_count = MAX_SPEED
    _attr_should_poll = True

    def __init__(self, api, fan: Fan) -> None:
        """Initialize the fan entity."""
        self._api = api
        self._fan = fan
        self._attr_unique_id = fan.unique_id
        self._attr_name = fan.name

        # Optimistic state
        self._attr_is_on = False
        self._attr_percentage = 0
        self._attr_percentage_when_turn_on = 0
        self._attr_current_direction = DIRECTION_FORWARD
        self._attr_supported_features = (
            FanEntityFeature.SET_SPEED
            | FanEntityFeature.TURN_ON
            | FanEntityFeature.TURN_OFF
            | FanEntityFeature.DIRECTION
            | FanEntityFeature.OSCILLATE
        )

        # Oscillation state (yuragi)
        self._attr_oscillating = False

        # Store the complete fan state including yuragi
        self._current_state = FanState(
            is_on=False,
            speed=MIN_SPEED,
            reverse=False,
            yuragi=False,
        )

        # Device info
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._fan.unique_id)},
            "name": self._fan.name,
            "manufacturer": "Panasonic",
            "model": self._fan.product_code,
            "serial_number": self._fan.serial_number,
        }

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()

        # Fetch initial state
        await self.async_update()

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""

        if percentage is None:
            # Use percentage when turn on if not specified
            percentage = self._attr_percentage_when_turn_on

        await self._update_fan_state(is_on=True, percentage=percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        # Call API to turn off
        await self._update_fan_state(is_on=False)

        # Update optimistic state, HA requires percentage to be 0 when off
        self._attr_percentage = 0
        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        if percentage == 0:
            await self.async_turn_off()
            return

        self._attr_percentage_when_turn_on = percentage
        await self._update_fan_state(is_on=True, percentage=percentage)

    async def async_set_direction(self, direction: str) -> None:
        """Set the direction of the fan."""
        if direction not in (DIRECTION_FORWARD, DIRECTION_REVERSE):
            raise ValueError(f"Invalid direction: {direction}")

        # If fan is on, update the direction immediately
        await self._update_fan_state(direction=direction)

    async def async_oscillate(self, oscillating: bool) -> None:
        """Set oscillation (yuragi mode) of the fan."""
        await self._update_fan_state(oscillating=oscillating)

    async def _update_fan_state(
        self,
        is_on: bool | None = None,
        percentage: int | None = None,
        direction: str | None = None,
        oscillating: bool | None = None,
    ) -> None:
        """Update fan state via API and sync optimistic state."""
        # Use current values if not provided, with proper defaults
        final_is_on = is_on if is_on is not None else (self._attr_is_on or False)
        final_percentage = (
            percentage if percentage is not None else (self._attr_percentage or 0)
        )
        final_direction = (
            direction
            if direction is not None
            else (self._attr_current_direction or DIRECTION_FORWARD)
        )
        final_oscillating = (
            oscillating
            if oscillating is not None
            else (self._attr_oscillating or False)
        )

        # Convert percentage to speed
        speed = self._percentage_to_speed(final_percentage)

        # Create new state based on current state, updating only changed fields
        new_state = FanState(
            is_on=final_is_on,
            speed=speed,
            reverse=(final_direction == DIRECTION_REVERSE),
            yuragi=final_oscillating,
        )

        # Call API
        _LOGGER.debug(
            "Pushing state to cloud for %s: is_on=%s, speed=%s, reverse=%s, yuragi=%s",
            self._attr_name,
            new_state.is_on,
            new_state.speed,
            new_state.reverse,
            new_state.yuragi,
        )
        await self._api.set_state(self._fan, new_state)

        # Update instance state
        self._current_state = new_state

        # Update optimistic state
        self._attr_is_on = final_is_on
        self._attr_percentage = final_percentage
        self._attr_current_direction = final_direction
        self._attr_oscillating = final_oscillating
        self.async_write_ha_state()

    def _percentage_to_speed(self, percentage: int) -> int:
        """Convert percentage to speed (1-10)."""
        speed = math.ceil(
            percentage_to_ranged_value((MIN_SPEED, MAX_SPEED), percentage)
        )
        return max(MIN_SPEED, min(MAX_SPEED, speed))

    async def async_update(self) -> None:
        """Fetch new state data for this fan.

        This is called by Home Assistant when polling is enabled or when
        a manual refresh is requested.
        """
        try:
            state = await self._api.get_state_for_fan(self._fan)
            self._update_state_from_fan_state(state)
        except Exception as err:
            _LOGGER.error("Error updating %s: %s", self._attr_name, err)

    def _update_state_from_fan_state(self, state: FanState) -> None:
        """Update entity attributes from a FanState object."""
        # Update instance state
        self._current_state = state

        self._attr_is_on = state.is_on

        percentage = int(
            ranged_value_to_percentage((MIN_SPEED, MAX_SPEED), state.speed)
        )
        self._attr_percentage_when_turn_on = percentage

        if state.is_on and state.speed > 0:
            # Convert speed (1-10) to percentage
            self._attr_percentage = percentage
        else:
            self._attr_percentage = 0

        # Update direction
        self._attr_current_direction = (
            DIRECTION_REVERSE if state.reverse else DIRECTION_FORWARD
        )

        # Update oscillation state
        self._attr_oscillating = state.yuragi

        _LOGGER.debug(
            "Updated %s: is_on=%s, speed=%s, percentage=%s, reverse=%s, yuragi=%s",
            self._attr_name,
            state.is_on,
            state.speed,
            self._attr_percentage,
            state.reverse,
            state.yuragi,
        )
