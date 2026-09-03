#!/usr/bin/env python3
"""Poll a device's fields and print whatever changes.

Two sweeps taken minutes apart cannot tell "this field never changes" from "the
thing I toggled never actually changed". This asks for every known field over
and over and reports each difference as it happens, so operating a control in
the Panasonic app shows immediately which field it moves — if any.

    python3 scripts/watch_fields.py --device 1 --ids-from light-off.json
    # while it runs, toggle the light in the Panasonic app

Read-only: it sends GET queries and never commands an appliance.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _component import load, use_threaded_dns  # noqa: E402

api, const, packet = load("api", "const", "packet")

KNOWN_IDS = {
    const.ID_POWER: "power",
    const.ID_SPEED: "speed",
    const.ID_DIRECTION: "direction",
    const.ID_YURAGI: "yuragi",
    const.ID_TIMER: "timer?",
    const.ID_OFF_TIMER: "off timer?",
    const.ID_INFO: "info blob",
}


def ids_from_snapshot(path: Path) -> list[int]:
    """The field ids a saved sweep found."""
    snapshot = json.loads(path.read_text())
    return sorted(int(field_id, 16) for field_id in snapshot["fields"])


def changes(
    before: dict[int, bytes], after: dict[int, bytes]
) -> list[tuple[int, str, str]]:
    """Every field that differs, as (id, old, new) with hex or a marker."""
    def shown(values: dict[int, bytes], field_id: int) -> str:
        if field_id not in values:
            return "<absent>"
        return values[field_id].hex().upper() or "<empty>"

    return [
        (field_id, shown(before, field_id), shown(after, field_id))
        for field_id in sorted(set(before) | set(after))
        if before.get(field_id) != after.get(field_id)
    ]


async def poll(client, fan, ids: list[int]) -> dict[int, bytes] | None:
    """One read of every id, or None if the device did not answer."""
    control = await client.query_raw(fan, ids, require_ids=True)
    if control is None or control.get("result") != "success_response":
        return None
    return {field.id: field.value for field in packet.decode(control["packet"])}


async def run(args: argparse.Namespace) -> int:
    username = args.username or os.environ.get("PANASONIC_USERNAME")
    password = args.password or os.environ.get("PANASONIC_PASSWORD")
    if not username:
        username = input("Panasonic account email: ").strip()
    if not password:
        password = getpass.getpass("Panasonic account password: ")

    ids = ids_from_snapshot(Path(args.ids_from))

    use_threaded_dns()
    client = api.ApiClient(username, password)
    try:
        fans = await client.get_devices()
        if not fans:
            print("No devices on this account.")
            return 1

        if args.device is None:
            fan = fans[0]
        elif args.device.isdigit() and int(args.device) < len(fans):
            fan = fans[int(args.device)]
        else:
            matches = [f for f in fans if f.name.lower() == args.device.lower()]
            if not matches:
                print(f"No device called {args.device!r}")
                return 1
            fan = matches[0]

        print(f"Watching {len(ids)} field(s) on {fan.name} for {args.seconds}s.")
        print("Operate the light in the Panasonic app now.\n")

        state = await poll(client, fan, ids)
        if state is None:
            print("The device did not answer the first read.")
            return 1
        print(f"Baseline read: {len(state)} field(s).\n")

        deadline = time.monotonic() + args.seconds
        polls = 0
        while time.monotonic() < deadline:
            fresh = await poll(client, fan, ids)
            polls += 1
            if fresh is None:
                continue

            for field_id, old, new in changes(state, fresh):
                note = KNOWN_IDS.get(field_id, "")
                stamp = time.strftime("%H:%M:%S")
                print(f"{stamp}  {field_id:#06x}  {old} -> {new}  {note}")

            state = fresh

        print(f"\nDone after {polls} read(s).")
        return 0
    finally:
        await client.session.close()
        await client.auth.session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--device", help="device index or name (default: the first)")
    parser.add_argument(
        "--ids-from",
        default="light-off.json",
        help="sweep JSON naming the ids to poll (default light-off.json)",
    )
    parser.add_argument(
        "--seconds", type=int, default=180, help="how long to watch (default 180)"
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
