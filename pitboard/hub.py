"""Keeps the game link up and the dashboard snapshot current."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from collections import deque

import grpc

from pitboard.grpc_link import CHANNEL_OPTIONS, DynamicClient, Unsupported, friendly_rpc
from pitboard.messages import merge_sections, message_to_dict
from pitboard.normalize import extract_events, load_field_map, normalize
from pitboard.recording import SessionRecorder
from pitboard.safety import acceptable_action_name, is_dangerous
from pitboard.schema_loader import LoadedSchema
from pitboard.settings import Settings

log = logging.getLogger("pitboard")


class HubError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Hub:
    def __init__(
        self,
        *,
        settings: Settings,
        schema: LoadedSchema | None,
        mock: bool,
        lan_active: bool,
        recorder: SessionRecorder,
        field_map_path=None,
        mock_fps: float = 17.0,
    ):
        self.settings = settings
        self.schema = schema
        self.mock = mock
        self.lan_active = lan_active
        self.recorder = recorder
        self.extensions = [recorder]
        self.mock_fps = mock_fps
        self.field_map_path = field_map_path
        self.grpc_target = settings.grpc_target
        self.link = "idle"
        self.detail = ""
        self.raw: dict = {}
        self.events: deque = deque(maxlen=40)
        self.actions: list[dict] = []
        self.actions_supported = False
        self.actions_error = ""
        self.frame_count = 0
        self.fps = 0.0
        self.updated_at = None
        self._frame_times: deque = deque()
        self._subscribers: list[asyncio.Queue] = []
        self._dirty = False
        self._stopping = False
        self._channel = None
        self._client: DynamicClient | None = None
        self._mock = None
        self._task: asyncio.Task | None = None
        self._bcast: asyncio.Task | None = None
        self._nonces: dict[str, tuple[str, float]] = {}
        self._hits: deque = deque()

    async def start(self) -> None:
        if self.mock:
            from pitboard.mock_server import MockTelemetryServer

            self._mock = MockTelemetryServer(fps=self.mock_fps)
            port = await self._mock.start()
            self.grpc_target = f"127.0.0.1:{port}"
            self.schema = self._mock.schema
        if self.settings.record:
            self.recorder.set_enabled(True)
        self._task = asyncio.create_task(self.run(), name="pitboard-link")
        self._bcast = asyncio.create_task(self._broadcaster(), name="pitboard-broadcast")

    async def stop(self) -> None:
        self._stopping = True
        tasks = [task for task in (self._task, self._bcast) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._channel is not None:
            with contextlib.suppress(Exception):
                await self._channel.close()
        if self._mock is not None:
            await self._mock.stop()
        self.recorder.close()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        queue.put_nowait(self.snapshot())
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def snapshot(self) -> dict:
        field_map = load_field_map(self.field_map_path or _default_field_map(self.settings))
        body = normalize(self.raw, field_map=field_map, events=list(self.events))
        body.update(
            {
                "link": self.link,
                "detail": self.detail,
                "mock": self.mock,
                "schema_source": None if self.schema is None else self.schema.source,
                "schema_service": None if self.schema is None else self.schema.service_name,
                "schema_methods": [] if self.schema is None else self.schema.method_names(),
                "actions_supported": self.actions_supported,
                "actions_error": self.actions_error,
                "actions": list(self.actions),
                "pilot": self.settings.pilot,
                "fps": round(self.fps, 1),
                "frames": self.frame_count,
                "updated_at": self.updated_at,
                "grpc_target": self.grpc_target,
                "settings": {
                    "lan_enabled": self.settings.lan_enabled,
                    "lan_active": self.lan_active,
                    "allow_dangerous_actions": self.settings.allow_dangerous_actions,
                    "record": self.settings.record,
                    "restart_required": self.settings.lan_enabled != self.lan_active,
                    "record_error": self.recorder.error,
                    "record_path": str(self.recorder.path) if self.recorder.path else None,
                },
            }
        )
        return body

    async def run(self) -> None:
        try:
            await self._run()
        except asyncio.CancelledError:
            await self._set_link("offline", "Stopped.")
            raise

    async def _run(self) -> None:
        if self.schema is None:
            await self._set_link(
                "no_schema",
                "Extract the schema from your StarCitizen.exe, or start Pitboard with --mock.",
            )
            await self._sleep_forever()
            return
        if self.schema.source == "synthetic" and not self.mock:
            await self._set_link(
                "refused",
                "The practice schema is not the game's schema. Extract descriptors before connecting to the game.",
            )
            await self._sleep_forever()
            return
        delay = 0.4
        while not self._stopping:
            try:
                await self._session()
                delay = 0.4
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("telemetry session ended", exc_info=exc)
                message = friendly_rpc(exc)
                kind = "schema_mismatch" if "decode" in message.lower() or "schema" in message.lower() else "offline"
                await self._set_link(kind, message)
            if self._stopping:
                break
            if self.link == "live":
                await self._set_link("offline", self.detail or "The game closed the telemetry stream.")
            await asyncio.sleep(delay)
            delay = min(delay * 1.7, 3.0)

    async def _session(self) -> None:
        await self._set_link("connecting", f"Looking for the game on {self.grpc_target}.")
        channel = grpc.aio.insecure_channel(self.grpc_target, options=CHANNEL_OPTIONS)
        self._channel = channel
        refresh: asyncio.Task | None = None
        try:
            await asyncio.wait_for(channel.channel_ready(), timeout=2.0)
            client = DynamicClient(channel, self.schema)
            self._client = client
            self.actions_supported = client.has("ListTriggerableActions") and client.has("TriggerGameAction")
            if self.actions_supported:
                refresh = asyncio.create_task(self._refresh_actions(client), name="pitboard-actions")
            else:
                self.actions = []
                self.actions_error = "This game build streams telemetry only. Commands need a build that exposes them."
            await self._set_link("live", "Streaming.")
            async for frame in client.telemetry_frames():
                self._ingest(frame)
            await self._set_link("offline", "The game closed the telemetry stream.")
        except asyncio.TimeoutError:
            await self._set_link("offline", "Game telemetry port is closed.")
        finally:
            if refresh is not None:
                refresh.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await refresh
            self._client = None
            self._channel = None
            with contextlib.suppress(Exception):
                await channel.close()

    async def _refresh_actions(self, client: DynamicClient) -> None:
        while not self._stopping:
            try:
                self.actions = await client.list_actions()
                self.actions_supported = True
                self.actions_error = ""
                self._dirty = True
            except Unsupported as exc:
                self.actions_supported = False
                self.actions = []
                self.actions_error = str(exc)
                return
            except Exception as exc:
                message = friendly_rpc(exc)
                if "does not implement" in message:
                    self.actions_supported = False
                    self.actions = []
                    self.actions_error = "This game build streams telemetry only. Commands need a build that exposes them."
                    self._dirty = True
                    return
                self.actions_error = message
            await asyncio.sleep(5)

    def _ingest(self, frame) -> None:
        data = message_to_dict(frame)
        for event in extract_events(data):
            self.events.append(event)
        self.raw = merge_sections(self.raw, data)
        self.frame_count += 1
        now = time.monotonic()
        self._frame_times.append(now)
        while self._frame_times and now - self._frame_times[0] > 1:
            self._frame_times.popleft()
        self.fps = float(len(self._frame_times))
        self.updated_at = time.time()
        self._dirty = True

    async def _broadcaster(self) -> None:
        while not self._stopping:
            await asyncio.sleep(0.1)
            if not self._dirty:
                continue
            self._dirty = False
            snap = self.snapshot()
            self._publish(snap)
            for extension in self.extensions:
                try:
                    extension.on_frame(snap)
                except Exception:
                    log.exception("extension %s failed on a frame", getattr(extension, "name", "?"))

    async def _set_link(self, status: str, detail: str) -> None:
        changed = status != self.link or detail != self.detail
        self.link = status
        self.detail = detail
        if changed:
            log.info("%s — %s", status, detail)
            for extension in self.extensions:
                try:
                    extension.on_link(status, detail)
                except Exception:
                    log.exception("extension failed on link change")
        self._dirty = True
        self._publish(self.snapshot())

    def _publish(self, snap: dict) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(snap)

    async def _sleep_forever(self) -> None:
        while not self._stopping:
            await asyncio.sleep(3600)

    def _rate_limit(self) -> None:
        now = time.monotonic()
        while self._hits and now - self._hits[0] > 2:
            self._hits.popleft()
        if len(self._hits) >= 10:
            raise HubError(429, "Too many commands. Wait a moment.")
        self._hits.append(now)

    def _known(self, name: str) -> dict:
        if not acceptable_action_name(name):
            raise HubError(400, "That command name is not usable.")
        for action in self.actions:
            if action["name"] == name:
                return action
        raise HubError(404, "The game has not offered that command.")

    def _purge_nonces(self) -> None:
        now = time.monotonic()
        expired = [key for key, (_name, deadline) in self._nonces.items() if deadline < now]
        for key in expired:
            del self._nonces[key]

    async def arm(self, name: str) -> dict:
        self._rate_limit()
        action = self._known(name)
        if not action["dangerous"] and not is_dangerous(name):
            raise HubError(400, "That command is not hazardous. Send it directly.")
        if not self.settings.allow_dangerous_actions:
            raise HubError(403, "Hazardous commands are off. Enable them on this PC first.")
        self._purge_nonces()
        nonce = secrets.token_urlsafe(18)
        self._nonces[nonce] = (name, time.monotonic() + 3)
        return {"nonce": nonce, "expires_ms": 3000, "name": name}

    def _consume_nonce(self, name: str, nonce: str | None) -> bool:
        self._purge_nonces()
        if not nonce:
            return False
        stored = self._nonces.pop(nonce, None)
        if stored is None:
            return False
        stored_name, deadline = stored
        return stored_name == name and time.monotonic() <= deadline

    async def trigger(self, name: str, hold_ms: int = 0, nonce: str | None = None, *, loopback: bool) -> dict:
        self._rate_limit()
        action = self._known(name)
        dangerous = bool(action["dangerous"] or is_dangerous(name) or is_dangerous(action.get("label") or ""))
        if dangerous:
            if not loopback:
                raise HubError(403, "Hazardous commands can only be sent from this PC.")
            if not self.settings.allow_dangerous_actions:
                raise HubError(403, "Hazardous commands are off.")
            if not self._consume_nonce(name, nonce):
                raise HubError(403, "Hold the command to confirm it, then it will send.")
        if not action.get("available", True):
            raise HubError(409, "The game says that command is not available.")
        if self.link != "live" or self._client is None:
            raise HubError(409, "The game is not streaming right now.")
        if not self.actions_supported:
            raise HubError(409, "This game build does not accept commands.")
        try:
            hold = max(0, min(int(hold_ms or 0), 10_000))
        except (TypeError, ValueError):
            hold = 0
        try:
            accepted, message = await self._client.trigger(name, hold)
        except Exception as exc:
            raise HubError(502, friendly_rpc(exc)) from exc
        result = {"ok": bool(accepted), "message": message, "name": name}
        for extension in self.extensions:
            try:
                extension.on_action(name, result)
            except Exception:
                log.exception("extension failed on action")
        self._dirty = True
        result["snapshot"] = self.snapshot()
        return result

    def update_settings(self, patch: dict) -> dict:
        allowed = {"allow_dangerous_actions", "lan_enabled", "record", "regenerate_token"}
        unknown = set(patch) - allowed
        if unknown:
            raise HubError(400, "Unknown settings.")
        if "allow_dangerous_actions" in patch:
            if not isinstance(patch["allow_dangerous_actions"], bool):
                raise HubError(400, "allow_dangerous_actions must be true or false.")
            self.settings.allow_dangerous_actions = patch["allow_dangerous_actions"]
        if "lan_enabled" in patch:
            if not isinstance(patch["lan_enabled"], bool):
                raise HubError(400, "lan_enabled must be true or false.")
            self.settings.lan_enabled = patch["lan_enabled"]
        if "record" in patch:
            if not isinstance(patch["record"], bool):
                raise HubError(400, "record must be true or false.")
            self.settings.record = patch["record"]
            self.recorder.set_enabled(self.settings.record)
        regenerated = False
        if patch.get("regenerate_token") is True:
            self.settings.access_token = secrets.token_urlsafe(32)
            regenerated = True
        elif patch.get("regenerate_token") not in (None, False):
            raise HubError(400, "regenerate_token must be true.")
        self.settings.save()
        self._dirty = True
        view = self.snapshot()["settings"]
        if regenerated:
            view = dict(view)
            view["access_token"] = self.settings.access_token
        return view


def _default_field_map(settings: Settings):
    if settings.path is None:
        return None
    return settings.path.parent / "field_map.json"
