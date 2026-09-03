"""
API Client for interacting with the Panasonic WiFan cloud service.
"""

import aiohttp
import asyncio
from datetime import datetime as dt, timezone
from time import monotonic
import logging
from typing import Literal, Sequence

from . import packet
from .auth import PanasonicGLBAuthClient
from .const import (
    CMD_HEADER,
    DIGIT_HIGH_NIBBLE,
    DIRECTION_FORWARD_LOW,
    DIRECTION_HIGH_NIBBLE,
    DIRECTION_REVERSE_LOW,
    ID_LIGHT_BRIGHTNESS,
    ID_LIGHT_POWER,
    LIGHT_MODE_NORMAL,
    LIGHT_MODE_SLEEP,
    SLEEP_BRIGHTNESS_STEPS,
    ID_OFF_TIMER,
    ID_POWER,
    ID_SPEED,
    ID_TIMER,
    ID_DIRECTION,
    ID_LIGHT_COLOR_TEMP,
    ID_LIGHT_MODE,
    ID_LIGHT_SLEEP_BRIGHTNESS,
    ID_YURAGI,
    MAX_BRIGHTNESS,
    MAX_COLOR_TEMP,
    MAX_SPEED,
    MIN_BRIGHTNESS,
    MIN_COLOR_TEMP,
    MIN_SPEED,
    POWER_OFF,
    POWER_ON,
    QUERY_IDS,
    YURAGI_OFF,
    YURAGI_ON,
)
from .packet import Field, PacketError
from .types import DeviceState, Fan, FanState, LightState

BASE_URL = "https://prod.mycfan.pgtls.net/v1/mycfan/user"
DEVICE_CONTROLS_URL = "https://prod.mycfan.pgtls.net/v1/mycfan/deviceControls"
API_KEY = "rZLwuRtU0nFb20Mh6LShL6uY3fZ5tBlarz4ONmdl"
OAUTH_CLIENT_ID = "8k1QeEXDxt3qGgYOvDY7NmZLfl60YfNi"

# Trailing fields the app sends with every command. They look like timer
# slots; 0xFF appears to mean "leave alone".
ON_TRAILER = Field(id=ID_TIMER, value=bytes.fromhex("FF31FFFF"))
OFF_TRAILER = Field(id=ID_OFF_TIMER, value=bytes.fromhex("3140FFFF"))

SLEEP_AFTER_QUERY = 2  # seconds

# How long a state read stays good for. Each appliance carries a fan, a light
# and a sleep switch, and they update on the same schedule, so without this
# they would each poll the cloud separately for the same answer.
CACHE_TTL = 60  # seconds
GET = "GET"
SET = "SET"

_LOGGER = logging.getLogger(__name__)


def _query_ids() -> tuple[int, ...]:
    """Field ids to poll, including the light group if its ids are known."""
    ids = list(QUERY_IDS)
    if ID_LIGHT_POWER is not None:
        ids.append(ID_LIGHT_POWER)
    if ID_LIGHT_BRIGHTNESS is not None:
        ids.append(ID_LIGHT_BRIGHTNESS)
    ids.append(ID_LIGHT_COLOR_TEMP)
    ids.append(ID_LIGHT_MODE)
    ids.append(ID_LIGHT_SLEEP_BRIGHTNESS)
    return tuple(ids)


QUERY_PACKET = packet.query(_query_ids())


