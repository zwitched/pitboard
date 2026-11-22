"""Dynamic gRPC client for GameTelemetryService.

Call shapes come from whichever descriptor set is loaded, so the same code
talks to the synthetic practice server and to a schema extracted from the
owner's StarCitizen.exe.
"""

from __future__ import annotations

from google.protobuf.descriptor import FieldDescriptor

from pitboard.safety import classify_action, is_dangerous, prettify_action
from pitboard.schema_loader import LoadedSchema

_NAME_FIELDS = ("action_name", "action", "name", "action_id", "id")
_HOLD_FIELDS = ("hold_ms", "hold", "hold_millis", "duration_ms")
_INTS = {
    FieldDescriptor.TYPE_INT32,
    FieldDescriptor.TYPE_INT64,
    FieldDescriptor.TYPE_UINT32,
    FieldDescriptor.TYPE_UINT64,
    FieldDescriptor.TYPE_SINT32,
    FieldDescriptor.TYPE_SINT64,
    FieldDescriptor.TYPE_FIXED32,
    FieldDescriptor.TYPE_FIXED64,
    FieldDescriptor.TYPE_SFIXED32,
    FieldDescriptor.TYPE_SFIXED64,
}

CHANNEL_OPTIONS = (("grpc.enable_http_proxy", 0),)


class Unsupported(RuntimeError):
    pass


class DynamicClient:
    def __init__(self, channel, schema: LoadedSchema):
        self.channel = channel
        self.schema = schema

    def has(self, name: str) -> bool:
        return name in self.schema.methods

    def _path(self, name: str) -> str:
        return f"/{self.schema.service_name}/{name}"

    async def telemetry_frames(self):
        method = self.schema.methods.get("TelemetryStream")
        if method is None:
            raise Unsupported("TelemetryStream is not in the loaded schema.")
        if method.client_streaming:
            raise Unsupported("TelemetryStream is a client stream, which this board does not send.")
        request_cls = self.schema.request_class("TelemetryStream")
        response_cls = self.schema.response_class("TelemetryStream")
        request = request_cls()
        if method.server_streaming:
            call = self.channel.unary_stream(
                self._path("TelemetryStream"),
                request_serializer=request_cls.SerializeToString,
                response_deserializer=response_cls.FromString,
            )
            async for frame in call(request):
                yield frame
            return
        call = self.channel.unary_unary(
            self._path("TelemetryStream"),
            request_serializer=request_cls.SerializeToString,
            response_deserializer=response_cls.FromString,
        )
        yield await call(request)

    async def list_actions(self) -> list[dict]:
        if not self.has("ListTriggerableActions"):
            raise Unsupported("This game build does not list commands.")
        request_cls = self.schema.request_class("ListTriggerableActions")
        response_cls = self.schema.response_class("ListTriggerableActions")
        call = self.channel.unary_unary(
            self._path("ListTriggerableActions"),
            request_serializer=request_cls.SerializeToString,
            response_deserializer=response_cls.FromString,
        )
        response = await call(request_cls())
        return actions_from_message(response)

    async def trigger(self, action_name: str, hold_ms: int) -> tuple[bool, str]:
        if not self.has("TriggerGameAction"):
            raise Unsupported("This game build does not accept commands.")
        method = self.schema.methods["TriggerGameAction"]
        request = build_trigger_request(method, action_name, hold_ms)
        request_cls = request.__class__
        response_cls = self.schema.response_class("TriggerGameAction")
        call = self.channel.unary_unary(
            self._path("TriggerGameAction"),
            request_serializer=request_cls.SerializeToString,
            response_deserializer=response_cls.FromString,
        )
        response = await call(request)
        return interpret_trigger_response(response)


def build_trigger_request(method, action_name: str, hold_ms: int):
    from google.protobuf.message_factory import GetMessageClass

    message = GetMessageClass(method.input_type)()
    name_field = None
    hold_field = None
    string_fields = []
    for field in method.input_type.fields:
        lowered = field.name.lower()
        if field.type == FieldDescriptor.TYPE_STRING and not field.is_repeated:
            string_fields.append(field)
            if lowered in _NAME_FIELDS and (name_field is None or lowered == "action_name"):
                name_field = field
        if lowered in _HOLD_FIELDS and field.type in _INTS and not field.is_repeated:
            hold_field = field
    if name_field is None and len(string_fields) == 1:
        name_field = string_fields[0]
    if name_field is None:
        raise Unsupported("TriggerGameAction has no action name field in this schema.")
    setattr(message, name_field.name, action_name)
    if hold_field is not None and hold_ms:
        setattr(message, hold_field.name, int(hold_ms))
    return message


