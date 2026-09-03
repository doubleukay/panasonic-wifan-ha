#!/usr/bin/env python3
"""Try candidate shapes of a light command until one moves the light.

The device beeps at a minimal light packet — so it accepts it — but does not
switch the light, which means the packet is missing something the Panasonic app
sends. The app's own packets are not observable through the cloud log, so this
walks a set of candidate shapes and asks after each whether the light moved.

Every byte comes from what the fan itself reports; only the light's power field
is changed. Nothing is invented.

    python3 scripts/try_light_variants.py --device 1 --on

WRITES to the appliance: each variant is a real command.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _component import load, use_threaded_dns  # noqa: E402

api, const, packet = load("api", "const", "packet")
Field = packet.Field

# Fields worth asking for: the ones the fan is known to answer.
PROBE_IDS = (
    const.ID_POWER,
    const.ID_SPEED,
    const.ID_DIRECTION,
    const.ID_YURAGI,
    const.ID_LIGHT_POWER,
    const.ID_LIGHT_MODE,
    const.ID_LIGHT_BRIGHTNESS,
    const.ID_LIGHT_COLOR_TEMP,
    const.ID_LIGHT_SLEEP_BRIGHTNESS,
    const.ID_TIMER,
)

FAN_TRAILER = Field(id=const.ID_TIMER, value=bytes.fromhex("FF31FFFF"))


def header() -> list:
    return [Field(id=fid, value=bytes([v])) for fid, v in const.CMD_HEADER]


def variants(current: dict[int, bytes], on: bool) -> list[tuple[str, list]]:
    """Candidate light commands, cheapest shape first."""
    light_power = bytes([0x30 if on else 0x31])

    def echo(field_id: int):
        """The device's own current value for a field, if it reported one."""
        value = current.get(field_id)
        return [Field(id=field_id, value=value)] if value else []

    light = [Field(id=const.ID_LIGHT_POWER, value=light_power)]
    brightness = echo(const.ID_LIGHT_BRIGHTNESS)
    fan_state = (
        echo(const.ID_POWER)
        + echo(const.ID_SPEED)
        + echo(const.ID_DIRECTION)
        + echo(const.ID_YURAGI)
    )
    neighbours = echo(const.ID_LIGHT_MODE) + echo(const.ID_LIGHT_COLOR_TEMP) + echo(
        const.ID_LIGHT_SLEEP_BRIGHTNESS
    )

    return [
        ("power only", header() + light),
        ("power + brightness (what 0.1.1 sends)", header() + light + brightness),
        (
            "power + brightness + fan trailer",
            header() + light + brightness + [FAN_TRAILER],
        ),
        (
            "light fields in device order",
            header()
            + light
            + echo(const.ID_LIGHT_MODE)
            + brightness
            + echo(const.ID_LIGHT_COLOR_TEMP)
            + echo(const.ID_LIGHT_SLEEP_BRIGHTNESS),
        ),
        (
            "full state echoed, light flipped",
            header() + fan_state + light + brightness + [FAN_TRAILER],
        ),
        (
            "full state echoed with neighbours",
            header()
            + fan_state
            + light
            + echo(const.ID_LIGHT_MODE)
            + brightness
            + echo(const.ID_LIGHT_COLOR_TEMP)
            + echo(const.ID_LIGHT_SLEEP_BRIGHTNESS)
            + [FAN_TRAILER],
        ),
    ]


def describe(fields: list) -> str:
    return " ".join(f"{f.id:04X}={f.value.hex().upper()}" for f in fields)


async def read_fields(client, fan) -> dict[int, bytes]:
    control = await client.query_raw(fan, list(PROBE_IDS))
    if control is None or control.get("result") != "success_response":
        return {}
    return {f.id: f.value for f in packet.decode(control["packet"])}


async def run(args: argparse.Namespace) -> int:
    username = args.username or os.environ.get("PANASONIC_USERNAME")
    password = args.password or os.environ.get("PANASONIC_PASSWORD")
    if not username:
        username = input("Panasonic account email: ").strip()
    if not password:
        password = getpass.getpass("Panasonic account password: ")

    use_threaded_dns()
    client = api.ApiClient(username, password)
    try:
        fans = await client.get_devices()
        fan = fans[int(args.device)] if args.device else fans[0]

        current = await read_fields(client, fan)
        if not current:
            print("The device did not answer the initial read.")
            return 1

        print(f"{fan.name} currently reports:")
        for field_id in sorted(current):
            print(f"  {field_id:#06x} = {current[field_id].hex().upper()}")

        candidates = variants(current, args.on)
        if args.only is not None:
            candidates = [candidates[args.only - 1]]

        print(
            f"\nSending {len(candidates)} candidate(s) to switch the light "
            f"{'on' if args.on else 'off'}.\n"
        )

        for number, (name, fields) in enumerate(candidates, start=1):
            command = packet.encode(fields)
            print(f"[{number}] {name}")
            print(f"    fields: {describe(fields)}")
            print(f"    packet: {command}")

            await client._post_device_controls(fan, "SET", command)

            answer = input("    Did the light change? [y/N/q] ").strip().lower()
            if answer == "q":
                print("\nStopped.")
                return 0
            if answer == "y":
                print(f"\nThat one works: variant {number}, {name}")
                print(f"packet: {command}")
                return 0

        print("\nNone of them moved the light.")
        return 1
    finally:
        await client.session.close()
        await client.auth.session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--device", help="device index (default: the first)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--on", action="store_true")
    group.add_argument("--off", action="store_true")
    parser.add_argument(
        "--only", type=int, help="send just this variant number, then stop"
    )
    args = parser.parse_args()
    args.on = not args.off
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
