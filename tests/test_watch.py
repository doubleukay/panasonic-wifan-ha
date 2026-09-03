"""Tests for the control-log watcher."""

import asyncio

import watch_controls

from _component import load

api, packet = load("api", "packet")

NAMES = {"abc123": "Study"}

SET_RECORD = {
    "accepted_id": "id-1",
    "accepted_at": "20260902120000+0000",
    "completed_at": "20260902120001+0000",
    "appliance_id": "abc123",
    "method": "SET",
    "status": "complete",
    "result": "success_response",
    "reason": "200",
    "packet": "020080013000F00135",
}


def test_record_key_separates_different_records():
    other = SET_RECORD | {"accepted_id": "id-2"}
    assert watch_controls.record_key(SET_RECORD) != watch_controls.record_key(other)


def test_record_key_is_stable_for_the_same_record():
    assert watch_controls.record_key(SET_RECORD) == watch_controls.record_key(
        dict(SET_RECORD)
    )


def test_record_key_changes_as_a_record_completes():
    pending = SET_RECORD | {"status": "pending", "completed_at": ""}
    assert watch_controls.record_key(pending) != watch_controls.record_key(SET_RECORD)


def test_format_record_decodes_fields_and_names_the_appliance():
    text = watch_controls.format_record(SET_RECORD, NAMES)
    assert "Study" in text
    assert "<-- SET" in text
    assert "0x0080" in text and "power" in text
    assert "0x00f0" in text and "speed" in text


def test_format_record_marks_only_set_records():
    getter = SET_RECORD | {"method": "GET"}
    assert "<-- SET" not in watch_controls.format_record(getter, NAMES)


def test_format_record_survives_an_undecodable_packet():
    broken = SET_RECORD | {"packet": "FF0080"}
    assert "undecodable" in watch_controls.format_record(broken, NAMES)


def test_format_record_survives_an_empty_packet():
    empty = SET_RECORD | {"packet": ""}
    text = watch_controls.format_record(empty, NAMES)
    assert "Study" in text
    assert "raw:" not in text


def test_controls_returns_every_record_including_set():
    client = api.ApiClient.__new__(api.ApiClient)

    async def fake_request(method, url, **kwargs):
        return {"controls": [SET_RECORD, SET_RECORD | {"method": "GET"}]}

    client._request = fake_request
    records = asyncio.run(client.controls())
    assert [r["method"] for r in records] == ["SET", "GET"]


def test_controls_survives_a_null_response():
    client = api.ApiClient.__new__(api.ApiClient)

    async def fake_request(method, url, **kwargs):
        return None

    client._request = fake_request
    assert asyncio.run(client.controls()) == []
