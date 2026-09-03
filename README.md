# Panasonic WIFAN - Home Assistant Integration

A native Home Assistant integration for Panasonic Malaysia WiFi fans. This integration communicates directly with their Ceiling Fan cloud API.

## Features
- Auto-discover fans
- Turn on/off
- Set fan speed (1-10 range)
- Reverse mode
- Yuragi mode (implemented as "oscillation")
- Optimistic state updates (polling every 5 minutes, shared between entities)
- Light control: on/off, brightness, colour temperature (warm to daylight),
  and sleep mode with its own dimmer, on fans that have a light

## Installation

### HACS (Recommended)
1. Open HACS in Home Assistant
2. Go to Integrations
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add this repository URL: `https://github.com/doubleukay/panasonic-wifan-ha`
6. Select category: "Integration"
7. Click "Add"
8. Search for "Panasonic WIFAN" and install

### Manual Installation
1. Copy the `custom_components/panasonic_wifan` directory to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration
1. Go to Settings → Devices & Services
2. Click "+ Add Integration"
3. Search for "Panasonic WIFAN"
4. Enter your Panasonic username (email) and password. NOTE: social login is not supported.
5. Click Submit

Your fans will be automatically discovered and added as devices.

## Protocol

The cloud API carries opaque hex packets to and from the fan. A packet is a
one-byte field count followed by that many TLV fields:

```
[count: 1 byte] ( [id: 2 bytes] [length: 1 byte] [value: length bytes] )*
```

So `0A0080013000F00131...` means ten fields, of which the first is `0x0080`
(power), one byte long, value `0x30`. Numeric settings put `0x3` in the high
nibble and the number in the low one, so speed 10 is `0x3A`.

Fields seen so far:

| Id | Meaning |
| --- | --- |
| `0x0080` | Power (`0x30` on, `0x31` off) |
| `0x00F0` | Speed, 1-10 |
| `0x00F1` | Direction (`0x41` forward, `0x42` reverse) |
| `0x00F2` | Yuragi (`0x30` on, `0x31` off) |
| `0x0081`, `0x0082`, `0x008A` | Unmapped |
| `0x0086` | 46-byte blob, not decoded |
| `0x0088` | Unknown, constant `0x42` so far |
| `0x008C` | Model name in ASCII, e.g. `F-M12GC` |
| `0x0093`, `0x00FC`, `0x00FD`, `0x00FE` | Constant header on every SET packet |
| `0x009D`, `0x009E`, `0x009F` | Tables, not decoded |
| `0x00F3` | Light power (`0x30` on, `0x31` off) |
| `0x00F4` | Light mode, `0x42` normal and `0x43` sleep |
| `0x00F5` | Light brightness, percentage byte (`0x64` = 100%) |
| `0x00F6` | Light colour temperature, `0x00` warm to `0x64` daylight |
| `0x00F7` | Sleep mode brightness — three fixed steps only: 1, 50, 100 |
| `0x00F8`, `0x00F9`, `0x00FA`, `0x00FB` | Timers, not fully decoded |

## Light control

The light is field `0x00F3` (`0x30` on, `0x31` off, the same convention as the
fan's power) and its brightness is field `0x00F5`, a plain percentage byte
rather than the `0x3X` digit encoding the fan settings use.

A command carrying only those two is **acknowledged and discarded** — the fan
beeps and the light does not move. The whole light group has to be present, in
the order the device reports it:

```
0x00F3 power   0x00F4 mode   0x00F5 brightness   0x00F6 colour temp   0x00F7 sleep brightness
```

The light has two modes. Normal mode (`0x00F4` = `0x42`) uses `0x00F5` for
brightness; sleep mode (`0x43`) dims further than the normal range allows and
keeps its own brightness in `0x00F7`. The device holds both values whichever
mode is active, and every command carries both, so switching modes does not
discard the other setting.

Colour temperature is a percentage from warm at `0x00` to daylight at `0x64`.
The fitting has white balance only — no colour — so the entity declares
`ColorMode.COLOR_TEMP` and no RGB mode. Home Assistant draws that control as a
warm-to-cool gradient, which is a temperature slider rather than a colour
picker.

Sleep brightness is not a range. The device takes `0x01`, `0x32` and `0x64`
and nothing else — sending `0x3C` leaves it on its previous value, reported
back unchanged. So it has three steps where every other percentage field has a
hundred.

In Home Assistant, sleep mode appears as the light's **effect**: `Normal` or
`Sleep`. The brightness slider applies to whichever mode is selected, and in
sleep mode it snaps to the nearest of the three steps.

It is also exposed as a separate **switch**, `Light sleep mode`. That is
deliberate duplication: HomeKit's lightbulb service has no notion of a light
effect, so a bridged light cannot carry sleep mode to Apple Home at all. A
switch is the only shape that crosses that bridge.

### How the entities stay in step

The fan, the light and the sleep switch of one appliance share a single view of
its state, and a state read is cached briefly so they do not each ask the cloud
the same question. Sharing matters as much as the caching: a light command
carries the whole light group, so each one is built from the light's current
settings. If the switch changed the mode and the light entity had not seen it,
turning the light on would send the mode back to normal.

A command is also not the last word on what the appliance did with it — entering
sleep mode lights the fitting whether the command said so or not — so the device
is read back a few seconds afterwards. Conversely a read landing within a few
seconds of a command is dropped, since the appliance may not have reported the
change yet and taking it would undo what was just asked for.

### How these fields were found

Every light field above came from polling the whole field range on an F-M12GC
while operating the corresponding control in the Panasonic app, with a
deliberate fan speed change in the same run as a control. Nothing here is
inferred from documentation, because none exists. A device that does not report
`0x00F3` gets no light entity.

### Finding fields on another model

If a model exposes something this integration does not, the same tooling
applies. All three read-only scripts take `--device <index or name>`.

Print the decoded state of every fan:

```bash
python3 scripts/show_state.py
```

Find which field ids a device answers to at all. The fan rejects a query
containing any field it does not have, so this asks one id per request and
keeps a wave of them in flight:

```bash
python3 scripts/sweep_ids.py --device 1 --out fields.json
```

Watch those fields and print whatever changes, which is what identifies a
control. Operate the thing you are looking for while it runs, and change
something you already understand as a control:

```bash
python3 scripts/watch_fields.py --device 1 --ids-from fields.json
```

Read the cloud's control log, decoded. Note that it appears to carry only this
client's own commands, so the Panasonic app's packets do not show up here:

```bash
python3 scripts/watch_controls.py --history
```

Finally, `scripts/try_light.py` sends a single light command and reports
whether the device came back in the state that was asked for. It is the only
script that writes to an appliance:

```bash
python3 scripts/try_light.py --device 1 --on --brightness 40
```

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install aiohttp pytest
.venv/bin/python -m pytest tests
```

The tests cover the packet codec and every command the integration builds,
including the exact bytes for each fan command, and they run without Home
Assistant installed. Installing `homeassistant` into the same virtualenv adds
the light entity tests, which are skipped otherwise.

## Support

For issues and feature requests, please use the [GitHub issue tracker](https://github.com/doubleukay/panasonic-wifan-ha/issues).

## License

Copyright 2025 Woon Wai Keen

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.