class ApiClient:
    def __init__(self, username: str, password: str):
        self.auth = PanasonicGLBAuthClient(username, password)
        self.session = aiohttp.ClientSession()
        self._cache: dict[str, tuple[float, DeviceState]] = {}
        self._cache_lock = asyncio.Lock()

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

    async def _completed_markers(self, fans: list[Fan]) -> dict[str, str]:
        """The newest reply already logged for each appliance.

        A poll must not accept a reply that completed before its own request,
        or a state change made moments earlier is read back as the old state.
        """
        data = await self._request("GET", DEVICE_CONTROLS_URL)

        markers = {fan.unique_id: "" for fan in fans}
        for control in _controls(data):
            if control.get("method") != GET:
                continue
            appliance = control.get("appliance_id")
            if appliance in markers:
                markers[appliance] = max(
                    markers[appliance], control.get("completed_at", "")
                )
        return markers

    async def get_state_for_fans(
        self,
        fans: list[Fan],
        *,
        attempts: int = 5,
        delay: float | None = None,
    ) -> dict[str, DeviceState]:
        """Read the state of several appliances.

        A device answers through the cloud, and how long that takes varies, so
        the reply is waited for over several reads rather than a single one. A
        caller that decides something from the presence of a state — whether to
        create a light entity, say — would otherwise see nothing at all on a
        slow reply.
        """
        if delay is None:
            delay = SLEEP_AFTER_QUERY

        fans_by_id = {fan.unique_id: fan for fan in fans}
        markers = await self._completed_markers(fans)

        for fan in fans:
            await self.request_fields(fan, _query_ids())

        device_states: dict[str, DeviceState] = {}

        for attempt in range(attempts):
            await asyncio.sleep(delay)

            data = await self._request("GET", DEVICE_CONTROLS_URL)

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

            controls = sorted(
                _controls(data), key=lambda x: x.get("completed_at", ""), reverse=True
            )
            for control in controls:
                if control.get("method") != GET:
                    continue
                if control.get("status") != "complete":
                    continue
                if control.get("result") != "success_response":
                    continue
                if (fan := fans_by_id.get(control.get("appliance_id"))) is None:
                    continue
                if fan.unique_id in device_states:
                    continue
                if control.get("completed_at", "") <= markers[fan.unique_id]:
                    # Logged before this poll asked, so it may predate a change
                    # made moments ago.
                    continue

                state = decode_get_state_packet(control["packet"])
                device_states[fan.unique_id] = state
                self._cache[fan.unique_id] = (monotonic(), state)
                _LOGGER.debug(
                    "Fetched state for %s: is_on=%s, speed=%s, reverse=%s, "
                    "yuragi=%s, light=%s",
                    fan.name,
                    state.fan.is_on,
                    state.fan.speed,
                    state.fan.reverse,
                    state.fan.yuragi,
                    state.light,
                )

            if len(device_states) == len(fans):
                break

            _LOGGER.debug(
                "Have state for %s of %s appliance(s) after attempt %s",
                len(device_states),
                len(fans),
                attempt + 1,
            )

        missing = [f.name for f in fans if f.unique_id not in device_states]
        if missing:
            _LOGGER.warning(
                "No state returned for %s after %s attempt(s)",
                ", ".join(missing),
                attempts,
            )

        return device_states

    async def get_state_for_fan(
        self, fan: Fan, *, max_age: float | None = CACHE_TTL
    ) -> DeviceState:
        """Read one appliance's state, reusing a recent read if there is one.

        The entities for one appliance refresh together, so a short-lived cache
        turns three polls into one. Pass max_age=0 to force a fresh read.
        """
        if (cached := self._cached(fan, max_age)) is not None:
            _LOGGER.debug("Using the cached state for %s", fan.name)
            return cached

        async with self._cache_lock:
            # Another entity may have refreshed it while this one waited.
            if (cached := self._cached(fan, max_age)) is not None:
                _LOGGER.debug("Using the state %s just fetched", fan.name)
                return cached

            states = await self.get_state_for_fans([fan])
            return states[fan.unique_id]

    def _cached(self, fan: Fan, max_age: float | None) -> DeviceState | None:
        if not max_age:
            return None
        if (entry := self._cache.get(fan.unique_id)) is None:
            return None
        fetched_at, state = entry
        if monotonic() - fetched_at > max_age:
            return None
        return state

    def forget(self, fan: Fan) -> None:
        """Drop a cached state, after a command has changed the appliance."""
        self._cache.pop(fan.unique_id, None)

    async def _latest_control(self, fan: Fan) -> dict | None:
        """The most recently completed GET response for one appliance."""
        data = await self._request("GET", DEVICE_CONTROLS_URL)
        controls = [
            control
            for control in _controls(data)
            if control.get("method") == GET
            and control.get("appliance_id") == fan.unique_id
            and control.get("status") == "complete"
        ]
        if not controls:
            return None
        return max(controls, key=lambda control: control.get("completed_at", ""))

    async def controls(self) -> list[dict]:
        """Every control record the cloud reports for this account.

        Includes commands issued by other clients, Panasonic's own app among
        them, which is how the app's packets can be observed rather than
        guessed at.
        """
        data = await self._request("GET", DEVICE_CONTROLS_URL)
        return _controls(data)

    async def newest_completed_at(self, fan: Fan) -> str:
        """Timestamp of the most recent completed response, or an empty string."""
        control = await self._latest_control(fan)
        return control.get("completed_at", "") if control else ""

    async def request_fields(self, fan: Fan, ids: Sequence[int]) -> None:
        """Ask a device for fields without waiting for its reply.

        The cloud queues each request separately, so several can be in flight at
        once and collected together with recent_controls().
        """
        await self._post_device_controls(fan, GET, packet.query(ids))

    async def recent_controls(self, fan: Fan, since: str = "") -> list[dict]:
        """Completed responses for one appliance newer than the given timestamp."""
        data = await self._request("GET", DEVICE_CONTROLS_URL)
        controls = [
            control
            for control in _controls(data)
            if control.get("method") == GET
            and control.get("appliance_id") == fan.unique_id
            and control.get("status") == "complete"
            and control.get("completed_at", "") > since
        ]
        return sorted(controls, key=lambda control: control.get("completed_at", ""))

    async def query_raw(
        self,
        fan: Fan,
        ids: Sequence[int],
        *,
        attempts: int = 5,
        delay: float | None = None,
        require_ids: bool = False,
    ) -> dict | None:
        """Ask a device for arbitrary fields and return the raw control record.

        Used by the field discovery scripts. Returns None if no fresh response
        arrives, and the record itself — including a failed ``result`` — when
        the device rejects the query.

        Anything else polling the same appliance — Home Assistant itself, or
        another script — puts its own replies in the same log, and those answer
        a different set of fields. With ``require_ids`` a reply is only accepted
        if it carries every field that was asked for, which keeps another
        poller's answer from being read as this one's.
        """
        if delay is None:
            delay = SLEEP_AFTER_QUERY

        previous = await self._latest_control(fan)
        since = previous.get("completed_at", "") if previous else ""

        await self._post_device_controls(fan, GET, packet.query(ids))

        wanted = set(ids)

        for _ in range(attempts):
            await asyncio.sleep(delay)
            control = await self._latest_control(fan)
            if not control or control.get("completed_at", "") <= since:
                continue
            if require_ids and not _answers(control, wanted):
                # Someone else's reply, logged in the same place.
                _LOGGER.debug(
                    "Ignoring a reply that does not cover the fields asked for"
                )
                continue
            return control

        return None

    async def set_state(self, fan: Fan, state: FanState):
        self.forget(fan)
        await self._post_device_controls(fan, SET, make_command_packet(state))

    async def set_light_state(self, fan: Fan, state: LightState):
        self.forget(fan)
        await self._post_device_controls(fan, SET, make_light_command_packet(state))

    async def _post_device_controls(
        self, fan: Fan, method: Literal["GET", "SET"], payload: str
    ):
        data = await self._request(
            "POST",
            DEVICE_CONTROLS_URL,
            json={
                "appliance_id": fan.unique_id,
                "method": method,
                "packet": payload,
            },
        )
        _LOGGER.debug("deviceControls response: %s", data)


