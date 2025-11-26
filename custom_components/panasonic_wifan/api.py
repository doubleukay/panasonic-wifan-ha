"""
API Client for interacting with the Panasonic WiFan cloud service.
"""

import aiohttp
import asyncio
from datetime import datetime as dt, timezone
import logging
from typing import Literal

from .auth import PanasonicGLBAuthClient
from .const import MIN_SPEED, MAX_SPEED
from .types import Fan, FanState

BASE_URL = "https://prod.mycfan.pgtls.net/v1/mycfan/user"
API_KEY = "rZLwuRtU0nFb20Mh6LShL6uY3fZ5tBlarz4ONmdl"
OAUTH_CLIENT_ID = "8k1QeEXDxt3qGgYOvDY7NmZLfl60YfNi"
QUERY_PACKET = "0A00800000F00000F10000F20000F80000F90000FA0000FB00008600008800"
OFF_PACKET = "060093014200FD010400FC013000FE01400080013100FA043140FFFF"
ON_PACKET = (
    "090093014200FD010400FC013000FE01400080013000F0013200F1014100F2013100F8043131FFFF"
)
SLEEP_AFTER_QUERY = 2  # seconds
GET = "GET"
SET = "SET"

_LOGGER = logging.getLogger(__name__)


class ApiClient:
    def __init__(self, username: str, password: str):
        self.auth = PanasonicGLBAuthClient(username, password)
        self.session = aiohttp.ClientSession()

    async def _request(self, method: str, url: str, **kwargs):
        """Helper method to make API requests with common headers and error handling."""
        headers = {
            "content-type": "application/json",
            "x-api-key": API_KEY,
            "authorization": await self.auth.get_access_token(),
            "x-timestamp": get_timestamp(),
        }

        resp = await self.session.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
        return await resp.json()

    async def get_devices(self) -> list[Fan]:
        data = await self._request("GET", f"{BASE_URL}/devices")
        return [Fan.from_api(item) for item in data.get("devices", [])]

    async def get_state_for_fans(self, fans: list[Fan]) -> dict[str, FanState]:
        fans_by_id = {fan.unique_id: fan for fan in fans}

        for fan in fans:
            await self._request(
                "POST",
                "https://prod.mycfan.pgtls.net/v1/mycfan/deviceControls",
                json={
                    "appliance_id": fan.unique_id,
                    "method": GET,
                    "packet": QUERY_PACKET,
                },
            )

        # Wait a bit to allow cloud to process the responses
        await asyncio.sleep(SLEEP_AFTER_QUERY)

        data = await self._request(
            "GET",
            "https://prod.mycfan.pgtls.net/v1/mycfan/deviceControls",
        )

        """
        Example response data:
        {   
            "controls": [
                {
                    "accepted_id": "xxx",
                    "accepted_at": "20251117054743+0000",
                    "appliance_id": "xxx",
                    "method": "GET",
                    "status": "complete",
                    "completed_at": "20251117054744+0000",
                    "result": "success_response",
                    "reason": "200",
                    "packet": "0A0080013000F0013200F1014100F20...",
                },
            ]
        }
        """

        _LOGGER.debug("Fetched deviceControls: %s", data)

        fan_states: dict[str, FanState] = {}
        if "controls" in data:
            data["controls"].sort(key=lambda x: x.get("completed_at", ""), reverse=True)
            for control in data["controls"]:
                if control["method"] != GET:
                    continue
                if control.get("status") != "complete":
                    continue
                if control.get("result") != "success_response":
                    continue
                if (fan := fans_by_id.get(control["appliance_id"])) is None:
                    continue
                if fan.unique_id in fan_states:
                    continue

                state = decode_get_state_packet(control["packet"])
                fan_states[fan.unique_id] = state
                _LOGGER.debug(
                    "Fetched state for %s: is_on=%s, speed=%s, reverse=%s, yuragi=%s",
                    fan.name,
                    state.is_on,
                    state.speed,
                    state.reverse,
                    state.yuragi,
                )

        return fan_states

    async def get_state_for_fan(self, fan: Fan) -> FanState:
        states = await self.get_state_for_fans([fan])
        return states[fan.unique_id]

    async def set_state(self, fan: Fan, state: FanState):
        packet = make_command_packet(state)
        await self._post_device_controls(fan, SET, packet)

    async def _post_device_controls(
        self, fan: Fan, method: Literal["GET", "SET"], packet: str
    ):
        data = await self._request(
            "POST",
            "https://prod.mycfan.pgtls.net/v1/mycfan/deviceControls",
            json={
                "appliance_id": fan.unique_id,
                "method": method,
                "packet": packet,
            },
        )
        _LOGGER.debug("deviceControls response: %s", data)


def get_timestamp():
    now = dt.now(timezone.utc)
    return now.strftime("%Y%m%d%H%M%S+0000")


def make_command_packet(state: FanState) -> str:
    if state.speed < MIN_SPEED or state.speed > MAX_SPEED:
        raise ValueError(f"Speed must be between {MIN_SPEED} and {MAX_SPEED}")

    if not state.is_on:
        return OFF_PACKET

    speed_nibble = f"{state.speed:01X}"
    reverse_nibble = "2" if state.reverse else "1"
    yuragi_nibble = "0" if state.yuragi else "1"

    nibbles = (
        f"090093014200FD010400FC013000FE014000800130"
        f"00F0013{speed_nibble}"
        f"00F1014{reverse_nibble}"
        f"00F2013{yuragi_nibble}"
        f"00F804FF31FFFF"
    )

    return nibbles


def decode_get_state_packet(packet: str) -> FanState:
    """
    Example packet value:
    0A0080013000F0013100F1014100F2013100F8043131000000F902000000FA04314
    0000000FB02000000862E2A0000FE01000000000000000000000000000000000000
    000000000000000000000000000000000000000000000000880142
    """

    if packet[:9] != "0A0080013":
        raise ValueError("Unknown packet header", packet[:9])

    if packet[9:10] == "0":
        is_on = True
    elif packet[9:10] == "1":
        is_on = False
    else:
        raise ValueError("Unknown ON/OFF nibble", packet[9:10])

    speed_prefix = packet[10:17]
    if speed_prefix != "00F0013":
        raise ValueError("Unknown speed prefix", speed_prefix)

    speed_nibble = packet[17:18]
    speed = int(speed_nibble, 16)

    reverse_prefix = packet[18:25]
    if reverse_prefix != "00F1014":
        raise ValueError("Unknown reverse prefix", reverse_prefix)
    reverse_nibble = packet[25:26]
    reverse = reverse_nibble == "2"

    yuragi_prefix = packet[26:33]
    if yuragi_prefix != "00F2013":
        raise ValueError("Unknown yuragi prefix", yuragi_prefix)
    yuragi_nibble = packet[33:34]
    yuragi = yuragi_nibble == "0"

    return FanState(
        is_on=is_on,
        speed=speed,
        reverse=reverse,
        yuragi=yuragi,
    )
