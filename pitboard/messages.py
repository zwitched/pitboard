"""Protobuf message conversion that respects proto3's omitted zeros."""

from __future__ import annotations

from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.message_factory import GetMessageClass

_FLOAT = {FieldDescriptor.TYPE_FLOAT, FieldDescriptor.TYPE_DOUBLE}
_INT = {
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
_JS_MAX = 2**53 - 1
_MAX_DEPTH = 8


def _scalar(field: FieldDescriptor, value):
    if field.type == FieldDescriptor.TYPE_BOOL:
        return bool(value)
    if field.type == FieldDescriptor.TYPE_STRING:
        text = str(value)
        return text[:200]
    if field.type == FieldDescriptor.TYPE_BYTES:
        return bytes(value).hex()[:200]
    if field.type == FieldDescriptor.TYPE_ENUM:
        try:
            named = field.enum_type.values_by_number.get(int(value))
        except (TypeError, ValueError):
            return value
        return named.name if named is not None else int(value)
    if field.type in _FLOAT:
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return round(number, 4)
    if field.type in _INT:
        number = int(value)
        if abs(number) > _JS_MAX:
            return str(number)
        return number
    return value


def message_to_dict(message, *, fill_absent: bool = False, _depth: int = 0) -> dict:
    """Turn one present message into a dict.

    The top-level frame is converted with fill_absent=False, so a section the
    game did not send is left out and the previous section can stay. Inside a
    section that *was* sent, missing nested messages are filled with defaults:
    proto3 drops all-zero submessages, and those zeros are real readings.
    Proto3 optional fields that were not set stay absent so a deep merge can
    keep the last value.
    """
    if _depth > _MAX_DEPTH:
        return {}
    out: dict = {}
    for field in message.DESCRIPTOR.fields:
        is_map = bool(field.message_type and field.message_type.GetOptions().map_entry)
        if is_map:
            raw_map = getattr(message, field.name)
            value_field = field.message_type.fields_by_name["value"]
            if len(raw_map) == 0 and not fill_absent:
                continue
            converted = {}
            for key, item in raw_map.items():
                if value_field.message_type and not value_field.message_type.GetOptions().map_entry:
                    converted[str(key)] = message_to_dict(item, fill_absent=True, _depth=_depth + 1)
                else:
                    converted[str(key)] = _scalar(value_field, item)
            out[field.name] = converted
            continue
        if field.is_repeated:
            items = []
            for item in getattr(message, field.name):
                if field.message_type:
                    items.append(message_to_dict(item, fill_absent=True, _depth=_depth + 1))
                else:
                    items.append(_scalar(field, item))
            if items or fill_absent:
                out[field.name] = items
            continue
        if field.message_type:
            if message.HasField(field.name):
                out[field.name] = message_to_dict(
                    getattr(message, field.name), fill_absent=True, _depth=_depth + 1
                )
            elif fill_absent:
                empty = GetMessageClass(field.message_type)()
                out[field.name] = message_to_dict(empty, fill_absent=True, _depth=_depth + 1)
            continue
        if field.has_presence and not message.HasField(field.name):
            continue
        out[field.name] = _scalar(field, getattr(message, field.name))
    return out


def merge_sections(old: dict, new: dict) -> dict:
    """Keep sections the new frame omitted. Update values it actually sent."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return new
    merged = dict(old)
    for key, value in new.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = merge_sections(current, value)
        else:
            merged[key] = value
    return merged
