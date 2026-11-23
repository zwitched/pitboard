import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from pitboard.api import create_app


def _app(home: Path, **kwargs):
    defaults = dict(home=home, discover_schema=False, testing=True, bind_host="127.0.0.1")
    defaults.update(kwargs)
    return create_app(**defaults)


def test_bootstrap_and_rejected_hosts(tmp_path: Path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        denied = client.get("/api/bootstrap", headers={"Host": "evil.example"})
        assert denied.status_code == 403
        token = client.get("/api/bootstrap").json()["token"]
        assert token
        page = client.get("/")
        assert page.status_code == 200
        assert "Pitboard" in page.text
        assert token not in page.text
        assert "Content-Security-Policy" in page.headers
        cross = client.get(
            "/api/state",
            headers={"Authorization": f"Bearer {token}", "Origin": "http://evil.example"},
        )
        assert cross.status_code == 403
        state = client.get("/api/state", headers={"Authorization": f"Bearer {token}"})
        assert state.status_code == 200
        assert state.json()["link"] == "no_schema"
        assert "access_token" not in state.text


def test_wrong_token_and_websocket(tmp_path: Path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        token = client.get("/api/bootstrap").json()["token"]
        assert client.get("/api/state", headers={"Authorization": "Bearer nope"}).status_code == 401
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"op": "auth", "token": token})
            hello = socket.receive_json()
            assert hello["op"] == "hello"
            assert hello["snapshot"]["pilot"] == "LighterBurrito"


def test_lan_peer_cannot_bootstrap_or_arm(tmp_path: Path):
    app = _app(tmp_path, mock=True, mock_fps=30)
    token = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app, client=("10.1.1.5", 4242)) as client:
        assert client.get("/api/bootstrap").status_code == 403
        deadline = time.time() + 5
        actions = []
        while time.time() < deadline:
            state = client.get("/api/state", headers=headers)
            assert state.status_code == 200
            body = state.json()
            actions = body["actions"]
            if body["link"] == "live" and actions:
                break
            time.sleep(0.05)
        assert any(item["name"] == "v_eject" and item["dangerous"] for item in actions)
        armed = client.post("/api/actions/arm", headers=headers, json={"name": "v_eject"})
        assert armed.status_code == 403
        triggered = client.post("/api/actions/trigger", headers=headers, json={"name": "v_eject", "nonce": "nope"})
        assert triggered.status_code == 403
        lights = client.post("/api/actions/trigger", headers=headers, json={"name": "v_lights"})
        assert lights.status_code == 200
        assert lights.json()["ok"] is True


def test_hold_to_confirm_and_settings_are_local_only(tmp_path: Path):
    app = _app(tmp_path, mock=True, mock_fps=30)
    with TestClient(app) as client:
        token = client.get("/api/bootstrap").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        deadline = time.time() + 5
        while time.time() < deadline:
            body = client.get("/api/state", headers=headers).json()
            if body["link"] == "live" and body["actions"]:
                break
            time.sleep(0.05)
        blocked = client.post("/api/actions/trigger", headers=headers, json={"name": "v_self_destruct"})
        assert blocked.status_code == 403
        settings = client.post("/api/settings", headers=headers, json={"allow_dangerous_actions": True})
        assert settings.status_code == 200
        assert settings.json()["allow_dangerous_actions"] is True
        still = client.post("/api/actions/trigger", headers=headers, json={"name": "v_self_destruct", "nonce": "short"})
        assert still.status_code == 403
        nonce = client.post("/api/actions/arm", headers=headers, json={"name": "v_self_destruct"}).json()["nonce"]
        sent = client.post(
            "/api/actions/trigger",
            headers=headers,
            json={"name": "v_self_destruct", "nonce": nonce},
        )
        assert sent.status_code == 200
        assert sent.json()["ok"] is True
        reused = client.post(
            "/api/actions/trigger",
            headers=headers,
            json={"name": "v_self_destruct", "nonce": nonce},
        )
        assert reused.status_code == 403


def test_settings_file_permissions_and_token_persistence(tmp_path: Path):
    app = _app(tmp_path)
    with TestClient(app):
        pass
    path = tmp_path / "settings.json"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["lan_enabled"] is False
    assert saved["allow_dangerous_actions"] is False
    assert "token" not in json.dumps({key: saved[key] for key in saved if key != "access_token"})
    assert len(saved["access_token"]) >= 24
