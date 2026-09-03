from dataclasses import dataclass
from datetime import datetime as dt
from typing import NewType

UniqueID = NewType("UniqueID", str)

"""
Example API response:
{
    'appliance_id': 'xxx',
    'com_id': 'FM12EC',
    'hashed_guid': 'xxx',
    'name': 'Study',
    'product_code': 'F-M12EC',
    'serial_number': 'XXX'
}
"""


@dataclass(frozen=True)
class Fan:
    """Fan appliance data class"""

    appliance_id: str
    com_id: str
    hashed_guid: str
    name: str
    product_code: str
    serial_number: str

    @staticmethod
    def from_api(data: dict) -> "Fan":
        """Create Fan instance from API response dictionary"""
        return Fan(
            appliance_id=data.get("appliance_id", ""),
            com_id=data.get("com_id", ""),
            hashed_guid=data.get("hashed_guid", ""),
            name=data.get("name", ""),
            product_code=data.get("product_code", ""),
            serial_number=data.get("serial_number", ""),
        )

    @property
    def object_id(self) -> str:
        """Generate Home Assistant object ID from fan name"""
        return self.name.lower().replace(" ", "_")

    @property
    def unique_id(self) -> UniqueID:
        """Generate unique ID from appliance ID"""
        return UniqueID(self.appliance_id)

    def __str__(self) -> str:
        """String representation of the fan"""
        return f"{self.name} ({self.product_code}): {self.serial_number}"

    def __hash__(self) -> int:
        return hash(self.unique_id)


@dataclass(frozen=True)
class FanState:
    is_on: bool
    speed: int
    reverse: bool
    yuragi: bool


@dataclass(frozen=True)
class LightState:
    """State of the light fitted to a fan, when it has one.

    The light has two modes. In normal mode ``brightness`` and ``color_temp``
    apply; in sleep mode, which dims further than the normal range allows,
    ``sleep_brightness`` does. All three are percentages, with ``color_temp``
    running from warm at 0 to daylight at 100. The device keeps every value
    whichever mode is active, so switching modes does not lose the other one's
    setting.
    """

    is_on: bool
    brightness: int
    color_temp: int = 0
    sleep: bool = False
    sleep_brightness: int = 1

    @property
    def active_brightness(self) -> int:
        """The brightness that the current mode actually uses."""
        return self.sleep_brightness if self.sleep else self.brightness


@dataclass(frozen=True)
class DeviceState:
    """Everything a single state poll told us about one appliance."""

    fan: FanState
    light: LightState | None = None


@dataclass
class AuthToken:
    access_token: str
    refresh_token: str
    expiry: dt
