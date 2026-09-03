# Light control for panasonic-wifan-ha

Date: 2026-09-02

## Problem

The integration exposes a fan only. Panasonic's own app also controls the
light and its brightness on fans that have one, so the capability exists in the
same cloud API — but the packet fields that carry it are undocumented. A search
of public sources found no protocol documentation and no other implementation:
this repository is the only prior art.

The device under test for the existing code, an F-M12EC, has no light. The user
has a light-equipped fan on the same account.

## Constraints

- The light bytes are unknown and must not be guessed. Sending invented fields
  to a real appliance is not something to do speculatively.
- Owner uses an iPhone, so pulling the Android app apart for its constant table
  is not available.
- Fan behaviour must not regress. The bytes the integration sends today are the
  only known-good commands.

## Approach

Two pieces: make the protocol layer able to express a light, and give the owner
a way to find the ids.

### Packet codec

`decode_get_state_packet` and `make_command_packet` sliced fixed offsets out of
hex strings, which only works for the exact field layout the F-M12EC returns
and cannot express a field the author has not seen.

The packet format is regular:

```
[count: 1 byte] ( [id: 2 bytes] [length: 1 byte] [value: length bytes] )*
```

`packet.py` implements that as `encode`/`decode`/`query` over a `Field` record.
`api.py` is rebuilt on top of it. The refactor is byte-for-byte compatible: the
tests assert the exact command strings the previous implementation produced.

### State model

`FanState` stays as it is. `LightState` (on/off, brightness) and `DeviceState`
(a fan state plus an optional light state) are new. A poll returns a
`DeviceState`, so a device with no light simply carries `light=None`.

### Light platform

`light.py` adds one `LightEntity` per device that reports light fields, sharing
device identifiers with the fan so both entities land on the same device.
Brightness maps between Home Assistant's 1-255 and the device's step range.

The platform returns early when `ID_LIGHT_POWER` is `None`, so the code stays
dormant on a build where the ids are not known.

### Discovery

`scripts/sweep_ids.py` asks the device for each id in a range and prints what
comes back, batching queries and falling back to one id at a time when a batch
is rejected. Two runs — light off, light on — and a `--diff` between them
isolate the light's fields.

This uses only the device's own GET path, so no proxying, no phone tooling, and
no writes to the appliance.

## The ids, as found

Sweeping `0x0080`-`0x00FF` on an F-M12GC found 26 fields; `0x0000`-`0x007F`
returned nothing at all. Two sweeps taken minutes apart, light off then on,
showed no difference — which turned out to mean the sweeps were too coarse to
attribute a change, not that nothing changed.

Polling every field continuously while operating the app settled it:

| Field | Observed |
| --- | --- |
| `0x00F3` | `30` -> `31` on light off, `31` -> `30` on light on |
| `0x00F5` | `64` -> `3A` when brightness was lowered |
| `0x00F0` | `35` -> `36` on a deliberate speed change, as a control |

So light power follows the fan's convention exactly, but brightness does not:
it is a plain percentage byte, `0x64` for 100%, not the `0x3X` digit encoding.
The assumption carried in the original design was wrong on that point, which is
why `MAX_BRIGHTNESS` is 100 rather than 10 and `make_light_command_packet`
writes the byte whole.

A command built by analogy with the fan's — the same four header fields, then
`0x00F3` and `0x00F5` — was accepted by the cloud, and the fan beeped, but the
light did not move. Reading state back showed the requested values, so the
device stores the fields without acting on them.

Walking candidate packet shapes settled it: the light only switches when the
whole group `0x00F3`, `0x00F4`, `0x00F5`, `0x00F6`, `0x00F7` is present, in
that order. Power and brightness alone are acknowledged and discarded.

Watching fields while the app's own brightness and warm/daylight controls were
used then resolved two more:

| Field | Observed |
| --- | --- |
| `0x00F5` | `0x14` -> `0x01` -> `0x64` across the brightness slider |
| `0x00F6` | `0x20` -> `0x00` on warm, `0x00` -> `0x64` on daylight |

So `0x00F6` is colour temperature on the same percentage scale as brightness,
warm at 0 and daylight at 100. It is presented in Home Assistant as 2700K to
6500K; the device reports a percentage and the fitting's real colour
temperatures are not published, so those Kelvin ends are a reading of "warm"
and "daylight" rather than measured values. The mapping is linear and
monotonic, which is what the slider needs.

Watching the app's sleep mode resolved the last two:

| Field | Observed |
| --- | --- |
| `0x00F4` | `0x42` -> `0x43` on sleep mode, back on leaving it |
| `0x00F7` | `0x32`, `0x01`, `0x64` across sleep mode's own brightness control |

So the light has two modes with separate brightness settings, sleep dimming
below what the normal range allows. Every field in the light group is now
accounted for, and the mechanism that echoed unknown fields back untouched has
been removed along with `LightState.companions` — a command can be built
entirely from a known state.

`0x00F7` takes three fixed steps rather than a range, which only became clear
after the first attempt shipped. Writing `0x3C` to it was reported as accepted
and read back as the previous value: the device ignores anything that is not
`0x01`, `0x32` or `0x64`. Watching the app confirmed it only ever uses those
three. The read-back had looked like confirmation because the verification
compared power and normal brightness alone; it now compares every field, and
says explicitly that an echoed value is not proof the light acted.

Sleep mode is exposed as the light's effect (`Normal`/`Sleep`) rather than as a
separate entity or switch, since it is a mode of one light. The brightness
slider addresses whichever mode is active, snapping to the nearest step in
sleep mode. Both brightness values travel in every command so that switching
modes does not discard the other.

The Panasonic app's own packets were never observed. The cloud's control log
carries only the requesting client's commands, so `watch_controls.py` shows our
traffic and not the app's. The ids came from observation of state rather than of
commands.

Fields still unmapped: `0x0081`, `0x0082`, `0x008A`, `0x009D`-`0x009F`,
`0x00F4`, `0x00F6`, `0x00F7`. `0x008C` holds the model name in ASCII.

## Testing

`tests/` runs without Home Assistant, loading the protocol modules through a
stand-in package so the Home Assistant imports in `__init__.py` are skipped.
Coverage: codec round-trips, real captured packets, malformed input, the exact
legacy command bytes, and the light path exercised against stand-in ids.

## Out of scope

Timers (`0x00F8`-`0x00FB`), the 46-byte `0x0086` blob, and colour temperature.
Colour temperature is not in scope until a sweep shows a field for it.
