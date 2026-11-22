import asyncio
from pathlib import Path

import pytest

from pitboard.hub import Hub
from pitboard.recording import SessionRecorder
from pitboard.schema_loader import load_synthetic
from pitboard.settings import load_settings


async def _wait_live(hub: Hub):
    for _ in range(50):
        snap = hub.snapshot()
        if snap["link"] == "live" and snap["character"]["metrics"]["health"]["raw"] is not None:
            return snap
        await asyncio.sleep(0.05)
    raise AssertionError(hub.detail)


@pytest.mark.asyncio
async def test_mock_stream_updates_ship_and_records(tmp_path: Path):
    settings = load_settings(tmp_path)
    settings.record = True
    recorder = SessionRecorder(tmp_path / "sessions")
    hub = Hub(
        settings=settings,
        schema=None,
        mock=True,
        lan_active=False,
        recorder=recorder,
        mock_fps=40,
    )
    await hub.start()
    try:
        snap = await _wait_live(hub)
        assert snap["mock"] is True
        assert snap["schema_source"] == "synthetic"
        assert snap["ship"]["name"] == "Cutter"
        assert snap["ship"]["manufacturer"] == "Drake"
        assert snap["character"]["posture"] == "seated"
        assert snap["ship"]["shields"]["faces"]["front"]["ratio"] is not None
        assert any(item["name"] == "v_lights_toggle" and not item["dangerous"] for item in snap["actions"])
        before = snap["ship"]["toggles"]["lights"]
        result = await hub.trigger("v_lights_toggle", loopback=True)
        assert result["ok"] is True
        flipped = before
        for _ in range(40):
            flipped = hub.snapshot()["ship"]["toggles"]["lights"]
            if flipped != before:
                break
            await asyncio.sleep(0.05)
        assert flipped != before
        with pytest.raises(Exception) as blocked:
            await hub.trigger("v_eject", loopback=True)
        assert getattr(blocked.value, "status", None) == 403
        settings.allow_dangerous_actions = True
        armed = await hub.arm("v_eject")
        ejected = await hub.trigger("v_eject", nonce=armed["nonce"], loopback=True)
        assert ejected["ok"] is True
        for _ in range(40):
            if hub.snapshot()["character"]["posture"] == "eva":
                break
            await asyncio.sleep(0.05)
        assert hub.snapshot()["character"]["posture"] == "eva"
        assert hub.snapshot()["ship"]["aboard"] is False
    finally:
        await hub.stop()
    log_files = list((tmp_path / "sessions").glob("*.jsonl"))
    assert log_files
    text = log_files[0].read_text(encoding="utf-8")
    assert '"kind":"frame"' in text or '"kind": "frame"' in text
    assert "access_token" not in text
    assert "v_lights_toggle" in text


@pytest.mark.asyncio
async def test_synthetic_schema_is_refused_for_the_real_port(tmp_path: Path):
    settings = load_settings(tmp_path)
    hub = Hub(
        settings=settings,
        schema=load_synthetic(),
        mock=False,
        lan_active=False,
        recorder=SessionRecorder(tmp_path / "sessions"),
    )
    await hub.start()
    try:
        for _ in range(20):
            if hub.link == "refused":
                break
            await asyncio.sleep(0.05)
        assert hub.link == "refused"
        assert "practice schema" in hub.detail.lower() or "not the game" in hub.detail.lower()
    finally:
        await hub.stop()
