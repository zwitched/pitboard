"""Owner settings. The access token lives in a private file, never in git."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pitboard.paths import app_home

DEFAULT_PILOT = "LighterBurrito"
DEFAULT_PORT = 9477
DEFAULT_GRPC = "127.0.0.1:2942"
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class SettingsError(ValueError):
    pass


def parse_loopback_target(value: str) -> str:
    raw = value.strip()
    if raw.count(":") != 1:
        raise SettingsError("Game target must look like 127.0.0.1:2942")
    host, port_text = raw.rsplit(":", 1)
    host = host.strip().strip("[]")
    if host.lower() not in _LOOPBACK:
        raise SettingsError("The game target has to stay on this computer (127.0.0.1).")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise SettingsError("Game target port is not a number.") from exc
    if not 1 <= port <= 65535:
        raise SettingsError("Game target port is out of range.")
    return f"{host}:{port}"


def parse_port(value: int) -> int:
    if not isinstance(value, int) or not 1024 <= value <= 65535:
        raise SettingsError("Dashboard port must be between 1024 and 65535.")
    return value


@dataclass
class Settings:
    pilot: str = DEFAULT_PILOT
    lan_enabled: bool = False
    allow_dangerous_actions: bool = False
    access_token: str = ""
    port: int = DEFAULT_PORT
    grpc_target: str = DEFAULT_GRPC
    record: bool = False
    path: Path | None = None

    def bind_host(self) -> str:
        return "0.0.0.0" if self.lan_enabled else "127.0.0.1"

    def save(self) -> None:
        if self.path is None:
            raise SettingsError("Settings have no file path.")
        payload = {
            "pilot": self.pilot,
            "lan_enabled": self.lan_enabled,
            "allow_dangerous_actions": self.allow_dangerous_actions,
            "access_token": self.access_token,
            "port": self.port,
            "grpc_target": self.grpc_target,
            "record": self.record,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2) + "\n"
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp_name, 0o600)
            os.replace(tmp_name, self.path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


def _clean_pilot(value: object) -> str:
    if not isinstance(value, str):
        return DEFAULT_PILOT
    text = value.strip()
    if not text or len(text) > 32:
        return DEFAULT_PILOT
    return text


def _clean_token(value: object) -> str:
    if isinstance(value, str) and len(value) >= 24 and "\n" not in value and " " not in value:
        return value
    return secrets.token_urlsafe(32)


def load_settings(home: Path | None = None) -> Settings:
    folder = home or app_home()
    path = folder / "settings.json"
    settings = Settings(path=path, access_token=secrets.token_urlsafe(32))
    if not path.exists():
        settings.save()
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        settings.save()
        return settings
    if not isinstance(raw, dict):
        settings.save()
        return settings
    settings.pilot = _clean_pilot(raw.get("pilot", DEFAULT_PILOT))
    settings.lan_enabled = bool(raw.get("lan_enabled", False))
    settings.allow_dangerous_actions = bool(raw.get("allow_dangerous_actions", False))
    settings.access_token = _clean_token(raw.get("access_token"))
    try:
        settings.port = parse_port(int(raw.get("port", DEFAULT_PORT)))
    except (SettingsError, TypeError, ValueError):
        settings.port = DEFAULT_PORT
    try:
        settings.grpc_target = parse_loopback_target(str(raw.get("grpc_target", DEFAULT_GRPC)))
    except SettingsError:
        settings.grpc_target = DEFAULT_GRPC
    settings.record = bool(raw.get("record", False))
    settings.save()
    return settings
