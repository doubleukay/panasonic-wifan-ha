"""Tests for the TLV packet codec."""

import pytest

from _component import load

packet = load("packet")

# Captured from a real F-M12EC: the query the app sends, and the reply.
REAL_QUERY = "0A00800000F00000F10000F20000F80000F90000FA0000FB00008600008800"
REAL_RESPONSE = (
    "0A0080013000F0013100F1014100F2013100F8043131000000F902000000FA0431"
    "40000000FB02000000862E2A0000FE010000000000000000000000000000000000"
    "00000000000000000000000000000000000000000000000000880142"
)


def test_decode_real_query_yields_ten_empty_fields():
    fields = packet.decode(REAL_QUERY)
    assert [f.id for f in fields] == [
        0x0080, 0x00F0, 0x00F1, 0x00F2, 0x00F8,
        0x00F9, 0x00FA, 0x00FB, 0x0086, 0x0088,
    ]
    assert all(f.value == b"" for f in fields)


def test_query_rebuilds_the_real_query_byte_for_byte():
    ids = [f.id for f in packet.decode(REAL_QUERY)]
    assert packet.query(ids) == REAL_QUERY


def test_decode_real_response_reads_values_and_lengths():
    fields = packet.as_dict(packet.decode(REAL_RESPONSE))
    assert fields[0x0080].value == bytes([0x30])
    assert fields[0x00F0].value == bytes([0x31])
    assert fields[0x0086].value.hex().upper().startswith("2A0000FE01")
    assert len(fields[0x0086].value) == 0x2E
    assert fields[0x0088].value == bytes([0x42])


def test_encode_decode_roundtrip():
    fields = [
        packet.Field(id=0x0080, value=bytes([0x30])),
        packet.Field(id=0x0086, value=bytes(46)),
        packet.Field(id=0x00F8, value=bytes.fromhex("FF31FFFF")),
    ]
    assert packet.decode(packet.encode(fields)) == fields


def test_nibbles_split_a_single_byte_value():
    field = packet.Field(id=0x00F1, value=bytes([0x42]))
    assert field.high_nibble == 0x4
    assert field.low_nibble == 0x2
    assert field.byte == 0x42


def test_speed_ten_is_stored_as_0x3a():
    assert packet.nibble_byte(0x3, 10) == bytes([0x3A])
    assert packet.Field(id=0x00F0, value=bytes([0x3A])).low_nibble == 10


def test_byte_rejects_multi_byte_values():
    with pytest.raises(packet.PacketError):
        packet.Field(id=0x00F8, value=bytes(4)).byte


def test_decode_rejects_truncated_value():
    with pytest.raises(packet.PacketError, match="truncated"):
        packet.decode("01008004AABB")


def test_decode_rejects_truncated_header():
    with pytest.raises(packet.PacketError, match="truncated"):
        packet.decode("020080013000F0")


def test_decode_rejects_non_hex():
    with pytest.raises(packet.PacketError, match="valid hex"):
        packet.decode("nonsense")


def test_decode_rejects_empty_packet():
    with pytest.raises(packet.PacketError, match="empty"):
        packet.decode("")


def test_decode_ignores_padding_past_the_field_count():
    fields = packet.decode("010080013000000000")
    assert fields == [packet.Field(id=0x0080, value=bytes([0x30]))]


def test_as_dict_keeps_first_occurrence():
    fields = [
        packet.Field(id=0x0080, value=bytes([0x30])),
        packet.Field(id=0x0080, value=bytes([0x31])),
    ]
    assert packet.as_dict(fields)[0x0080].value == bytes([0x30])


def test_nibble_byte_rejects_out_of_range():
    with pytest.raises(packet.PacketError):
        packet.nibble_byte(0x3, 0x10)
