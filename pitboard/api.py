"""Local HTTP and WebSocket API for the dashboard."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import socket
from contextlib import asynccontextmanager
from pathlib import Path

import segno
from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from pitboard.hub import Hub, HubError
from pitboard.netpolicy import host_header_allowed, is_loopback_peer, origin_matches_host
from pitboard.paths import web_dir
from pitboard.recording import SessionRecorder
from pitboard.schema_loader import SchemaError, load_schema
from pitboard.settings import Settings, load_settings, parse_loopback_target, parse_port
from pitboard.paths import extracted_desc_candidates

log = logging.getLogger("pitboard")
WS_AUTH_TIMEOUT = 3.0
CSP = (
    "default-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)
_TOKEN_RE = re.compile(r"(token=)[^&\s\"']+", re.I)


class TokenRedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _TOKEN_RE.sub(r"\1***", record.msg)
        if record.args:
            args = record.args if isinstance(record.args, tuple) else (record.args,)
            record.args = tuple(_TOKEN_RE.sub(r"\1***", item) if isinstance(item, str) else item for item in args)
        return True


def install_log_filters() -> None:
    redact = TokenRedactFilter()
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "pitboard"):
        logging.getLogger(name).addFilter(redact)


def tokens_match(presented: str, expected: str) -> bool:
    if not presented or not expected or len(presented) != len(expected):
        return False
    return secrets.compare_digest(presented, expected)


def guess_lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # TEST-NET-1. UDP connect selects a route and does not transmit.
        sock.connect(("192.0.2.1", 9))
        address = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    if address.startswith("127.") or address.startswith("169.254."):
        return None
    return address


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapped(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"content-security-policy", CSP.encode()),
                    ]
                )
                message = dict(message)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapped)


class HostGate:
    def __init__(self, app, bind_host: str, testing: bool):
        self.app = app
        self.bind_host = bind_host
        self.testing = testing

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers") or []}
            host = headers.get("host", "")
            lan_active = self.bind_host == "0.0.0.0"
            if not host_header_allowed(host, lan_active=lan_active, testing=self.testing):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                    }
                )
                await send({"type": "http.response.body", "body": b"Host is not allowed."})
                return
        await self.app(scope, receive, send)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("x-pitboard-token", "").strip()


def _loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return is_loopback_peer(host, testing=bool(request.app.state.testing))


def _check_origin(request: Request) -> None:
    if not origin_matches_host(request.headers.get("origin"), request.headers.get("host", "")):
        raise HTTPException(403, "Cross-origin request refused.")


def _require_token(request: Request) -> bool:
    _check_origin(request)
    settings: Settings = request.app.state.settings
    if not tokens_match(_bearer(request), settings.access_token):
        raise HTTPException(401, "Missing or wrong access token.")
    return _loopback(request)


def _require_loopback_token(request: Request) -> None:
    if not _require_token(request):
        raise HTTPException(403, "This can only be changed from the PC running Pitboard.")


def create_app(
    *,
    home: Path,
    mock: bool = False,
    schema_path: Path | None = None,
    discover_schema: bool = True,
    testing: bool = False,
    bind_host: str | None = None,
    port: int | None = None,
    grpc_target: str | None = None,
    mock_fps: float = 17.0,
) -> FastAPI:
    settings = load_settings(home)
    if port is not None:
        settings.port = parse_port(port)
        settings.save()
    if grpc_target is not None:
        settings.grpc_target = parse_loopback_target(grpc_target)
        settings.save()
    actual_bind = bind_host or settings.bind_host()
    schema = None
    schema_error = ""
    if not mock:
        chosen = schema_path
        if chosen is None and discover_schema:
            for candidate in extracted_desc_candidates(home):
                if candidate.is_file():
                    chosen = candidate
                    break
        if chosen is not None:
            try:
                schema = load_schema(chosen, source="extracted")
            except SchemaError as exc:
                schema_error = str(exc)
                log.error("%s", exc)
    recorder = SessionRecorder(home / "sessions")
    hub = Hub(
        settings=settings,
        schema=schema,
        mock=mock,
        lan_active=actual_bind == "0.0.0.0",
        recorder=recorder,
        mock_fps=mock_fps,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await hub.start()
        try:
            yield
        finally:
            await hub.stop()

    docs = None if actual_bind == "0.0.0.0" else "/api/docs"
    app = FastAPI(
        title="Pitboard",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=docs,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    app.state.hub = hub
    app.state.settings = settings
    app.state.testing = testing
    app.state.bind_host = actual_bind
    app.state.schema_error = schema_error

    pages = web_dir()

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/bootstrap")
    def bootstrap(request: Request):
        _check_origin(request)
        host = request.headers.get("host", "")
        if not _loopback(request) or not host_header_allowed(host, lan_active=False, testing=testing):
            raise HTTPException(403, "The access token is only issued to this PC.")
        return {"token": settings.access_token, "pilot": settings.pilot}

    @app.get("/api/whoami")
    def whoami(request: Request):
        loopback = _require_token(request)
        return {"local_control": loopback, "pilot": settings.pilot}

    @app.get("/api/state")
    def state(request: Request):
        _require_token(request)
        return hub.snapshot()

    @app.get("/api/share")
    def share(request: Request):
        _require_loopback_token(request)
        url = None
        address = None
        if hub.lan_active:
            address = guess_lan_ip()
            if address:
                url = f"http://{address}:{settings.port}/?token={settings.access_token}"
        return {
            "lan_active": hub.lan_active,
            "lan_enabled": settings.lan_enabled,
            "restart_required": settings.lan_enabled != hub.lan_active,
            "share_url": url,
            "lan_address": address,
            "allow_dangerous_actions": settings.allow_dangerous_actions,
            "record": settings.record,
            "record_error": recorder.error,
            "record_path": str(recorder.path) if recorder.path else None,
        }

    @app.get("/api/share/qr.svg")
    def share_qr(request: Request):
        _require_loopback_token(request)
        if not hub.lan_active:
            raise HTTPException(404, "LAN access is off.")
        address = guess_lan_ip()
        if not address:
            raise HTTPException(404, "No LAN address detected.")
        url = f"http://{address}:{settings.port}/?token={settings.access_token}"
        svg = segno.make(url, error="m").svg_inline(scale=4, dark="#e7eef6", light="#10151c")
        return Response(content=svg, media_type="image/svg+xml")

    @app.post("/api/settings")
    def update_settings(request: Request, patch: dict = Body(...)):
        _require_loopback_token(request)
        try:
            return hub.update_settings(patch)
        except HubError as exc:
            raise HTTPException(exc.status, exc.detail) from exc

    @app.post("/api/actions/arm")
    async def arm(request: Request, payload: dict = Body(...)):
        _require_loopback_token(request)
        name = payload.get("name") if isinstance(payload, dict) else None
        try:
            return await hub.arm(str(name or ""))
        except HubError as exc:
            raise HTTPException(exc.status, exc.detail) from exc

    @app.post("/api/actions/trigger")
    async def trigger(request: Request, payload: dict = Body(...)):
        loopback = _require_token(request)
        if not isinstance(payload, dict):
            raise HTTPException(400, "Expected a JSON object.")
        try:
            return await hub.trigger(
                str(payload.get("name") or ""),
                payload.get("hold_ms") or 0,
                payload.get("nonce"),
                loopback=loopback,
            )
        except HubError as exc:
            raise HTTPException(exc.status, exc.detail) from exc

    @app.get("/")
    def index():
        page = pages / "index.html"
        return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/favicon.svg")
    def favicon():
        return FileResponse(pages / "favicon.svg", media_type="image/svg+xml")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        host = websocket.headers.get("host", "")
        origin = websocket.headers.get("origin")
        lan_active = websocket.app.state.bind_host == "0.0.0.0"
        if not host_header_allowed(host, lan_active=lan_active, testing=testing) or not origin_matches_host(origin, host):
            await websocket.close(code=4403)
            return
        try:
            raw = await asyncio.wait_for(websocket.receive_json(), timeout=WS_AUTH_TIMEOUT)
        except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError):
            await websocket.close(code=4401)
            return
        token = raw.get("token") if isinstance(raw, dict) else None
        if not isinstance(token, str) or not tokens_match(token, settings.access_token):
            await websocket.close(code=4401)
            return
        queue = hub.subscribe()
        try:
            await websocket.send_json({"op": "hello", "snapshot": hub.snapshot()})
            while True:
                snapshot = await queue.get()
                await websocket.send_json({"op": "snapshot", "snapshot": snapshot})
        except WebSocketDisconnect:
            return
        finally:
            hub.unsubscribe(queue)

    if pages.is_dir():
        app.mount("/static", StaticFiles(directory=pages), name="static")

    app.add_middleware(SecurityHeaders)
    app.add_middleware(HostGate, bind_host=actual_bind, testing=testing)
    return app
