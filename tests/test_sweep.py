"""Tests for the id sweep.

The fan rejects a query outright if it contains one field it does not have, so
the sweep asks for a single id per request and keeps a wave of them in flight.
"""

import asyncio

import pytest

import sweep_ids
from _component import load

packet, types_ = load("packet", "types")

FAN = types_.Fan(
    appliance_id="abc123",
    com_id="FM12GC",
    hashed_guid="g",
    name="Study",
    product_code="F-M12GC",
    serial_number="SN1",
)


class FakeFan:
    """Stands in for the cloud, answering only the ids it has.

    ``lag`` holds replies back for that many reads, so the sweep's polling is
    exercised rather than assumed.
    """

    def __init__(self, values: dict[int, bytes], lag: int = 0):
        self.values = values
        self.lag = lag
        self.pending: list[dict] = []
        self.delivered: list[dict] = []
        self.clock = 0
        self.reads = 0

    async def newest_completed_at(self, fan) -> str:
        everything = self.delivered + self.pending
        return max((c["completed_at"] for c in everything), default="")

    async def request_fields(self, fan, ids) -> None:
        self.clock += 1
        field_id = ids[0]
        record = {
            "method": "GET",
            "appliance_id": fan.unique_id,
            "status": "complete",
            "completed_at": f"{self.clock:020d}",
            "ready_after": self.lag,
        }
        if field_id in self.values:
            record["result"] = "success_response"
            record["packet"] = packet.encode(
                [packet.Field(id=field_id, value=self.values[field_id])]
            )
        else:
            record["result"] = "error_response"
            record["reason"] = "505"
            record["packet"] = ""
        self.pending.append(record)

    async def recent_controls(self, fan, since: str = "") -> list[dict]:
        self.reads += 1
        ready = [c for c in self.pending if c["ready_after"] < self.reads]
        for record in ready:
            self.pending.remove(record)
            self.delivered.append(record)
        return sorted(
            (c for c in self.delivered if c["completed_at"] > since),
            key=lambda c: c["completed_at"],
        )


def run_sweep(client, ids, wave_size=4, attempts=6):
    return asyncio.run(
        sweep_ids.sweep(
            client, FAN, ids, wave_size, attempts, delay=0, post_gap=0
        )
    )


def test_sweep_finds_only_the_ids_the_device_has():
    values = {0x0080: bytes([0x30]), 0x0081: bytes([0x00]), 0x0089: bytes([0x31])}
    client = FakeFan(values)
    found = run_sweep(client, list(range(0x0080, 0x0090)))
    assert found == values


def test_sweep_survives_a_device_that_answers_nothing():
    client = FakeFan({})
    assert run_sweep(client, list(range(0x0080, 0x0088))) == {}


def test_sweep_waits_for_lagging_replies():
    values = {0x0082: bytes.fromhex("00004C00")}
    client = FakeFan(values, lag=2)
    assert run_sweep(client, list(range(0x0080, 0x0084))) == values


def test_sweep_asks_for_one_id_per_request():
    class Recorder(FakeFan):
        def __init__(self):
            super().__init__({})
            self.requested = []

        async def request_fields(self, fan, ids):
            self.requested.append(list(ids))
            await super().request_fields(fan, ids)

    client = Recorder()
    run_sweep(client, list(range(0x0080, 0x0084)))
    assert all(len(request) == 1 for request in client.requested)
    assert [r[0] for r in client.requested] == [0x0080, 0x0081, 0x0082, 0x0083]


def test_chunks_splits_without_losing_ids():
    ids = list(range(0x0080, 0x0090))
    assert sweep_ids.chunks(ids, 6) == [ids[0:6], ids[6:12], ids[12:16]]


@pytest.mark.parametrize("value,expected", [(b"\x30", "0"), (b"\x00", "."), (b"\x4c", "L")])
def test_printable_shows_text_where_there_is_text(value, expected):
    assert sweep_ids.printable(value) == expected
