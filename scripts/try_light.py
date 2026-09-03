#!/usr/bin/env python3
"""Send one light command to a fan and report what changed.

Unlike the other scripts this one WRITES to an appliance: it is the check that
a light command built from the discovered field ids is actually accepted.

    python3 scripts/try_light.py --device 1 --on --brightness 40
    python3 scripts/try_light.py --device 1 --off

It prints the packet before sending, reads the light's state before and after,
and says whether the device reported the change.
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

api, const, types_ = load("api", "const", "types")


def pick(fans, wanted):
    if wanted is None:
        return fans[0]
    if wanted.isdigit() and int(wanted) < len(fans):
        return fans[int(wanted)]
    matches = [f for f in fans if f.name.lower() == wanted.lower()]
    return matches[0] if matches else None


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
        if not fans:
            print("No devices on this account.")
            return 1

        fan = pick(fans, args.device)
        if fan is None:
            print(f"No device called {args.device!r}")
            return 1

        before = await client.get_state_for_fan(fan)
        print(f"{fan.name}")
        print(f"  light before : {before.light}")
        print(f"  fan before   : {before.fan}")

        brightness = args.brightness
        if brightness is None:
            brightness = (
                before.light.brightness if before.light else const.MAX_BRIGHTNESS
            )

        current = before.light
        state = types_.LightState(
            is_on=args.on,
            brightness=brightness,
            color_temp=current.color_temp if current else 0,
            sleep=args.sleep if args.sleep is not None else bool(current and current.sleep),
            sleep_brightness=(
                args.sleep_brightness
                if args.sleep_brightness is not None
                else (current.sleep_brightness if current else 1)
            ),
        )
        command = api.make_light_command_packet(state)
        print(f"\n  sending      : {state}")
        print(f"  packet       : {command}")

        if args.two_step:
            # The mode switch appears to reset the sleep brightness, so try
            # setting the mode first and the brightness in a second command.
            mode_only = types_.LightState(
                is_on=state.is_on,
                brightness=state.brightness,
                color_temp=state.color_temp,
                sleep=state.sleep,
                sleep_brightness=current.sleep_brightness if current else 1,
            )
            print(f"  step 1       : {api.make_light_command_packet(mode_only)}")
            await client.set_light_state(fan, mode_only)
            await asyncio.sleep(args.gap)
            print(f"  step 2       : {command}")
            await client.set_light_state(fan, state)
        else:
            await client.set_light_state(fan, state)

        after = await client.get_state_for_fan(fan)
        print(f"\n  light after  : {after.light}")
        print(f"  fan after    : {after.fan}")

        if after.light is None:
            print("\n  The device stopped reporting light state.")
            return 1

        # Compare every field, not just power: a device that stores a value
        # without acting on it looks identical to one that applied it, and a
        # value it rejects outright comes back changed.
        differences = [
            (name, getattr(state, name), getattr(after.light, name))
            for name in ("is_on", "brightness", "color_temp", "sleep", "sleep_brightness")
            if getattr(state, name) != getattr(after.light, name)
        ]

        if differences:
            print("\n  The device did not take the command as sent:")
            for name, asked, got in differences:
                print(f"    {name}: asked {asked}, reports {got}")
            return 1

        print("\n  The device reports every value that was asked for.")
        print("  That is not proof the light acted on them - check the light itself.")
        if before.fan != after.fan:
            print("  Note: the fan state also changed, which it should not have.")
            return 1
        return 0
    finally:
        await client.session.close()
        await client.auth.session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--device", help="device index or name (default: the first)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--on", action="store_true", help="switch the light on")
    group.add_argument("--off", action="store_true", help="switch the light off")
    parser.add_argument(
        "--brightness",
        type=int,
        help=f"{const.MIN_BRIGHTNESS}-{const.MAX_BRIGHTNESS} percent "
        "(default: leave as it is)",
    )
    sleep = parser.add_mutually_exclusive_group()
    sleep.add_argument(
        "--sleep", dest="sleep", action="store_true", default=None,
        help="switch to sleep mode",
    )
    sleep.add_argument(
        "--no-sleep", dest="sleep", action="store_false", default=None,
        help="switch to normal mode",
    )
    parser.add_argument(
        "--two-step",
        action="store_true",
        help="send the mode change first, then the brightness, as two commands",
    )
    parser.add_argument(
        "--gap", type=float, default=3.0, help="seconds between the two steps"
    )
    parser.add_argument(
        "--sleep-brightness",
        type=int,
        help=f"sleep mode brightness, {const.MIN_BRIGHTNESS}-{const.MAX_BRIGHTNESS} "
        "percent (default: leave as it is)",
    )
    args = parser.parse_args()
    args.on = not args.off
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
