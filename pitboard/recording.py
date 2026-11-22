"""Optional JSONL session log. Off until the owner turns it on."""

from __future__ import annotations

import json
import time
from pathlib import Path


class SessionRecorder:
    name = "session-log"

    def __init__(self, directory: Path):
        self.directory = directory
        self.error = ""
        self.path: Path | None = None
        self._handle = None
        self._last = 0.0

    @property
    def enabled(self) -> bool:
        return self._handle is not None

    def set_enabled(self, enabled: bool) -> None:
        if enabled and self._handle is None:
            self._open()
        elif not enabled and self._handle is not None:
            self.close()

    def _open(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = self.directory / f"pitboard-{stamp}.jsonl"
        self._handle = self.path.open("a", encoding="utf-8")
        self.error = ""
        self._write({"kind": "start", "at": time.time()})

    def close(self) -> None:
        if self._handle is None:
            return
        self._write({"kind": "stop", "at": time.time()})
        try:
            self._handle.close()
        finally:
            self._handle = None

    def on_link(self, status: str, detail: str) -> None:
        self._write({"kind": "link", "at": time.time(), "status": status, "detail": detail})

    def on_frame(self, snapshot: dict) -> None:
        if self._handle is None:
            return
        now = time.monotonic()
        if now - self._last < 0.5:
            return
        self._last = now
        character = snapshot.get("character") or {}
        ship = snapshot.get("ship") or {}
        self._write(
            {
                "kind": "frame",
                "at": time.time(),
                "link": snapshot.get("link"),
                "posture": character.get("posture"),
                "metrics": {
                    key: (value or {}).get("raw")
                    for key, value in (character.get("metrics") or {}).items()
                },
                "ship": ship.get("name"),
                "speed": ((ship.get("metrics") or {}).get("speed") or {}).get("raw"),
                "hull": ((ship.get("metrics") or {}).get("hull") or {}).get("raw"),
                "shields": (ship.get("shields") or {}).get("average"),
                "toggles": ship.get("toggles"),
            }
        )

    def on_action(self, name: str, result: dict) -> None:
        self._write(
            {
                "kind": "action",
                "at": time.time(),
                "name": name,
                "ok": result.get("ok"),
                "message": result.get("message"),
            }
        )

    def _write(self, payload: dict) -> None:
        if self._handle is None:
            return
        try:
            self._handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
            self._handle.flush()
        except OSError as exc:
            self.error = "Session log stopped: disk write failed."
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None
            self.error = f"{self.error} ({exc.__class__.__name__})"
