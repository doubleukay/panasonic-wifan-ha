#!/usr/bin/env python3
"""Watch the cloud's control log and decode every packet that appears.

The log carries commands from every client on the account, including the
Panasonic app. So to learn how the app controls something this integration
cannot, run this and then operate that control in the app: the app's own SET
packet shows up here, decoded.

    python3 scripts/watch_controls.py --seconds 180
    # while it runs, toggle the light in the Panasonic app

Read-only: it polls the log and never sends a command to an appliance.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _component import load, use_threaded_dns  # noqa: E402

api, packet = load("api", "packet")

KNOWN_IDS = {
    0x0080: "power",
    0x00F0: "speed",
    0x00F1: "direction",
    0x00F2: "yuragi",
    0x0093: "command marker",
    0x00FC: "command header",
    0x00FD: "command header",
    0x00FE: "command header",
}


def record_key(record: dict) -> tuple:
    """Identity of a control record, for spotting ones already seen."""
    return (
        record.get("accepted_id", ""),
        record.get("accepted_at", ""),
        record.get("completed_at", ""),
        record.get("status", ""),
        record.get("packet", ""),
    )


def format_record(record: dict, names: dict[str, str]) -> str:
    """One control record, with its packet decoded field by field."""
    appliance = names.get(record.get("appliance_id", ""), record.get("appliance_id", "?"))
    method = record.get("method", "?")
    marker = "  <-- SET" if method == "SET" else ""

    lines = [
        f"{record.get('accepted_at', '?')}  {method:<4s}  {appliance}  "
        f"status={record.get('status')}  result={record.get('result')}"
        f"  reason={record.get('reason')}{marker}"
    ]

    raw = record.get("packet") or ""
    if not raw:
        return "\n".join(lines)

    lines.append(f"    raw: {raw}")
    try:
        fields = packet.decode(raw)
    except packet.PacketError as err:
        lines.append(f"    undecodable: {err}")
        return "\n".join(lines)

    for field in fields:
        note = KNOWN_IDS.get(field.id, "")
        value = field.value.hex().upper() or "<empty>"
        lines.append(f"    {field.id:#06x}  {value:<20s}  {note}")

    return "\n".join(lines)


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
        names = {fan.unique_id: fan.name for fan in fans}
        for fan in fans:
            print(f"  {fan}")

        print(
            f"\nWatching the control log for {args.seconds}s. "
            "Operate the light in the Panasonic app now.\n"
        )

        existing = await client.controls()
        by_method: dict[str, int] = {}
        for record in existing:
            method = record.get("method", "?")
            by_method[method] = by_method.get(method, 0) + 1
        summary = ", ".join(f"{count} {method}" for method, count in sorted(by_method.items()))

        if args.history:
            print(f"{len(existing)} existing record(s) ({summary}):\n")
            for record in sorted(existing, key=lambda r: r.get("accepted_at", "")):
                if args.only_set and record.get("method") != "SET":
                    continue
                print(format_record(record, names))
                print()
        else:
            print(f"({len(existing)} existing record(s) ignored: {summary})\n")

        seen = {record_key(r) for r in existing}

        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(args.interval)

            for record in await client.controls():
                key = record_key(record)
                if key in seen:
                    continue
                seen.add(key)
                print(format_record(record, names))
                print()

        print("Done watching.")
        return 0
    finally:
        await client.session.close()
        await client.auth.session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument(
        "--seconds", type=int, default=180, help="how long to watch (default 180)"
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="print the records already in the log before watching",
    )
    parser.add_argument(
        "--only-set",
        action="store_true",
        help="with --history, show only SET records",
    )
    parser.add_argument(
        "--interval", type=float, default=3.0, help="seconds between polls (default 3)"
    )
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
