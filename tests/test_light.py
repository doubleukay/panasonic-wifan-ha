"""Tests for the light entity.

Skipped unless Home Assistant is installed, since the entity subclasses it.
"""

import asyncio

import pytest

from _component import load

pytest.importorskip("homeassistant", reason="Home Assistant is not installed")

light, types_, store_module = load("light", "types", "store")
Fan = types_.Fan
LightState = types_.LightState

FAN = Fan(
    appliance_id="abc123",
    com_id="FM14GX",
    hashed_guid="g",
    name="Living Room",
    product_code="F-M14GX",
    serial_number="SN1",
)


@pytest.mark.parametrize("value", range(1, 101))
def test_brightness_survives_a_round_trip(value):
    assert light.to_device_brightness(light.to_ha_brightness(value)) == value


def test_brightness_ends_are_the_ends_of_both_scales():
    assert light.to_ha_brightness(1) == 1
    assert light.to_ha_brightness(100) == 255
    assert light.to_device_brightness(1) == 1
    assert light.to_device_brightness(255) == 100


@pytest.mark.parametrize("value", [-5, 0, 255])
def test_out_of_range_device_brightness_is_clamped(value):
    assert 1 <= light.to_ha_brightness(value) <= 255


def test_entity_reports_brightness_and_colour_temperature_support():
    entity, _ = make_entity(
        LightState(is_on=True, brightness=58, color_temp=32)
    )
    assert entity.unique_id == "abc123_light"
    assert entity.color_mode == "color_temp"
    assert entity.supported_color_modes == {"color_temp"}
    assert entity.is_on is True
    assert entity.brightness == light.to_ha_brightness(58)
    assert entity.color_temp_kelvin == light.to_kelvin(32)
    assert entity.min_color_temp_kelvin == 2700
    assert entity.max_color_temp_kelvin == 6500


def test_warm_and_daylight_map_to_the_ends_of_the_kelvin_range():
    assert light.to_kelvin(0) == 2700
    assert light.to_kelvin(100) == 6500
    assert light.to_device_color_temp(2700) == 0
    assert light.to_device_color_temp(6500) == 100


@pytest.mark.parametrize("percent", range(0, 101, 5))
def test_colour_temperature_survives_a_round_trip(percent):
    assert light.to_device_color_temp(light.to_kelvin(percent)) == percent


@pytest.mark.parametrize("kelvin", [1000, 2000, 9000, 20000])
def test_out_of_range_kelvin_is_clamped(kelvin):
    assert 0 <= light.to_device_color_temp(kelvin) <= 100


class Recorder:
    """Stands in for the API, keeping what the entity sent."""

    def __init__(self):
        self.sent = []

    async def set_light_state(self, fan, state):
        self.sent.append(state)


def make_store(light_state):
    return store_module.StateStore(
        {
            FAN.unique_id: types_.DeviceState(
                fan=types_.FanState(is_on=True, speed=3, reverse=False, yuragi=False),
                light=light_state,
            )
        }
    )


def make_entity(state, store=None):
    api = Recorder()
    store = store or make_store(state)
    entity = light.PanasonicWiFiLight(api, FAN, store)
    entity.async_write_ha_state = lambda: None
    return entity, api


def test_turning_on_with_a_kelvin_value_sends_it():
    entity, api = make_entity(LightState(is_on=False, brightness=58, color_temp=0))
    asyncio.run(entity.async_turn_on(color_temp_kelvin=6500))
    assert api.sent[0].color_temp == 100
    assert api.sent[0].is_on is True


def test_turning_on_without_a_kelvin_value_keeps_the_current_one():
    entity, api = make_entity(LightState(is_on=False, brightness=58, color_temp=32))
    asyncio.run(entity.async_turn_on())
    assert api.sent[0].color_temp == 32


def test_the_light_offers_normal_and_sleep_as_effects():
    entity, _ = make_entity(LightState(is_on=True, brightness=58))
    assert entity.effect_list == ["Normal", "Sleep"]
    assert entity.effect == "Normal"


def test_selecting_sleep_switches_the_mode():
    entity, api = make_entity(
        LightState(is_on=True, brightness=58, sleep=False, sleep_brightness=50)
    )
    asyncio.run(entity.async_turn_on(effect="Sleep"))
    assert api.sent[0].sleep is True
    assert entity.effect == "Sleep"


def test_a_sleeping_light_reports_its_sleep_brightness():
    entity, _ = make_entity(
        LightState(is_on=True, brightness=100, sleep=True, sleep_brightness=50)
    )
    assert entity.brightness == light.to_ha_brightness(50)


