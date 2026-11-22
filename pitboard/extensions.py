"""Extension points.

A future Stream Deck plugin should implement TelemetryExtension and register
it when the app starts. It receives the same snapshot and action list the
dashboard uses. Session recording is the built-in extension.
"""

from __future__ import annotations

from typing import Protocol


class TelemetryExtension(Protocol):
    name: str

    def on_link(self, status: str, detail: str) -> None: ...

    def on_frame(self, snapshot: dict) -> None: ...

    def on_action(self, name: str, result: dict) -> None: ...
