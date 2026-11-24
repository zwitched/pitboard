from pitboard.messages import merge_sections, message_to_dict
from pitboard.normalize import normalize
from pitboard.schema_loader import load_synthetic


def _frame():
    schema = load_synthetic()
    return schema.response_class("TelemetryStream")()


def test_proto3_zero_is_kept_when_the_section_is_present():
    frame = _frame()
    frame.character.oxygen = 0.4
    frame.character.health = 0
    parsed = type(frame).FromString(frame.SerializeToString())
    data = message_to_dict(parsed)
    assert data["character"]["health"] == 0
    assert data["character"]["oxygen"] == 0.4
    assert "vehicle" not in data


def test_missing_section_is_kept_across_frames():
    first = _frame()
    first.character.health = 0.55
    first.character.oxygen = 1
    second = _frame()
    second.vehicle.ship_name = "Cutter"
    second.vehicle.speed_mps = 12
    merged = merge_sections(message_to_dict(first), message_to_dict(second))
    assert merged["character"]["health"] == 0.55
    assert merged["vehicle"]["ship_name"] == "Cutter"
    assert merged["vehicle"]["speed_mps"] == 12


def test_explicit_zero_replaces_a_previous_reading():
    first = {"character": {"health": 0.4, "oxygen": 1}}
    second = {"character": {"health": 0, "oxygen": 0.2}}
    merged = merge_sections(first, second)
    assert merged["character"]["health"] == 0
    assert merged["character"]["oxygen"] == 0.2


def test_synthetic_frame_normalizes_character_and_ship():
    frame = _frame()
    frame.character.health = 0.82
    frame.character.oxygen = 0.5
    frame.character.hunger = 0.4
    frame.character.thirst = 0.7
    frame.character.body_temperature_c = 36.6
    frame.character.outside_temperature_c = -12.5
    frame.character.heart_rate_bpm = 88
    frame.character.posture = "seated"
    frame.character.crew_role = "Pilot"
    frame.character.location_name = "Orison"
    frame.character.position.x = 10
    frame.character.position.y = 20
    frame.character.position.z = 30
    frame.character.breathable_atmosphere = True
    ship = frame.vehicle
    ship.ship_name = "Cutter"
    ship.manufacturer = "Drake"
    ship.model = "Cutter"
    ship.flight_mode = "SCM"
    ship.seated = True
    ship.flying = True
    ship.shield_front = 0.9
    ship.shield_rear = 0.2
    ship.hull = 0.77
    ship.speed_mps = 42.5
    ship.vertical_speed_mps = -3
    ship.g_force = 2.4
    ship.radar_altitude_m = 800
    ship.decoys = 10
    ship.noise = 4
    ship.main_power = True
    ship.lights = True
    ship.landing_gear = False
    ship.power_engines = 0.4
    ship.power_weapons = 0.3
    ship.power_shields = 0.3
    frame.weapons.ready = 2
    frame.weapons.total = 2
    frame.weapons.active_group = 1
    frame.weapons.gimbals_locked = False
    event = frame.events.add()
    event.name = "Shield hit"
    event.detail = "Bow"
    view = normalize(message_to_dict(frame), events=[{"name": "Shield hit", "detail": "Bow", "at": None}])
    assert view["character"]["metrics"]["health"]["display"] == "82%"
    assert view["character"]["metrics"]["body_temperature"]["unit"] == "°C"
    assert view["character"]["posture"] == "seated"
    assert view["character"]["location"] == "Orison"
    assert view["character"]["position"]["y"] == 20
    assert view["ship"]["name"] == "Cutter"
    assert view["ship"]["manufacturer"] == "Drake"
    assert view["ship"]["mode"] == "SCM"
    assert view["ship"]["aboard"] is True
    assert view["ship"]["shields"]["faces"]["front"]["ratio"] == 0.9
    assert view["ship"]["shields"]["faces"]["rear"]["ratio"] == 0.2
    assert view["ship"]["metrics"]["speed"]["unit"] == "m/s"
    assert view["ship"]["countermeasures"] == {"decoys": 10, "noise": 4}
    assert view["ship"]["weapons"]["ready"] == 2
    assert view["ship"]["toggles"]["lights"] is True
    assert view["ship"]["toggles"]["main_power"] is True
    assert view["ship"]["power"]["engines"] == 0.4
    assert view["events"][0]["name"] == "Shield hit"


