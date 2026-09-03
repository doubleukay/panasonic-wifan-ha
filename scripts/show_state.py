#!/usr/bin/env python3
"""Print the decoded state of every fan on an account.

Read-only: it sends the same GET query the integration polls with and never
writes to an appliance. Useful for checking that the codec understands your
device before installing anything into Home Assistant.

    python3 scripts/show_state.py

Credentials come from --username/--password, from PANASONIC_USERNAME and
PANASONIC_PASSWORD, or from a prompt.
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

api, packet = load("api", "packet")


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

        print(f"Query packet: {api.QUERY_PACKET}\n")

        for fan in fans:
            print(f"{fan}")
            control = await client.query_raw(fan, api._query_ids())
            if control is None:
                print("  no response\n")
                continue
            if control.get("result") != "success_response":
                print(
                    f"  device rejected the query "
                    f"(result={control.get('result')}, reason={control.get('reason')})\n"
                )
                continue

            raw = control["packet"]
            print(f"  raw      : {raw}")
            for field in packet.decode(raw):
                print(f"  field    : {field}")

            state = api.decode_get_state_packet(raw)
            print(f"  fan      : {state.fan}")
            print(f"  light    : {state.light}\n")

        return 0
    finally:
        await client.session.close()
        await client.auth.session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username")
    parser.add_argument("--password")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
