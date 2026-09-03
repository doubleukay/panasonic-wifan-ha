"""Tests for the live field watcher."""

import json

import watch_fields


def test_ids_from_snapshot_reads_hex_keys(tmp_path):
    path = tmp_path / "sweep.json"
    path.write_text(
        json.dumps({"fields": {"0x0080": "30", "0x00f3": "30", "0x008c": "462D"}})
    )
    assert watch_fields.ids_from_snapshot(path) == [0x0080, 0x008C, 0x00F3]


def test_changes_reports_a_changed_value():
    before = {0x0080: b"\x30", 0x00F3: b"\x30"}
    after = {0x0080: b"\x30", 0x00F3: b"\x31"}
    assert watch_fields.changes(before, after) == [(0x00F3, "30", "31")]


def test_changes_is_empty_when_nothing_moved():
    state = {0x0080: b"\x30"}
    assert watch_fields.changes(state, dict(state)) == []


def test_changes_marks_fields_appearing_and_disappearing():
    assert watch_fields.changes({}, {0x0089: b"\x30"}) == [(0x0089, "<absent>", "30")]
    assert watch_fields.changes({0x0089: b"\x30"}, {}) == [(0x0089, "30", "<absent>")]


def test_changes_marks_an_empty_value():
    assert watch_fields.changes({0x0089: b"\x30"}, {0x0089: b""}) == [
        (0x0089, "30", "<empty>")
    ]


def test_changes_are_ordered_by_id():
    before = {0x00F3: b"\x30", 0x0080: b"\x30"}
    after = {0x00F3: b"\x31", 0x0080: b"\x31"}
    assert [c[0] for c in watch_fields.changes(before, after)] == [0x0080, 0x00F3]
