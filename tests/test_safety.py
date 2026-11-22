import pytest

from pitboard.safety import acceptable_action_name, classify_action, is_dangerous, prettify_action


@pytest.mark.parametrize(
    "name",
    [
        "v_self_destruct",
        "self-destruct",
        "v_eject",
        "eject",
        "v_power_set_off",
        "main_power_off",
        "master_power_shutdown",
        "v_doors_open",
        "v_doors_unlock",
        "open_doors",
        "unlock_port",
        "cargo_open",
        "v_cargo_open",
        "jettison_cargo",
        "scuttle",
    ],
)
def test_hazardous_names(name):
    assert is_dangerous(name)


@pytest.mark.parametrize(
    "name",
    [
        "v_lights_toggle",
        "v_power_engine",
        "v_doors_close",
        "v_landing_gear_toggle",
        "toggle_flashlight",
        "emote_wave",
        "v_flight_ready",
        "close_doors",
        "lock_doors",
    ],
)
def test_safe_names_stay_available(name):
    assert not is_dangerous(name)


def test_classify_and_label():
    assert classify_action("emote_wave") == "emote"
    assert classify_action("v_lights_toggle") == "ship"
    assert classify_action("toggle_flashlight") == "character"
    assert classify_action("anything", "emotes") == "emote"
    assert prettify_action("v_power_set_off") == "Power Set Off"


def test_control_characters_are_rejected():
    assert acceptable_action_name("v_lights_toggle")
    assert not acceptable_action_name("lights\n")
    assert not acceptable_action_name("")
    assert not acceptable_action_name("x" * 97)