def _answers(control: dict, wanted: set[int]) -> bool:
    """Whether a reply carries every field that was asked for."""
    if control.get("result") != "success_response":
        # A rejection is about the query that was sent, so it does belong to it.
        return True
    try:
        present = {field.id for field in packet.decode(control.get("packet") or "")}
    except PacketError:
        return False
    return wanted.issubset(present)


def _controls(data) -> list[dict]:
    """The control records in a deviceControls response.

    The endpoint answers with JSON null when nothing is queued, and omits the
    key in some replies, so neither can be assumed present.
    """
    if not isinstance(data, dict):
        return []
    return data.get("controls") or []


def get_timestamp():
    now = dt.now(timezone.utc)
    return now.strftime("%Y%m%d%H%M%S+0000")


def _header_fields() -> list[Field]:
    return [
        Field(id=field_id, value=bytes([value])) for field_id, value in CMD_HEADER
    ]


def _digit_field(field_id: int, value: int) -> Field:
    """A numeric setting, stored as one byte with 0x3 in the high nibble."""
    return Field(id=field_id, value=packet.nibble_byte(DIGIT_HIGH_NIBBLE, value))


def make_command_packet(state: FanState) -> str:
    if state.speed < MIN_SPEED or state.speed > MAX_SPEED:
        raise ValueError(f"Speed must be between {MIN_SPEED} and {MAX_SPEED}")

    fields = _header_fields()

    if not state.is_on:
        fields.append(_digit_field(ID_POWER, POWER_OFF))
        fields.append(OFF_TRAILER)
        return packet.encode(fields)

    fields.append(_digit_field(ID_POWER, POWER_ON))
    fields.append(_digit_field(ID_SPEED, state.speed))
    fields.append(
        Field(
            id=ID_DIRECTION,
            value=packet.nibble_byte(
                DIRECTION_HIGH_NIBBLE,
                DIRECTION_REVERSE_LOW if state.reverse else DIRECTION_FORWARD_LOW,
            ),
        )
    )
    fields.append(
        _digit_field(ID_YURAGI, YURAGI_ON if state.yuragi else YURAGI_OFF)
    )
    fields.append(ON_TRAILER)

    return packet.encode(fields)