def lowered_bool(field, value) -> bool:
    if field.name.lower() in {"available", "enabled"}:
        return True
    return bool(field.has_presence or value)


def _action_from_submessage(message) -> dict | None:
    strings = {}
    bools = {}
    for field in message.DESCRIPTOR.fields:
        if field.is_repeated or field.message_type:
            continue
        value = getattr(message, field.name)
        if field.type == FieldDescriptor.TYPE_STRING and value:
            strings[field.name.lower()] = value
        elif field.type == FieldDescriptor.TYPE_BOOL and lowered_bool(field, value):
            bools[field.name.lower()] = bool(value)
    name = ""
    for key in _NAME_FIELDS:
        if strings.get(key):
            name = strings[key]
            break
    if not name and len(strings) == 1:
        name = next(iter(strings.values()))
    if not name:
        return None
    category = strings.get("category") or strings.get("group") or ""
    label = strings.get("label") or strings.get("display_name") or prettify_action(name)
    available = True
    if "available" in bools:
        available = bools["available"]
    elif "enabled" in bools:
        available = bools["enabled"]
    return {
        "name": name,
        "label": label[:80],
        "group": classify_action(name, category),
        "dangerous": is_dangerous(name) or is_dangerous(label),
        "available": available,
    }


def actions_from_message(message) -> list[dict]:
    found: list[dict] = []

    def walk(current) -> None:
        for field in current.DESCRIPTOR.fields:
            value = getattr(current, field.name)
            if field.is_repeated and field.type == FieldDescriptor.TYPE_STRING:
                for item in value:
                    if item:
                        found.append(
                            {
                                "name": item,
                                "label": prettify_action(item),
                                "group": classify_action(item),
                                "dangerous": is_dangerous(item),
                                "available": True,
                            }
                        )
            elif field.is_repeated and field.message_type:
                for sub in value:
                    action = _action_from_submessage(sub)
                    if action:
                        found.append(action)
            elif field.message_type and not field.is_repeated and current.HasField(field.name):
                walk(value)

    walk(message)
    deduped = []
    seen = set()
    for action in found:
        if action["name"] in seen:
            continue
        seen.add(action["name"])
        deduped.append(action)
    return deduped


def interpret_trigger_response(message) -> tuple[bool, str]:
    accepted = None
    detail = ""
    for field in message.DESCRIPTOR.fields:
        if field.is_repeated or field.message_type:
            continue
        value = getattr(message, field.name)
        lowered = field.name.lower()
        if field.type == FieldDescriptor.TYPE_BOOL and lowered in {"accepted", "success", "ok"}:
            if field.has_presence and not message.HasField(field.name):
                continue
            accepted = bool(value)
        elif field.type == FieldDescriptor.TYPE_STRING and lowered in {"message", "detail", "reason", "error"} and value:
            detail = str(value)[:200]
    if accepted is None:
        return True, detail or "sent"
    return accepted, detail or ("accepted" if accepted else "rejected by the game")


def friendly_rpc(exc: Exception) -> str:
    import grpc

    code = getattr(exc, "code", None)
    if callable(code):
        status = code()
        details = ""
        details_fn = getattr(exc, "details", None)
        if callable(details_fn):
            details = details_fn() or ""
        if status == grpc.StatusCode.UNAVAILABLE:
            return "Game telemetry port is closed."
        if status == grpc.StatusCode.UNIMPLEMENTED:
            return "This game build does not implement that call."
        label = status.name.replace("_", " ").lower()
        if details and len(details) < 160:
            return f"The game returned {label}: {details}"
        return f"The game returned {label}."
    text = str(exc).lower()
    if "parse" in text or "decode" in text or "truncat" in text:
        return "Could not decode a telemetry message with the loaded schema."
    return "Telemetry connection failed."
