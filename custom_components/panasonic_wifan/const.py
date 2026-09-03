"""Constants for the Panasonic WIFAN integration."""

DOMAIN = "panasonic_wifan"

# Platforms
PLATFORMS = ["fan", "light", "switch"]

# Speed settings
MIN_SPEED = 1
MAX_SPEED = 10
SPEED_STEP = 1

# Config flow
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# --- Packet field ids -------------------------------------------------------
#
# Ids confirmed by observing traffic for the F-M12EC (fan, no light).

ID_POWER = 0x0080
ID_SPEED = 0x00F0
ID_DIRECTION = 0x00F1
ID_YURAGI = 0x00F2

# Queried alongside the settings above; contents not yet understood. 0x0086 is
# a 46-byte blob, the rest look like timer state.
ID_TIMER = 0x00F8
ID_UNKNOWN_F9 = 0x00F9
ID_OFF_TIMER = 0x00FA
ID_UNKNOWN_FB = 0x00FB
ID_INFO = 0x0086
ID_UNKNOWN_88 = 0x0088

# Fields every SET packet opens with. Meaning unknown, values are constant.
ID_CMD_MARKER = 0x0093
ID_CMD_FC = 0x00FC
ID_CMD_FD = 0x00FD
ID_CMD_FE = 0x00FE

CMD_HEADER: tuple[tuple[int, int], ...] = (
    (ID_CMD_MARKER, 0x42),
    (ID_CMD_FD, 0x04),
    (ID_CMD_FC, 0x30),
    (ID_CMD_FE, 0x40),
)

# Field ids read on every state poll.
QUERY_IDS: tuple[int, ...] = (
    ID_POWER,
    ID_SPEED,
    ID_DIRECTION,
    ID_YURAGI,
    ID_TIMER,
    ID_UNKNOWN_F9,
    ID_OFF_TIMER,
    ID_UNKNOWN_FB,
    ID_INFO,
    ID_UNKNOWN_88,
)

# Value nibbles
POWER_ON = 0x0
POWER_OFF = 0x1
DIRECTION_HIGH_NIBBLE = 0x4
DIRECTION_FORWARD_LOW = 0x1
DIRECTION_REVERSE_LOW = 0x2
DIGIT_HIGH_NIBBLE = 0x3
YURAGI_ON = 0x0
YURAGI_OFF = 0x1

# --- Light control ----------------------------------------------------------
#
# Found by polling every field on an F-M12GC while operating the light in the
# Panasonic app: 0x00F3 flipped with the light, 0x00F5 with the brightness
# slider, and a deliberate fan speed change moved 0x00F0 in the same run as a
# control.
ID_LIGHT_POWER: int | None = 0x00F3
ID_LIGHT_BRIGHTNESS: int | None = 0x00F5

# Brightness is a plain percentage byte, not the 0x3X digit encoding the fan
# settings use: 0x64 is 100%, 0x3A is 58%.
MIN_BRIGHTNESS = 1
MAX_BRIGHTNESS = 100

# Colour temperature, a percentage like brightness: 0x00 is warm, 0x64 is
# daylight. Watched moving 0x20 -> 0x00 when warm was chosen in the app and
# 0x00 -> 0x64 for daylight.
ID_LIGHT_COLOR_TEMP = 0x00F6
MIN_COLOR_TEMP = 0
MAX_COLOR_TEMP = 100

# The Kelvin values the two ends are presented as in Home Assistant. The scale
# the device reports is a percentage, not Kelvin, and the fitting's real colour
# temperatures are not published, so these are a reasonable reading of "warm"
# and "daylight" rather than measured figures.
WARM_KELVIN = 2700
DAYLIGHT_KELVIN = 6500

# The device ignores a light command unless the whole light group is present,
# in this order: 0x00F3, 0x00F4, 0x00F5, 0x00F6, 0x00F7. Power and brightness
# alone are acknowledged with a beep and discarded.

# Light mode. Sleep mode dims further than the normal range allows and keeps
# its own brightness in 0x00F7. Watched flipping 0x42 -> 0x43 as sleep mode was
# switched on in the app.
ID_LIGHT_MODE = 0x00F4
LIGHT_MODE_NORMAL = 0x42
LIGHT_MODE_SLEEP = 0x43

# Sleep mode's own brightness. Unlike the other percentages this takes three
# fixed steps, not a range: the app was watched moving it between 0x01, 0x32
# and 0x64 and nothing else, and the device rejects a value outside that set -
# sending 0x3C left it on its previous value.
ID_LIGHT_SLEEP_BRIGHTNESS = 0x00F7
SLEEP_BRIGHTNESS_STEPS: tuple[int, ...] = (1, 50, 100)