def make_light_command_packet(state: LightState) -> str:
    """Build a SET packet for the light.

    The device ignores a command carrying only power and brightness — it beeps
    and does nothing — so the whole light group goes out in the order the
    device reports it: power, mode, brightness, colour temperature, sleep
    brightness. Values for the mode not currently active are sent as held, so
    switching modes does not discard the other one's setting.
    """
    if ID_LIGHT_POWER is None or ID_LIGHT_BRIGHTNESS is None:
        raise RuntimeError(
            "Light field ids are unknown for this integration; "
            "run scripts/sweep_ids.py to discover them"
        )

    if state.brightness < MIN_BRIGHTNESS or state.brightness > MAX_BRIGHTNESS:
        raise ValueError(
            f"Brightness must be between {MIN_BRIGHTNESS} and {MAX_BRIGHTNESS}"
        )
    if state.sleep_brightness not in SLEEP_BRIGHTNESS_STEPS:
        # The device silently keeps its previous value for anything else.
        raise ValueError(
            "Sleep brightness must be one of "
            f"{', '.join(str(s) for s in SLEEP_BRIGHTNESS_STEPS)}"
        )
    if state.color_temp < MIN_COLOR_TEMP or state.color_temp > MAX_COLOR_TEMP:
        raise ValueError(
            f"Colour temperature must be between {MIN_COLOR_TEMP} and "
            f"{MAX_COLOR_TEMP}"
        )

    fields = _header_fields()
    fields.append(
        _digit_field(ID_LIGHT_POWER, POWER_ON if state.is_on else POWER_OFF)
    )
    fields.append(
        Field(
            id=ID_LIGHT_MODE,
            value=bytes([LIGHT_MODE_SLEEP if state.sleep else LIGHT_MODE_NORMAL]),
        )
    )
    # These are percentages, so they are written whole rather than through the
    # nibble encoding the fan settings use.
    fields.append(Field(id=ID_LIGHT_BRIGHTNESS, value=bytes([state.brightness])))
    fields.append(Field(id=ID_LIGHT_COLOR_TEMP, value=bytes([state.color_temp])))
    fields.append(
        Field(id=ID_LIGHT_SLEEP_BRIGHTNESS, value=bytes([state.sleep_brightness]))
    )

    return packet.encode(fields)


