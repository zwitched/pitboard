"""Practice gRPC server so the board can be used without the game.

The service name and RPC names match the public local API. The messages are
the synthetic schema in schema/synthetic/, not a dump from StarCitizen.exe.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field

import grpc

from pitboard.schema_loader import LoadedSchema, load_synthetic

MOCK_ACTIONS: tuple[dict, ...] = (
    {"name": "toggle_flashlight", "category": "character", "label": "Flashlight"},
    {"name": "mobiglas", "category": "character", "label": "mobiGlas"},
    {"name": "star_map", "category": "character", "label": "Star map"},
    {"name": "visor_wipe", "category": "character", "label": "Visor wipe"},
    {"name": "emote_wave", "category": "emote", "label": "Wave"},
    {"name": "emote_salute", "category": "emote", "label": "Salute"},
    {"name": "emote_yes", "category": "emote", "label": "Yes"},
    {"name": "emote_no", "category": "emote", "label": "No"},
    {"name": "v_landing_gear_toggle", "category": "ship", "label": "Landing gear"},
    {"name": "v_lights_toggle", "category": "ship", "label": "Lights"},
    {"name": "v_vtol_toggle", "category": "ship", "label": "VTOL"},
    {"name": "v_decoupled_toggle", "category": "ship", "label": "Decoupled"},
    {"name": "v_gsafe_toggle", "category": "ship", "label": "G-Safe"},
    {"name": "v_flight_ready", "category": "ship", "label": "Flight ready"},
    {"name": "v_ping", "category": "ship", "label": "Ping"},
    {"name": "v_hail", "category": "ship", "label": "Hail"},
    {"name": "v_quantum", "category": "ship", "label": "Quantum travel"},
    {"name": "v_self_destruct", "category": "ship", "label": "Self destruct"},
    {"name": "v_eject", "category": "ship", "label": "Eject"},
    {"name": "v_power_set_off", "category": "ship", "label": "Main power off"},
    {"name": "v_doors_open", "category": "ship", "label": "Open doors"},
    {"name": "v_doors_unlock", "category": "ship", "label": "Unlock doors"},
    {"name": "v_cargo_open", "category": "ship", "label": "Open cargo"},
)

_TOGGLE_FIELDS = {
    "v_landing_gear_toggle": "landing_gear",
    "v_lights_toggle": "lights",
    "v_vtol_toggle": "vtol",
    "v_decoupled_toggle": "decoupled",
    "v_gsafe_toggle": "g_safe",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass
class World:
    lights: bool = True
    landing_gear: bool = False
    vtol: bool = False
    decoupled: bool = False
    g_safe: bool = True
    doors_open: bool = False
    doors_locked: bool = True
    main_power: bool = True
    destroyed: bool = False
    ejected: bool = False
    pending: list[dict] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)
    ejected_at: float | None = None

    def note(self, name: str, detail: str = "") -> None:
        self.pending.append({"name": name, "detail": detail})

    def apply(self, action_name: str, hold_ms: int = 0) -> str:
        if action_name in _TOGGLE_FIELDS:
            attr = _TOGGLE_FIELDS[action_name]
            setattr(self, attr, not getattr(self, attr))
            state = "on" if getattr(self, attr) else "off"
            self.note(action_name, state)
            return f"{action_name} {state}"
        if action_name == "v_power_set_off":
            self.main_power = False
            self.note("Main power", "off")
            return "main power off"
        if action_name in {"v_doors_open", "v_cargo_open"}:
            self.doors_open = True
            self.note(action_name, "open")
            return "open"
        if action_name == "v_doors_unlock":
            self.doors_locked = False
            self.note("Door locks", "unlocked")
            return "unlocked"
        if action_name == "v_self_destruct":
            self.destroyed = True
            self.main_power = False
            self.note("Self destruct", "hull lost")
            return "destruct"
        if action_name == "v_eject":
            self.ejected = True
            self.ejected_at = time.monotonic()
            self.note("Eject", "seat left the ship")
            return "ejected"
        label = action_name
        if hold_ms:
            self.note(action_name, f"hold {hold_ms} ms")
            return f"accepted hold {hold_ms}"
        self.note(action_name, "triggered")
        return f"accepted {label}"

    def build(self, frame_cls, index: int):
        now = time.monotonic()
        elapsed = now - self.started
        frame = frame_cls()
        frame.frame_index = index
        frame.timestamp_unix_ms = int(time.time() * 1000)
        character = frame.character
        if self.ejected:
            character.posture = "eva"
            fall = 0.0 if self.ejected_at is None else now - self.ejected_at
            character.oxygen = _clamp(0.95 - fall * 0.04)
        else:
            character.posture = "seated"
            character.oxygen = _clamp(0.9 + 0.05 * math.sin(elapsed / 4))
        character.health = 0.0 if self.destroyed else _clamp(0.86 + 0.02 * math.sin(elapsed / 7))
        character.hunger = 0.58
        character.thirst = _clamp(0.51 + 0.03 * math.sin(elapsed / 6))
        character.body_temperature_c = 36.7 + 0.15 * math.sin(elapsed / 5)
        character.outside_temperature_c = 18 + 9 * math.sin(elapsed / 8)
        character.heart_rate_bpm = 72 + 8 * math.sin(elapsed / 1.4) + (20 if self.ejected else 0)
        character.gravity_g = 0.0 if self.ejected else 1.0
        character.pressure_kpa = 12.4 if self.ejected else 101.3
        character.radiation = 0.04
        character.intoxication = 0.02
        character.breathable_atmosphere = not self.ejected
        character.balance = 0.42 if self.ejected else 0.9
        character.crew_role = "Pilot"
        character.location_name = "Orison" if not self.ejected else "Crusader orbit"
        character.position.x = 12450.5 + 20 * math.sin(elapsed / 3)
        character.position.y = 842.0
        character.position.z = -3320.25

        if not self.ejected:
            ship = frame.vehicle
            ship.seated = True
            ship.ship_name = "Cutter"
            ship.manufacturer = "Drake"
            ship.model = "Cutter"
            ship.role = "Light freight"
            ship.flight_mode = "SCM"
            ship.landed = self.landing_gear and not self.destroyed
            ship.flying = not ship.landed and not self.destroyed
            front = 0.0 if self.destroyed else _clamp(0.78 + 0.18 * math.sin(elapsed / 1.6))
            rear = 0.0 if self.destroyed else _clamp(0.66 + 0.12 * math.sin(elapsed / 2.1))
            left = 0.0 if self.destroyed else _clamp(0.84 + 0.08 * math.sin(elapsed / 2.4))
            right = 0.0 if self.destroyed else _clamp(0.8 + 0.1 * math.cos(elapsed / 2.2))
            top = 0.0 if self.destroyed else _clamp(0.72 + 0.1 * math.sin(elapsed / 1.9))
            bottom = 0.0 if self.destroyed else _clamp(0.7 + 0.1 * math.cos(elapsed / 2.6))
            ship.shield_front = front
            ship.shield_rear = rear
            ship.shield_left = left
            ship.shield_right = right
            ship.shield_top = top
            ship.shield_bottom = bottom
            ship.shield_faces["front"] = front
            ship.shield_faces["rear"] = rear
            ship.shield_faces["left"] = left
            ship.shield_faces["right"] = right
            ship.shield_faces["top"] = top
            ship.shield_faces["bottom"] = bottom
            ship.hull = 0.0 if self.destroyed else 0.93
            ship.speed_mps = 0.0 if self.destroyed or self.landing_gear else 150 + 80 * math.sin(elapsed / 3)
            ship.vertical_speed_mps = 0.0 if self.destroyed else 18 * math.cos(elapsed / 2.5)
            ship.radar_altitude_m = 40.0 if self.landing_gear else 2400 + 500 * math.sin(elapsed / 5)
            ship.g_force = 0.2 if self.destroyed else 1.1 + 2.4 * abs(math.sin(elapsed / 2.2))
            ship.decoys = 22
            ship.noise = 8
            ship.boost_reserve = 0.0 if not self.main_power else _clamp(0.62 + 0.2 * math.sin(elapsed / 3.5))
            ship.boost_active = ship.boost_reserve > 0.75 and self.main_power
            ship.hydrogen = 0.0 if not self.main_power else 0.71
            ship.power_engines = 0.0 if not self.main_power else 0.45
            ship.power_weapons = 0.0 if not self.main_power else 0.25
            ship.power_shields = 0.0 if not self.main_power else 0.3
            ship.main_power = self.main_power and not self.destroyed
            ship.landing_gear = self.landing_gear
            ship.lights = self.lights and self.main_power
            ship.vtol = self.vtol
            ship.decoupled = self.decoupled
            ship.g_safe = self.g_safe
            ship.cruise_control = False
            ship.proximity_assist = True
            ship.esp = False
            ship.night_vision = False
            ship.doors_open = self.doors_open
            ship.doors_locked = self.doors_locked
            weapons = frame.weapons
            weapons.ready = 0 if self.destroyed or not self.main_power else 2
            weapons.total = 2
            weapons.active_group = 1
            weapons.gimbals_locked = False
            group = weapons.groups.add()
            group.index = 1
            group.name = "Group 1"
            group.ready = weapons.ready > 0
        frame.force_feedback.intensity = 0.0 if self.ejected else _clamp(0.15 + 0.15 * abs(math.sin(elapsed)))
        frame.turret.occupied = False
        frame.turret.yaw_deg = 0.0
        frame.turret.pitch_deg = 4 * math.sin(elapsed / 2)

        pending = list(self.pending)
        self.pending.clear()
        if not pending and index and index % 136 == 0:
            pending.append({"name": "Radar contact", "detail": "Faint return, 6 km"})
        for item in pending:
            event = frame.events.add()
            event.name = item["name"]
            event.detail = item["detail"]
            event.timestamp_unix_ms = frame.timestamp_unix_ms
        return frame


class MockTelemetryServer:
    def __init__(self, schema: LoadedSchema | None = None, fps: float = 17.0):
        self.schema = schema or load_synthetic()
        self.fps = fps
        self.world = World()
        self._server: grpc.aio.Server | None = None
        self.port = 0

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> int:
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("The practice server only binds to loopback.")
        service = self.schema.service_name
        frame_cls = self.schema.response_class("TelemetryStream")
        stream_req = self.schema.request_class("TelemetryStream")
        list_req = self.schema.request_class("ListTriggerableActions")
        list_resp = self.schema.response_class("ListTriggerableActions")
        trig_req = self.schema.request_class("TriggerGameAction")
        trig_resp = self.schema.response_class("TriggerGameAction")
        world = self.world
        delay = 1 / self.fps if self.fps else 0.05

        async def telemetry_stream(request, context):
            index = 0
            while True:
                cancelled = getattr(context, "cancelled", None)
                if callable(cancelled) and cancelled():
                    return
                yield world.build(frame_cls, index)
                index += 1
                await asyncio.sleep(delay)

        async def list_actions(request, context):
            message = list_resp()
            for action in MOCK_ACTIONS:
                item = message.actions.add()
                item.action_name = action["name"]
                item.category = action["category"]
                item.label = action["label"]
                item.available = True
            return message

        async def trigger(request, context):
            message = trig_resp()
            known = {action["name"] for action in MOCK_ACTIONS}
            name = request.action_name
            if name not in known:
                message.accepted = False
                message.message = "unknown action"
                return message
            detail = world.apply(name, int(request.hold_ms or 0))
            message.accepted = True
            message.message = detail
            return message

        server = grpc.aio.server()
        handlers = {
            "TelemetryStream": grpc.unary_stream_rpc_method_handler(
                telemetry_stream,
                request_deserializer=stream_req.FromString,
                response_serializer=frame_cls.SerializeToString,
            ),
            "ListTriggerableActions": grpc.unary_unary_rpc_method_handler(
                list_actions,
                request_deserializer=list_req.FromString,
                response_serializer=list_resp.SerializeToString,
            ),
            "TriggerGameAction": grpc.unary_unary_rpc_method_handler(
                trigger,
                request_deserializer=trig_req.FromString,
                response_serializer=trig_resp.SerializeToString,
            ),
        }
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(service, handlers),))
        self.port = server.add_insecure_port(f"{host}:{port}")
        await server.start()
        self._server = server
        return self.port

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.stop(0)
            self._server = None


async def serve(port: int = 29421) -> None:
    server = MockTelemetryServer()
    bound = await server.start(port=port)
    print(f"Practice telemetry listening on 127.0.0.1:{bound}")
    print("This is not Star Citizen. Leave it on loopback.")
    try:
        await server._server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop()
        raise