def test_brightness_in_sleep_mode_snaps_to_a_step():
    """Sleep mode takes three fixed steps; anything else the device ignores."""
    entity, api = make_entity(
        LightState(is_on=True, brightness=80, sleep=True, sleep_brightness=100)
    )
    asyncio.run(entity.async_turn_on(brightness=light.to_ha_brightness(10)))
    assert api.sent[0].sleep_brightness == 1
    assert api.sent[0].brightness == 80  # the normal setting is untouched


@pytest.mark.parametrize(
    "percent,expected", [(1, 1), (20, 1), (40, 50), (60, 50), (90, 100), (100, 100)]
)
def test_every_slider_position_lands_on_a_step(percent, expected):
    entity, api = make_entity(
        LightState(is_on=True, brightness=80, sleep=True, sleep_brightness=1)
    )
    asyncio.run(
        entity.async_turn_on(brightness=light.to_ha_brightness(percent))
    )
    assert api.sent[0].sleep_brightness == expected


def test_brightness_in_normal_mode_leaves_the_sleep_brightness_alone():
    entity, api = make_entity(
        LightState(is_on=True, brightness=80, sleep=False, sleep_brightness=50)
    )
    asyncio.run(entity.async_turn_on(brightness=light.to_ha_brightness(30)))
    assert api.sent[0].brightness == 30
    assert api.sent[0].sleep_brightness == 50


def test_turning_off_keeps_every_setting():
    entity, api = make_entity(
        LightState(
            is_on=True, brightness=80, color_temp=32, sleep=True,
            sleep_brightness=50,
        )
    )
    asyncio.run(entity.async_turn_off())
    sent = api.sent[0]
    assert sent.is_on is False
    assert (sent.brightness, sent.color_temp, sent.sleep, sent.sleep_brightness) == (
        80, 32, True, 50
    )


def test_the_light_offers_no_colour_picker():
    """The fitting has white balance only, so no RGB mode is declared."""
    entity, _ = make_entity(LightState(is_on=True, brightness=58))
    assert entity.supported_color_modes == {"color_temp"}
    assert "hs" not in entity.supported_color_modes
    assert "rgb" not in entity.supported_color_modes


def test_entity_shares_a_device_with_the_fan():
    entity, _ = make_entity(LightState(is_on=False, brightness=1))
    assert entity.device_info["identifiers"] == {("panasonic_wifan", "abc123")}
    assert entity.is_on is False


class Entry:
    entry_id = "entry-1"


def setup_light(states, api=None):
    """Run the light platform's setup with a stand-in hass and collect entities."""
    hass = type("Hass", (), {})()
    hass.data = {
        "panasonic_wifan": {
            Entry.entry_id: {
                "api": api,
                "fans": [FAN],
                "states": states,
                "store": store_module.StateStore(states),
            }
        }
    }
    added = []
    asyncio.run(light.async_setup_entry(hass, Entry(), added.extend))
    return added


def test_setup_adds_a_light_for_a_device_that_reports_one():
    states = {FAN.unique_id: types_.DeviceState(
        fan=types_.FanState(is_on=True, speed=3, reverse=False, yuragi=False),
        light=LightState(is_on=True, brightness=58),
    )}
    entities = setup_light(states)
    assert [e.unique_id for e in entities] == ["abc123_light"]


def test_setup_adds_nothing_for_a_device_with_no_light():
    states = {FAN.unique_id: types_.DeviceState(
        fan=types_.FanState(is_on=True, speed=3, reverse=False, yuragi=False),
        light=None,
    )}
    assert setup_light(states) == []


def test_setup_re_reads_state_that_setup_did_not_capture():
    """A slow first poll must not cost the device its light entity."""
    state = types_.DeviceState(
        fan=types_.FanState(is_on=True, speed=3, reverse=False, yuragi=False),
        light=LightState(is_on=False, brightness=100),
    )

    class Api:
        def __init__(self):
            self.asked_for = None

        async def get_state_for_fans(self, fans):
            self.asked_for = [f.name for f in fans]
            return {FAN.unique_id: state}

    api = Api()
    entities = setup_light({}, api=api)
    assert api.asked_for == ["Living Room"]
    assert [e.unique_id for e in entities] == ["abc123_light"]


def test_setup_survives_a_re_read_that_fails():
    class Api:
        async def get_state_for_fans(self, fans):
            raise RuntimeError("cloud unreachable")

    assert setup_light({}, api=Api()) == []





def test_the_light_sees_a_mode_change_made_by_the_switch():
    """Turning the light on after the sleep switch must not reset the mode."""
    store = make_store(LightState(is_on=False, brightness=80, sleep=False))

    # The switch puts the light into sleep mode.
    store.set_light(FAN, LightState(is_on=False, brightness=80, sleep=True))

    entity, api = make_entity(None, store=store)
    asyncio.run(entity.async_turn_on())

    assert api.sent[0].sleep is True
    assert api.sent[0].is_on is True