def test_alternate_field_names_and_percent_scale():
    raw = {
        "actor": {
            "hp": 0.5,
            "o2": 0.25,
            "food": 40,
            "hydration": 0.8,
            "body_temp": 37.1,
            "ambient_temp": 210,
            "pulse": 120,
            "stance": "EVA",
            "pos": {"x": 1, "y": 2, "z": 3},
        },
        "vehicle": {
            "vehicle_name": "Aurora",
            "maker": "Roberts",
            "model": "Mk I",
            "shield_forward": 0.9,
            "shield_aft": 0.2,
            "shield_port": 50,
            "hull_integrity": 0.77,
            "velocity_mps": 12.5,
            "gload": 6,
            "gear_down": True,
            "lamps": False,
            "main_power": False,
        },
    }
    view = normalize(raw)
    assert view["character"]["metrics"]["health"]["ratio"] == 0.5
    assert view["character"]["metrics"]["oxygen"]["display"] == "25%"
    assert view["character"]["metrics"]["hunger"]["ratio"] == 0.4
    assert view["character"]["metrics"]["body_temperature"]["display"] == "37.1"
    assert view["character"]["metrics"]["outside_temperature"]["raw"] == 210
    assert view["character"]["metrics"]["heart_rate"]["display"] == "120"
    assert view["character"]["posture"] == "eva"
    assert view["character"]["position"] == {"x": 1.0, "y": 2.0, "z": 3.0}
    assert view["ship"]["name"] == "Aurora"
    assert view["ship"]["manufacturer"] == "Roberts"
    assert view["ship"]["aboard"] is False
    assert view["ship"]["shields"]["faces"]["front"]["ratio"] == 0.9
    assert view["ship"]["shields"]["faces"]["left"]["ratio"] == 0.5
    assert view["ship"]["metrics"]["hull"]["display"] == "77%"
    assert view["ship"]["metrics"]["g_force"]["tone"] == "bad"
    assert view["ship"]["toggles"]["landing_gear"] is True
    assert view["ship"]["toggles"]["lights"] is False
    assert view["ship"]["power"]["main"] is False


def test_field_map_overrides_the_guess():
    raw = {"actor": {"hp": 0.2}, "custom": {"vitals": {"integrity_ratio": 0.9}}}
    view = normalize(raw, field_map={"character.health": "custom.vitals.integrity_ratio"})
    assert view["character"]["metrics"]["health"]["raw"] == 0.9
    assert view["character"]["metrics"]["health"]["path"] == "custom.vitals.integrity_ratio"


def test_mfd_flight_fields_do_not_steal_each_other():
    raw = {
        "vehicle": {
            "ship_name": "Cutlass Black",
            "radar_altitude_m": 812.0,
            "altitude_msl_m": 81914.0,
            "heading_deg": 586.0,
            "hydrogen": 0.6,
            "quantum_fuel": 0.0,
            "g_force": 0.8,
            "g_force_peak": 9.9,
        },
        "turret": {"yaw_deg": 12.0},
    }
    metrics = normalize(raw)["ship"]["metrics"]
    assert metrics["radar_altitude"]["path"] == "vehicle.radar_altitude_m"
    assert metrics["altitude"]["path"] == "vehicle.altitude_msl_m"
    assert metrics["heading"]["raw"] == 226
    assert metrics["heading"]["unit"] == "°"
    assert metrics["hydrogen"]["path"] == "vehicle.hydrogen"
    assert metrics["quantum_fuel"]["display"] == "0%"
    assert metrics["g_force"]["path"] == "vehicle.g_force"
    assert metrics["g_force_peak"]["raw"] == 9.9


def test_missing_mfd_fields_stay_blank():
    raw = {"vehicle": {"speed_mps": 100.0, "altitude": 500.0, "fuel": 0.5}}
    metrics = normalize(raw)["ship"]["metrics"]
    assert metrics["radar_altitude"]["raw"] == 500.0
    assert metrics["altitude"]["raw"] is None
    assert metrics["heading"]["raw"] is None
    assert metrics["hydrogen"]["ratio"] == 0.5
    assert metrics["quantum_fuel"]["raw"] is None
    assert metrics["g_force_peak"]["raw"] is None
