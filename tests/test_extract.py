import json
from pathlib import Path

from google.protobuf.descriptor_pb2 import FileDescriptorProto, FileDescriptorSet

from pitboard.proto_extract import (
    extract_descriptors,
    main,
    render_proto,
    slice_file_descriptor,
    write_descriptor_set,
)
from pitboard.paths import synthetic_desc_path


def _set() -> FileDescriptorSet:
    descriptor_set = FileDescriptorSet()
    descriptor_set.ParseFromString(synthetic_desc_path().read_bytes())
    return descriptor_set


def test_slice_stops_before_the_next_descriptor():
    descriptor_set = _set()
    first = descriptor_set.file[0].SerializeToString()
    blob = first + first
    sliced = slice_file_descriptor(blob, 0)
    assert sliced == first


def test_extracts_descriptor_from_padded_bytes(tmp_path: Path):
    descriptor_set = _set()
    blob = bytearray(b"\x00" * 40)
    blob += b"log line mentions sc.game.telemetry.v1 but is not a descriptor\n"
    blob += b"MZ" + b"\x11" * 20
    for file_desc in descriptor_set.file:
        blob += b"\x22\x33"
        blob += file_desc.SerializeToString()
        blob += b"\x0a trailing junk"
    blob += descriptor_set.file[0].SerializeToString()
    found = extract_descriptors(bytes(blob))
    assert {(item.name, item.package) for item in found} == {
        (item.name, item.package) for item in descriptor_set.file
    }
    by_name = {item.name: item.SerializeToString() for item in found}
    for file_desc in descriptor_set.file:
        assert by_name[file_desc.name] == file_desc.SerializeToString()


def test_dependency_file_is_recovered():
    dep = FileDescriptorProto(name="sc/common.proto", package="sc.common", syntax="proto3")
    enum = dep.enum_type.add(name="Stance")
    enum.value.add(name="ON_FOOT", number=0)
    enum.value.add(name="SEATED", number=1)
    main_file = FileDescriptorProto(
        name="sc/game/telemetry/v1/telemetry.proto",
        package="sc.game.telemetry.v1",
        syntax="proto3",
    )
    main_file.dependency.append("sc/common.proto")
    empty = main_file.message_type.add(name="Empty")
    assert empty.name == "Empty"
    service = main_file.service.add(name="GameTelemetryService")
    method = service.method.add(
        name="TelemetryStream",
        input_type=".sc.game.telemetry.v1.Empty",
        output_type=".sc.game.telemetry.v1.Empty",
    )
    method.server_streaming = True
    blob = b"pad" + dep.SerializeToString() + b"\x00gap" + main_file.SerializeToString() + b"tail"
    found = extract_descriptors(blob)
    names = {item.name for item in found}
    assert names == {"sc/common.proto", "sc/game/telemetry/v1/telemetry.proto"}


def test_write_stays_inside_the_output_directory(tmp_path: Path):
    descriptor_set = _set()
    manifest = write_descriptor_set(list(descriptor_set.file), tmp_path, source="test")
    assert (tmp_path / "telemetry.desc").is_file()
    assert (tmp_path / "manifest.json").is_file()
    text = (tmp_path / manifest["wrote"][0]).read_text(encoding="utf-8")
    assert "service GameTelemetryService" in text
    assert "rpc TelemetryStream(" in text
    assert "returns (stream " in text


def test_rendered_proto_compiles_again(tmp_path: Path):
    from grpc_tools import protoc

    descriptor_set = _set()
    rendered = render_proto(descriptor_set.file[0])
    proto_path = tmp_path / "round.proto"
    proto_path.write_text(rendered, encoding="utf-8")
    desc_out = tmp_path / "round.desc"
    code = protoc.main(
        [
            "protoc",
            f"-I{tmp_path}",
            f"--descriptor_set_out={desc_out}",
            "--include_imports",
            str(proto_path),
        ]
    )
    assert code == 0
    again = FileDescriptorSet()
    again.ParseFromString(desc_out.read_bytes())
    original = descriptor_set.file[0]
    rebuilt = again.file[0]

    def summary(file_desc: FileDescriptorProto) -> dict:
        messages = {}

        def walk(message, prefix: str) -> None:
            full = f"{prefix}.{message.name}" if prefix else message.name
            messages[full] = sorted((field.name, field.number, field.type) for field in message.field)
            for nested in message.nested_type:
                if not nested.options.map_entry:
                    walk(nested, full)

        for message in file_desc.message_type:
            walk(message, file_desc.package)
        services = {
            service.name: [
                (method.name, method.client_streaming, method.server_streaming)
                for method in service.method
            ]
            for service in file_desc.service
        }
        return {"package": file_desc.package, "messages": messages, "services": services}

    assert summary(rebuilt) == summary(original)


def test_cli_self_test():
    assert main(["--self-test"]) == 0


def test_cli_missing_exe(tmp_path: Path):
    assert main(["--exe", str(tmp_path / "missing.exe")]) == 1


def test_manifest_lists_trigger_rpc(tmp_path: Path):
    manifest = write_descriptor_set(list(_set().file), tmp_path)
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    methods = payload["files"][0]["services"][0]["methods"]
    names = {item["name"] for item in methods}
    assert names == {"TelemetryStream", "ListTriggerableActions", "TriggerGameAction"}
    stream = next(item for item in methods if item["name"] == "TelemetryStream")
    assert stream["server_streaming"] is True
    assert stream["client_streaming"] is False
