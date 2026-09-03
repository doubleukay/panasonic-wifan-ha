"""Encoding and decoding of Panasonic WIFAN device packets.

A packet is an upper-case hex string with a one-byte field count followed by
that many TLV fields::

    [count: 1 byte] ( [id: 2 bytes] [length: 1 byte] [value: length bytes] )*

For example the response to a state query starts ``0A`` (ten fields) and
continues ``0080 01 30`` (field 0x0080, one byte, value 0x30 = fan is on).

Values are ASCII-ish: a numeric setting is stored as a high nibble that
identifies the value's flavour and a low nibble holding the number itself, so
speed 2 is ``0x32`` and speed 10 is ``0x3A``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

MAX_FIELDS = 0xFF
MAX_VALUE_LENGTH = 0xFF


class PacketError(ValueError):
    """Raised when a packet cannot be parsed or built."""


@dataclass(frozen=True)
class Field:
    """A single TLV field within a packet."""

    id: int
    value: bytes

    @property
    def byte(self) -> int:
        """The value's only byte, for the many single-byte settings."""
        if len(self.value) != 1:
            raise PacketError(
                f"Field {self.id:#06x} holds {len(self.value)} bytes, expected 1"
            )
        return self.value[0]

    @property
    def low_nibble(self) -> int:
        """The low nibble of a single-byte value."""
        return self.byte & 0x0F

    @property
    def high_nibble(self) -> int:
        """The high nibble of a single-byte value."""
        return self.byte >> 4

    def __str__(self) -> str:
        return f"{self.id:04X}={self.value.hex().upper() or '<empty>'}"


def nibble_byte(high: int, low: int) -> bytes:
    """Build a one-byte value from its high and low nibbles."""
    if not 0 <= high <= 0xF:
        raise PacketError(f"High nibble out of range: {high}")
    if not 0 <= low <= 0xF:
        raise PacketError(f"Low nibble out of range: {low}")
    return bytes([(high << 4) | low])


def encode(fields: Sequence[Field]) -> str:
    """Serialise fields into a packet."""
    if len(fields) > MAX_FIELDS:
        raise PacketError(f"Too many fields: {len(fields)}")

    parts = [f"{len(fields):02X}"]
    for field in fields:
        if not 0 <= field.id <= 0xFFFF:
            raise PacketError(f"Field id out of range: {field.id}")
        if len(field.value) > MAX_VALUE_LENGTH:
            raise PacketError(
                f"Field {field.id:#06x} value too long: {len(field.value)} bytes"
            )
        parts.append(f"{field.id:04X}{len(field.value):02X}{field.value.hex().upper()}")

    return "".join(parts)


def decode(packet: str) -> list[Field]:
    """Parse a packet into its fields.

    Trailing bytes past the declared field count are ignored; devices pad some
    responses.
    """
    try:
        data = bytes.fromhex(packet)
    except ValueError as err:
        raise PacketError(f"Packet is not valid hex: {packet!r}") from err

    if not data:
        raise PacketError("Packet is empty")

    count = data[0]
    fields: list[Field] = []
    pos = 1

    for index in range(count):
        if pos + 3 > len(data):
            raise PacketError(
                f"Packet truncated in header of field {index + 1} of {count}"
            )
        field_id = int.from_bytes(data[pos : pos + 2], "big")
        length = data[pos + 2]
        pos += 3

        if pos + length > len(data):
            raise PacketError(
                f"Packet truncated in value of field {field_id:#06x}: "
                f"want {length} bytes, have {len(data) - pos}"
            )
        fields.append(Field(id=field_id, value=data[pos : pos + length]))
        pos += length

    return fields


def as_dict(fields: Iterable[Field]) -> dict[int, Field]:
    """Index fields by id, keeping the first occurrence of each."""
    indexed: dict[int, Field] = {}
    for field in fields:
        indexed.setdefault(field.id, field)
    return indexed


def query(ids: Iterable[int]) -> str:
    """Build a GET packet asking the device for the given field ids."""
    return encode([Field(id=field_id, value=b"") for field_id in ids])
