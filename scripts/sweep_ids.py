#!/usr/bin/env python3
"""Find out which packet fields a Panasonic fan answers to.

The fan replies to a GET packet with whatever fields it was asked for, so
sweeping a range of ids shows which ones exist and what they currently hold.
Run it once with the light off and once with it on: the ids whose values differ
are the light's, and they go into ID_LIGHT_POWER / ID_LIGHT_BRIGHTNESS in
const.py.

    python3 scripts/sweep_ids.py --out light-off.json
    # switch the light on in the Panasonic app, then
    python3 scripts/sweep_ids.py --out light-on.json
    python3 scripts/sweep_ids.py --diff light-off.json light-on.json

Credentials come from --username/--password, from PANASONIC_USERNAME and
PANASONIC_PASSWORD, or from a prompt. They are only ever sent to Panasonic's
own login endpoint, and are never written to the output files.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _component import load, use_threaded_dns  # noqa: E402

api, const, packet = load("api", "const", "packet")

DEFAULT_FIRST_ID = 0x0080
DEFAULT_LAST_ID = 0x00FF
KNOWN = {
    const.ID_POWER: "power",
    const.ID_SPEED: "speed",
    const.ID_DIRECTION: "direction",
    const.ID_YURAGI: "yuragi",
    const.ID_TIMER: "timer?",
    const.ID_OFF_TIMER: "off timer?",
    const.ID_INFO: "info blob",
    const.ID_CMD_MARKER: "command marker",
    const.ID_CMD_FC: "command header",
    const.ID_CMD_FD: "command header",
    const.ID_CMD_FE: "command header",
}


def printable(value: bytes) -> str:
    """Show a value as text where it looks like text, dots elsewhere."""
    return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in value)


def describe(field_id: int, value: bytes) -> str:
    label = KNOWN.get(field_id, "")
    hex_value = value.hex().upper() or "<empty>"
    return (
        f"  {field_id:#06x}  {len(value):3d}B  {hex_value:<40s}"
        f"  {printable(value):<20s}  {label}"
    )


def chunks(items: list[int], size: int) -> list[list[int]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def sweep(
    client,
    fan,
    ids: list[int],
    wave_size: int,
    attempts: int,
    delay: float,
    post_gap: float,
) -> dict[int, bytes]:
    """Query ids one at a time, but with a whole wave of them in flight at once.

    The fan rejects an entire query if it contains a single field it does not
    have (result=error_response, reason=505), so asking for ids in groups is no
    use for discovery. Each request is therefore for one id — but the cloud
    queues them independently, so a wave can be posted and then collected in a
    single read. Each reply names the field it carries, so replies need no
    matching up with their requests.
    """
    found: dict[int, bytes] = {}
    waves = chunks(ids, wave_size)

    for index, wave in enumerate(waves, start=1):
        label = f"{wave[0]:#06x}-{wave[-1]:#06x}"
        print(f"[{index}/{len(waves)}] {label} ...", end="", flush=True)

        marker = await client.newest_completed_at(fan)

        for field_id in wave:
            await client.request_fields(fan, [field_id])
            if post_gap:
                await asyncio.sleep(post_gap)

        answered = 0
        for _ in range(attempts):
            await asyncio.sleep(delay)
            controls = await client.recent_controls(fan, marker)
            answered = len(controls)

            for control in controls:
                if control.get("result") != "success_response":
                    continue
                for field in packet.decode(control["packet"]):
                    found[field.id] = field.value

            if answered >= len(wave):
                break

        supported = [f"{i:#06x}" for i in wave if i in found]
        print(
            f" {answered}/{len(wave)} replied"
            + (f", present: {', '.join(supported)}" if supported else "")
        )

    return found


def report(found: dict[int, bytes]) -> None:
    print(f"\n{len(found)} field(s) answered:\n")
    print(f"  {'id':<8s}{'len':>4s}  {'value':<40s}  {'ascii':<20s}  note")
    for field_id in sorted(found):
        print(describe(field_id, found[field_id]))


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text())


def diff(before_path: Path, after_path: Path) -> int:
    before, after = load_snapshot(before_path), load_snapshot(after_path)
    before_fields = before["fields"]
    after_fields = after["fields"]

    changed = sorted(
        field_id
        for field_id in set(before_fields) | set(after_fields)
        if before_fields.get(field_id) != after_fields.get(field_id)
    )

    print(f"{before_path.name} ({before.get('label', '?')}) -> "
          f"{after_path.name} ({after.get('label', '?')})\n")

    if not changed:
        print("Nothing changed. Was the light actually toggled between runs?")
        return 1

    print("Fields that changed:\n")
    for field_id in changed:
        old = before_fields.get(field_id, "<absent>")
        new = after_fields.get(field_id, "<absent>")
        note = KNOWN.get(int(field_id, 16), "")
        print(f"  {field_id}  {old:<20s} -> {new:<20s}  {note}")

    print(
        "\nIds above that are not already known settings are the candidates "
        "for ID_LIGHT_POWER / ID_LIGHT_BRIGHTNESS in const.py."
    )
    return 0


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

        print("Devices:")
        for index, fan in enumerate(fans):
            print(f"  [{index}] {fan}")

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

        print(f"\nSweeping {fan.name} ({fan.product_code}) "
              f"from {args.first:#06x} to {args.last:#06x}\n")

        ids = list(range(args.first, args.last + 1))
        found = await sweep(
            client, fan, ids, args.wave, args.attempts, args.delay, args.gap
        )
        report(found)

        if args.out:
            snapshot = {
                "device": {
                    "name": fan.name,
                    "product_code": fan.product_code,
                },
                "label": args.label or args.out,
                "fields": {
                    f"{field_id:#06x}": value.hex().upper()
                    for field_id, value in sorted(found.items())
                },
            }
            Path(args.out).write_text(json.dumps(snapshot, indent=2) + "\n")
            print(f"\nWrote {args.out}")

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
        "--first",
        type=lambda v: int(v, 0),
        default=DEFAULT_FIRST_ID,
        help=f"first field id (default {DEFAULT_FIRST_ID:#06x})",
    )
    parser.add_argument(
        "--last",
        type=lambda v: int(v, 0),
        default=DEFAULT_LAST_ID,
        help=f"last field id (default {DEFAULT_LAST_ID:#06x})",
    )
    parser.add_argument(
        "--wave", type=int, default=12, help="requests in flight at once (default 12)"
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=6,
        help="reads per wave while waiting for replies (default 6)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="seconds between those reads (default 2)",
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=0.2,
        help="seconds between requests within a wave (default 0.2)",
    )
    parser.add_argument("--out", help="write the result to this JSON file")
    parser.add_argument("--label", help="note stored in the JSON, e.g. 'light off'")
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("BEFORE", "AFTER"),
        help="compare two saved sweeps instead of querying",
    )
    args = parser.parse_args()

    if args.diff:
        return diff(Path(args.diff[0]), Path(args.diff[1]))

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
