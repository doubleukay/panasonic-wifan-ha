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


@dataclass
class AuthToken:
    access_token: str
    refresh_token: str
    expiry: dt
