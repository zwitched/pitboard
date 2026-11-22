"""Load a FileDescriptorSet and find GameTelemetryService."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from google.protobuf.descriptor import FileDescriptor, MethodDescriptor, ServiceDescriptor
from google.protobuf.descriptor_pb2 import FileDescriptorProto, FileDescriptorSet
from google.protobuf.descriptor_pool import DescriptorPool
from google.protobuf.message_factory import GetMessageClass

from pitboard.paths import synthetic_desc_path

SERVICE_NAME = "sc.game.telemetry.v1.GameTelemetryService"
_WELL_KNOWN = None


class SchemaError(RuntimeError):
    pass


def _well_known() -> dict[str, bytes]:
    global _WELL_KNOWN
    if _WELL_KNOWN is not None:
        return _WELL_KNOWN
    modules = {}
    try:
        from google.protobuf import any_pb2, duration_pb2, empty_pb2, struct_pb2, timestamp_pb2, wrappers_pb2
    except ImportError:  # pragma: no cover
        _WELL_KNOWN = {}
        return _WELL_KNOWN
    for module, filename in (
        (timestamp_pb2, "google/protobuf/timestamp.proto"),
        (duration_pb2, "google/protobuf/duration.proto"),
        (any_pb2, "google/protobuf/any.proto"),
        (empty_pb2, "google/protobuf/empty.proto"),
        (struct_pb2, "google/protobuf/struct.proto"),
        (wrappers_pb2, "google/protobuf/wrappers.proto"),
    ):
        modules[filename] = module.DESCRIPTOR.serialized_pb
    _WELL_KNOWN = modules
    return modules


@dataclass
class LoadedSchema:
    path: Path
    source: str
    pool: DescriptorPool
    files: list[FileDescriptorProto]
    service_name: str
    service: ServiceDescriptor
    methods: dict[str, MethodDescriptor] = field(default_factory=dict)

    def request_class(self, method: str):
        return GetMessageClass(self.methods[method].input_type)

    def response_class(self, method: str):
        return GetMessageClass(self.methods[method].output_type)

    def method_names(self) -> list[str]:
        return list(self.methods)


def _add_file(pool: DescriptorPool, message: FileDescriptorProto, added: set[str]) -> None:
    if message.name in added:
        return
    pool.Add(message)
    added.add(message.name)


def _load_pool(files: list[FileDescriptorProto]) -> DescriptorPool:
    pool = DescriptorPool()
    by_name = {item.name: item for item in files}
    added: set[str] = set()
    well_known = _well_known()

    def visit(message: FileDescriptorProto) -> None:
        if message.name in added:
            return
        for dependency in message.dependency:
            if dependency in by_name:
                visit(by_name[dependency])
            elif dependency in well_known and dependency not in added:
                pool.AddSerializedFile(well_known[dependency])
                added.add(dependency)
            elif dependency not in well_known and dependency not in by_name:
                raise SchemaError(
                    f"Schema is missing imported file {dependency}. Run the extractor again on StarCitizen.exe."
                )
        _add_file(pool, message, added)

    for message in files:
        visit(message)
    return pool


def _find_service(pool: DescriptorPool, files: list[FileDescriptor]) -> ServiceDescriptor:
    found: list[ServiceDescriptor] = []
    for file_desc in files:
        for service in file_desc.services_by_name.values():
            found.append(service)
    for service in found:
        if service.full_name == SERVICE_NAME:
            return service
    for service in found:
        if service.full_name.endswith("GameTelemetryService"):
            return service
    names = ", ".join(service.full_name for service in found) or "none"
    raise SchemaError(f"GameTelemetryService is not in this schema (found: {names}).")


def load_schema(path: Path, *, source: str) -> LoadedSchema:
    path = path.resolve()
    if not path.is_file():
        raise SchemaError(f"Schema file not found: {path}")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise SchemaError("Schema file is unexpectedly large.")
    descriptor_set = FileDescriptorSet()
    try:
        descriptor_set.ParseFromString(path.read_bytes())
    except Exception as exc:
        raise SchemaError(f"Could not read a descriptor set from {path.name}.") from exc
    if not descriptor_set.file:
        raise SchemaError(f"{path.name} does not contain any protobuf files.")
    files = list(descriptor_set.file)
    pool = _load_pool(files)
    file_descs = []
    for item in files:
        file_descs.append(pool.FindFileByName(item.name))
    service = _find_service(pool, file_descs)
    methods = {method.name: method for method in service.methods}
    if "TelemetryStream" not in methods:
        raise SchemaError("This schema has GameTelemetryService but no TelemetryStream method.")
    return LoadedSchema(
        path=path,
        source=source,
        pool=pool,
        files=files,
        service_name=service.full_name,
        service=service,
        methods=methods,
    )


def load_synthetic() -> LoadedSchema:
    return load_schema(synthetic_desc_path(), source="synthetic")
