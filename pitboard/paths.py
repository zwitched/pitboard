"""Locations for settings, the extracted schema, and packaged files."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def repo_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def app_home() -> Path:
    override = os.environ.get("PITBOARD_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path.cwd() / "data"


def web_dir() -> Path:
    return repo_root() / "web"


def synthetic_desc_path() -> Path:
    return repo_root() / "schema" / "synthetic" / "telemetry.desc"


def synthetic_proto_path() -> Path:
    return repo_root() / "schema" / "synthetic" / "telemetry.proto"


def extracted_desc_candidates(home: Path | None = None) -> list[Path]:
    home = home or app_home()
    candidates: list[Path] = []
    env = os.environ.get("PITBOARD_SCHEMA")
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(home / "telemetry.desc")
    candidates.append(repo_root() / "schema" / "extracted" / "telemetry.desc")
    return candidates