def decode_get_state_packet(response: str) -> DeviceState:
    """
    Example packet value:
    0A0080013000F0013100F1014100F2013100F8043131000000F902000000FA04314
    0000000FB02000000862E2A0000FE01000000000000000000000000000000000000
    000000000000000000000000000000000000000000000000880142
    """

    fields = packet.as_dict(packet.decode(response))

    def require(field_id: int, name: str) -> Field:
        if (field := fields.get(field_id)) is None:
            raise PacketError(f"Packet has no {name} field ({field_id:#06x})")
        return field

    power = require(ID_POWER, "power")
    if power.high_nibble != DIGIT_HIGH_NIBBLE:
        raise PacketError(f"Unknown power value {power.byte:#04x}")
    if power.low_nibble == POWER_ON:
        is_on = True
    elif power.low_nibble == POWER_OFF:
        is_on = False
    else:
        raise PacketError(f"Unknown ON/OFF nibble {power.low_nibble:#x}")

    speed_field = require(ID_SPEED, "speed")
    if speed_field.high_nibble != DIGIT_HIGH_NIBBLE:
        raise PacketError(f"Unknown speed value {speed_field.byte:#04x}")
    speed = speed_field.low_nibble

    direction = require(ID_DIRECTION, "direction")
    if direction.high_nibble != DIRECTION_HIGH_NIBBLE:
        raise PacketError(f"Unknown direction value {direction.byte:#04x}")
    reverse = direction.low_nibble == DIRECTION_REVERSE_LOW

    yuragi_field = require(ID_YURAGI, "yuragi")
    if yuragi_field.high_nibble != DIGIT_HIGH_NIBBLE:
        raise PacketError(f"Unknown yuragi value {yuragi_field.byte:#04x}")
    yuragi = yuragi_field.low_nibble == YURAGI_ON

    return DeviceState(
        fan=FanState(
            is_on=is_on,
            speed=speed,
            reverse=reverse,
            yuragi=yuragi,
        ),
        light=_decode_light(fields),
    )


def nearest_sleep_step(value: int) -> int:
    """The sleep brightness step closest to a value.

    The device takes only the steps and ignores anything else, so a value from
    a continuous control has to be snapped to one of them.
    """
    return min(SLEEP_BRIGHTNESS_STEPS, key=lambda step: abs(step - value))


def _decode_light(fields: dict[int, Field]) -> LightState | None:
    """Read light state, if this device reports any."""
    if ID_LIGHT_POWER is None:
        return None
    if (power := fields.get(ID_LIGHT_POWER)) is None:
        return None

    brightness = MAX_BRIGHTNESS
    if ID_LIGHT_BRIGHTNESS is not None and (
        field := fields.get(ID_LIGHT_BRIGHTNESS)
    ):
        brightness = min(MAX_BRIGHTNESS, max(MIN_BRIGHTNESS, field.byte))

    color_temp = MIN_COLOR_TEMP
    if field := fields.get(ID_LIGHT_COLOR_TEMP):
        color_temp = min(MAX_COLOR_TEMP, max(MIN_COLOR_TEMP, field.byte))

    sleep = False
    if field := fields.get(ID_LIGHT_MODE):
        sleep = field.byte == LIGHT_MODE_SLEEP

    sleep_brightness = SLEEP_BRIGHTNESS_STEPS[0]
    if field := fields.get(ID_LIGHT_SLEEP_BRIGHTNESS):
        sleep_brightness = nearest_sleep_step(field.byte)

    return LightState(
        is_on=power.low_nibble == POWER_ON,
        brightness=brightness,
        color_temp=color_temp,
        sleep=sleep,
        sleep_brightness=sleep_brightness,
    )
