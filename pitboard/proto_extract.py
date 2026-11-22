"""Find serialized FileDescriptorProto blobs for sc.game.telemetry.

Star Citizen does not offer gRPC reflection. The descriptors are embedded in
StarCitizen.exe. This scanner looks for a canonical protobuf encoding of a
file whose package is sc.game.telemetry*, checks that it parses, and writes a
descriptor set next to a reconstructed .proto. Nothing is fetched from the
network, and the output belongs in schema/extracted/, which is gitignored.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from google.protobuf.descriptor_pb2 import FileDescriptorProto, FileDescriptorSet

MARKER = b"sc.game.telemetry"
ALLOWED_FIELDS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15}
MAX_DESCRIPTOR = 8_000_000
_PACKAGE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*")
_FILENAME = re.compile(r"[A-Za-z0-9_./\\-]+\.proto")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_TYPE_NAMES = {
    1: "double",
    2: "float",
    3: "int64",
    4: "uint64",
    5: "int32",
    6: "fixed64",
    7: "fixed32",
    8: "bool",
    9: "string",
    12: "bytes",
    13: "uint32",
    15: "sfixed32",
    16: "sfixed64",
    17: "sint32",
    18: "sint64",
}
_EDITIONS = {
    998: "PROTO2",
    999: "PROTO3",
    1000: "2023",
    1001: "2024",
}


def _read_varint(buf, index: int, limit: int = 10):
    result = 0
    shift = 0
    start = index
    while index < len(buf) and index - start < limit:
        byte = buf[index]
        result |= (byte & 0x7F) << shift
        index += 1
        if not byte & 0x80:
            return result, index
        shift += 7
    return None


def _encode_varint(number: int) -> bytes:
    out = bytearray()
    while True:
        bits = number & 0x7F
        number >>= 7
        if number:
            out.append(bits | 0x80)
        else:
            out.append(bits)
            return bytes(out)


def _tag_before(buf, value_start: int, length: int, tag_byte: int) -> int | None:
    prefix = _encode_varint(length)
    at = value_start - len(prefix)
    if at < 1 or buf[at:value_start] != prefix or buf[at - 1] != tag_byte:
        return None
    return at - 1


def slice_file_descriptor(buf, start: int) -> bytes | None:
    """Cut one FileDescriptorProto assuming canonical field-number order.

    A following message starts again at field 1, which is smaller than the
    field we just finished, so concatenation does not get swallowed.
    """
    index = start
    end = min(len(buf), start + MAX_DESCRIPTOR)
    previous = 0
    if start < 0 or start >= len(buf):
        return None
    while index < end:
        parsed = _read_varint(buf, index)
        if not parsed:
            break
        tag, nxt = parsed
        field_number = tag >> 3
        wire = tag & 7
        if field_number < previous or field_number not in ALLOWED_FIELDS or wire not in (0, 1, 2, 5):
            break
        if wire == 0:
            got = _read_varint(buf, nxt)
            if not got:
                break
            _, index = got
        elif wire == 1:
            if nxt + 8 > end:
                break
            index = nxt + 8
        elif wire == 5:
            if nxt + 4 > end:
                break
            index = nxt + 4
        else:
            got = _read_varint(buf, nxt)
            if not got:
                break
            length, data_at = got
            if length < 0 or data_at + length > end:
                break
            index = data_at + length
        previous = field_number
        if index <= start:
            break
    if index <= start:
        return None
    return bytes(buf[start:index])


def _parse_blob(blob: bytes) -> FileDescriptorProto | None:
    message = FileDescriptorProto()
    try:
        consumed = message.ParseFromString(blob)
    except Exception:
        return None
    if consumed != len(blob):
        return None
    return message


def _structural_ok(message: FileDescriptorProto) -> bool:
    if not message.name.endswith(".proto"):
        return False
    if not _FILENAME.fullmatch(message.name):
        return False
    if message.package and not _PACKAGE.fullmatch(message.package):
        return False
    if not (message.message_type or message.service or message.enum_type):
        return False
    for service in message.service:
        if not _IDENT.fullmatch(service.name):
            return False
        for method in service.method:
            if not method.name or not method.input_type or not method.output_type:
                return False
            if not _IDENT.fullmatch(method.name):
                return False
    return True


def _is_telemetry_file(message: FileDescriptorProto) -> bool:
    if "sc.game.telemetry" in message.package:
        return True
    return any(service.name == "GameTelemetryService" for service in message.service)


def _try_marker(buf, marker_pos: int) -> FileDescriptorProto | None:
    base = len(MARKER)
    for extra in range(0, 48):
        length = base + extra
        end = marker_pos + length
        if end > len(buf):
            break
        raw = bytes(buf[marker_pos:end])
        try:
            package = raw.decode("ascii")
        except UnicodeDecodeError:
            continue
        if not _PACKAGE.fullmatch(package):
            continue
        package_tag = _tag_before(buf, marker_pos, length, 0x12)
        if package_tag is None or package_tag < 8:
            continue
        if bytes(buf[package_tag - 6 : package_tag]) != b".proto":
            continue
        for name_len in range(7, 181):
            name_start = package_tag - name_len
            if name_start < 1:
                continue
            name = bytes(buf[name_start:package_tag])
            try:
                name_text = name.decode("ascii")
            except UnicodeDecodeError:
                continue
            if not _FILENAME.fullmatch(name_text):
                continue
            name_tag = _tag_before(buf, name_start, name_len, 0x0A)
            if name_tag is None:
                continue
            blob = slice_file_descriptor(buf, name_tag)
            if not blob:
                continue
            message = _parse_blob(blob)
            if message is None:
                continue
            if message.name != name_text or message.package != package:
                continue
            if _structural_ok(message) and _is_telemetry_file(message):
                return message
    return None


def _find_by_filename(buf, filename: str) -> FileDescriptorProto | None:
    needle = filename.encode("ascii")
    start = 0
    while True:
        found = buf.find(needle, start)
        if found < 0:
            return None
        start = found + 1
        name_tag = _tag_before(buf, found, len(needle), 0x0A)
        if name_tag is None:
            continue
        blob = slice_file_descriptor(buf, name_tag)
        if not blob:
            continue
        message = _parse_blob(blob)
        if message is None or message.name != filename:
            continue
        if _structural_ok(message):
            return message


def extract_descriptors(buf) -> list[FileDescriptorProto]:
    found: dict[tuple[str, str], FileDescriptorProto] = {}
    start = 0
    while True:
        pos = buf.find(MARKER, start)
        if pos < 0:
            break
        start = pos + 1
        message = _try_marker(buf, pos)
        if message is None:
            continue
        key = (message.name, message.package)
        previous = found.get(key)
        if previous is None or message.ByteSize() > previous.ByteSize():
            found[key] = message

    queue = list(found.values())
    seen_deps: set[str] = set()
    while queue:
        message = queue.pop()
        for dependency in message.dependency:
            if dependency in seen_deps or dependency.startswith("google/protobuf/"):
                continue
            seen_deps.add(dependency)
            extra = _find_by_filename(buf, dependency)
            if extra is None:
                continue
            key = (extra.name, extra.package)
            if key not in found:
                found[key] = extra
                queue.append(extra)
    return list(found.values())


def _index_messages(file_desc: FileDescriptorProto) -> dict[str, object]:
    indexed = {}

    def walk(message, prefix: str) -> None:
        full = f"{prefix}.{message.name}" if prefix else message.name
        indexed[full] = message
        for nested in message.nested_type:
            walk(nested, full)

    for message in file_desc.message_type:
        walk(message, file_desc.package)
    return indexed


def _type_name(field, syntax: str) -> str:
    if field.type in (11, 14) and field.type_name:
        return field.type_name[1:] if field.type_name.startswith(".") else field.type_name
    return _TYPE_NAMES.get(field.type, "bytes")


def _label(field, syntax: str, is_map: bool) -> str:
    if is_map:
        return ""
    if field.label == 3:
        return "repeated "
    if getattr(field, "proto3_optional", False):
        return "optional "
    if syntax == "proto2" and field.label == 1:
        return "optional "
    if syntax == "proto2" and field.label == 2:
        return "required "
    return ""


def _emit_enum(enum, indent: str, lines: list[str]) -> None:
    lines.append(f"{indent}enum {enum.name} {{")
    for value in enum.value:
        lines.append(f"{indent}  {value.name} = {value.number};")
    lines.append(f"{indent}}}")
    lines.append("")


def _emit_message(message, indent: str, lines: list[str], messages: dict, syntax: str) -> None:
    lines.append(f"{indent}message {message.name} {{")
    inner = indent + "  "
    for enum in message.enum_type:
        _emit_enum(enum, inner, lines)
    synthetic = set()
    for field in message.field:
        if getattr(field, "proto3_optional", False) and field.HasField("oneof_index"):
            synthetic.add(field.oneof_index)
    emitted_oneofs: set[int] = set()
    nested_skip = set()
    for nested in message.nested_type:
        if nested.options.map_entry:
            nested_skip.add(nested.name)
            continue
        _emit_message(nested, inner, lines, messages, syntax)
    for field in message.field:
        if field.HasField("oneof_index") and field.oneof_index not in synthetic:
            if field.oneof_index in emitted_oneofs:
                continue
            emitted_oneofs.add(field.oneof_index)
            oneof = message.oneof_decl[field.oneof_index]
            lines.append(f"{inner}oneof {oneof.name} {{")
            for member in message.field:
                if member.HasField("oneof_index") and member.oneof_index == field.oneof_index:
                    _emit_field(member, inner + "  ", lines, messages, syntax)
            lines.append(f"{inner}}}")
            continue
        _emit_field(field, inner, lines, messages, syntax)
    lines.append(f"{indent}}}")
    lines.append("")


def _emit_field(field, indent: str, lines: list[str], messages: dict, syntax: str) -> None:
    type_key = field.type_name[1:] if field.type_name.startswith(".") else field.type_name
    entry = messages.get(type_key)
    is_map = bool(entry is not None and entry.options.map_entry)
    if is_map:
        key_field = next(item for item in entry.field if item.number == 1)
        value_field = next(item for item in entry.field if item.number == 2)
        key_type = _type_name(key_field, syntax)
        value_type = _type_name(value_field, syntax)
        lines.append(f"{indent}map<{key_type}, {value_type}> {field.name} = {field.number};")
        return
    prefix = _label(field, syntax, False)
    lines.append(f"{indent}{prefix}{_type_name(field, syntax)} {field.name} = {field.number};")


def render_proto(file_desc: FileDescriptorProto) -> str:
    syntax = file_desc.syntax or "proto2"
    messages = _index_messages(file_desc)
    lines = [
        "// Reconstructed locally by Pitboard from a FileDescriptorProto in your game files.",
        "// Pitboard loads telemetry.desc. This text is for you to read.",
        "// It came from your own install. Do not commit it.",
        f'syntax = "{syntax}";',
        "",
    ]
    if file_desc.edition:
        edition = _EDITIONS.get(file_desc.edition, str(file_desc.edition))
        lines.append(f'edition = "{edition}";')
        lines.append("")
    if file_desc.package:
        lines.append(f"package {file_desc.package};")
        lines.append("")
    public = set(file_desc.public_dependency)
    weak = set(file_desc.weak_dependency)
    for index, dependency in enumerate(file_desc.dependency):
        kind = "public " if index in public else "weak " if index in weak else ""
        lines.append(f'import {kind}"{dependency}";')
    if file_desc.dependency:
        lines.append("")
    for enum in file_desc.enum_type:
        _emit_enum(enum, "", lines)
    for message in file_desc.message_type:
        if message.options.map_entry:
            continue
        _emit_message(message, "", lines, messages, syntax)
    for service in file_desc.service:
        lines.append(f"service {service.name} {{")
        for method in service.method:
            request = method.input_type[1:] if method.input_type.startswith(".") else method.input_type
            response = method.output_type[1:] if method.output_type.startswith(".") else method.output_type
            req_stream = "stream " if method.client_streaming else ""
            res_stream = "stream " if method.server_streaming else ""
            lines.append(
                f"  rpc {method.name}({req_stream}{request}) returns ({res_stream}{response});"
            )
        lines.append("}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _safe_filename(message: FileDescriptorProto, used: set[str]) -> str:
    base = Path(message.name).name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.proto", base):
        base = "telemetry.proto"
    if base in used:
        prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", message.package or "file")
        base = f"{prefix}.{base}"
    used.add(base)
    return base


def _topo(messages: list[FileDescriptorProto]) -> list[FileDescriptorProto]:
    by_name = {message.name: message for message in messages}
    seen: set[str] = set()
    ordered: list[FileDescriptorProto] = []

    def visit(message: FileDescriptorProto) -> None:
        if message.name in seen:
            return
        seen.add(message.name)
        for dependency in message.dependency:
            if dependency in by_name:
                visit(by_name[dependency])
        ordered.append(message)

    for message in messages:
        visit(message)
    return ordered


def descriptor_manifest(messages: list[FileDescriptorProto], source: str | None = None) -> dict:
    files = []
    for message in _topo(messages):
        services = []
        for service in message.service:
            methods = []
            for method in service.method:
                methods.append(
                    {
                        "name": method.name,
                        "client_streaming": bool(method.client_streaming),
                        "server_streaming": bool(method.server_streaming),
                        "request": method.input_type,
                        "response": method.output_type,
                    }
                )
            services.append({"name": service.name, "full_name": f"{message.package}.{service.name}" if message.package else service.name, "methods": methods})
        files.append(
            {
                "name": message.name,
                "package": message.package,
                "messages": [item.name for item in message.message_type],
                "services": services,
            }
        )
    return {"source": source, "files": files}


def write_descriptor_set(messages: list[FileDescriptorProto], out_dir: Path, source: str | None = None) -> dict:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ordered = _topo(messages)
    descriptor_set = FileDescriptorSet()
    used: set[str] = set()
    written = []
    for message in ordered:
        descriptor_set.file.append(message)
        filename = _safe_filename(message, used)
        dest = (out_dir / filename).resolve()
        if dest.parent != out_dir:
            raise ValueError(f"Refusing to write outside {out_dir}")
        dest.write_text(render_proto(message), encoding="utf-8")
        written.append(filename)
    desc_path = out_dir / "telemetry.desc"
    desc_path.write_bytes(descriptor_set.SerializeToString())
    manifest = descriptor_manifest(ordered, source=source)
    manifest["wrote"] = written
    manifest["descriptor_set"] = "telemetry.desc"
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def scan_path(exe: Path) -> tuple[list[FileDescriptorProto], dict]:
    data = exe.read_bytes() if exe.stat().st_size < 64 * 1024 * 1024 else None
    notes = {
        "bytes": exe.stat().st_size,
        "mentions_service": False,
    }
    if data is None:
        import mmap

        with exe.open("rb") as handle:
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                notes["mentions_service"] = mapped.find(b"GameTelemetryService") >= 0
                return extract_descriptors(mapped), notes
    notes["mentions_service"] = b"GameTelemetryService" in data
    return extract_descriptors(data), notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract sc.game.telemetry protobuf descriptors from StarCitizen.exe."
    )
    parser.add_argument("--exe", help="Path to StarCitizen.exe (the channel's Bin64 executable).")
    parser.add_argument(
        "--out",
        default="schema/extracted",
        help="Folder for telemetry.desc and the reconstructed .proto files.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Embed the synthetic descriptor in junk bytes and extract it back.",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not args.exe:
        parser.print_help()
        print(
            "\nExample:\n"
            '  python tools/extract_proto.py --exe '
            '"C:\\Program Files\\Roberts Space Industries\\StarCitizen\\LIVE\\Bin64\\StarCitizen.exe"',
            file=sys.stderr,
        )
        return 2
    exe = Path(args.exe).expanduser()
    if not exe.is_file():
        print(f"No such file: {exe}", file=sys.stderr)
        return 1
    if exe.suffix.lower() != ".exe":
        print("Warning: this path does not end in .exe. Scanning it anyway.", file=sys.stderr)
    print(f"Scanning {exe} ({exe.stat().st_size} bytes)...")
    try:
        messages, notes = scan_path(exe)
    except OSError as exc:
        print(f"Could not read the file: {exc}", file=sys.stderr)
        return 1
    if not messages:
        print("No sc.game.telemetry FileDescriptorProto was found.", file=sys.stderr)
        if not notes["mentions_service"]:
            print(
                "This file does not contain the text GameTelemetryService. "
                "Use the game executable in the channel's Bin64 folder, not the RSI Launcher.",
                file=sys.stderr,
            )
        else:
            print(
                "The service name is in the file, but the serialized descriptor was not recognized. "
                "A game patch may have packed it differently.",
                file=sys.stderr,
            )
        return 2
    manifest = write_descriptor_set(messages, Path(args.out), source=str(exe))
    print(f"Wrote {Path(args.out).resolve() / 'telemetry.desc'}")
    for item in manifest["files"]:
        services = ", ".join(service["full_name"] for service in item["services"]) or "(no service)"
        print(f"  {item['name']}  package {item['package']}  {services}")
        for service in item["services"]:
            for method in service["methods"]:
                kind = "stream" if method["server_streaming"] else "unary"
                print(f"    {method['name']} ({kind})")
    return 0


def _self_test() -> int:
    from pitboard.paths import synthetic_desc_path

    desc_path = synthetic_desc_path()
    if not desc_path.is_file():
        print(f"Missing {desc_path}. Compile the synthetic proto first.", file=sys.stderr)
        return 1
    descriptor_set = FileDescriptorSet()
    descriptor_set.ParseFromString(desc_path.read_bytes())
    blob = bytearray()
    blob += b"\x00" * 32
    blob += b"<GameTelemetry> Local services server is running on 127.0.0.1:2942 sc.game.telemetry.v1\n"
    blob += b"MZ" + b"\x00" * 16
    for file_desc in descriptor_set.file:
        blob += b"\x11\x22 junk before"
        blob += file_desc.SerializeToString()
        blob += b"\x0a trailing"
    blob += descriptor_set.file[0].SerializeToString()
    found = extract_descriptors(bytes(blob))
    names = {(item.name, item.package) for item in found}
    expected = {(item.name, item.package) for item in descriptor_set.file}
    if names != expected:
        print(f"self-test failed: found {names}, expected {expected}", file=sys.stderr)
        return 1
    print("self-test passed: synthetic descriptors were recovered from padded bytes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
