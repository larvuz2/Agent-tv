"""High-level LGTV behaviour, config persistence and helpers."""

from __future__ import annotations

import asyncio
import os
import stat

import pytest

from agent_tv.apps import netflix_launch_payload, resolve_app, youtube_video_id
from agent_tv.config import Config
from agent_tv.tv import LGTV
from agent_tv.wol import magic_packet, normalize_mac


@pytest.fixture
async def tv(paired_config):
    t = LGTV.from_config()
    yield t
    await t.close()


async def test_pairing_persists_key_mac_and_model(tv, isolated_config):
    await tv.connect(pairing_timeout=5)
    await tv.learn_identity()
    cfg = Config.load()
    entry = cfg.tvs["living-room"]
    assert entry.client_key == "fake-key-1"
    assert entry.mac == ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"]
    assert entry.model == "OLED65C3PUA"
    mode = stat.S_IMODE(os.stat(cfg.path).st_mode)
    assert mode == 0o600


async def test_second_session_reuses_key(paired_config, fake_tv):
    first = LGTV.from_config()
    await first.connect(pairing_timeout=5)
    await first.close()
    second = LGTV.from_config()
    await second.ensure_connected()
    await second.close()
    assert fake_tv.prompts_shown == 1


async def test_status(tv):
    st = await tv.status()
    assert st["power"] == "Active"
    assert st["screen_on"] is True
    assert st["audio"]["volume"] == 10
    assert st["foreground_app"]["appId"] == "com.webos.app.home"
    assert st["media"][0]["playState"] == "playing"


async def test_launch_by_friendly_name(tv, fake_tv):
    res = await tv.launch("spotify")
    assert res["launched"] == "spotify-beehive"
    res = await tv.launch("Disney+")
    assert res["launched"] == "com.disney.disneyplus-prod"
    with pytest.raises(LookupError, match="Installed"):
        await tv.launch("definitely-not-an-app")


async def test_youtube_deep_link(tv, fake_tv):
    await tv.youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42", start_seconds=42)
    sent = fake_tv.launched[-1]
    assert sent["id"] == "youtube.leanback.v4"
    assert sent["contentId"] == "dQw4w9WgXcQ"
    assert sent["params"]["contentTarget"] == "https://www.youtube.com/tv?v=dQw4w9WgXcQ&t=42"


async def test_open_url_adds_scheme(tv, fake_tv):
    res = await tv.open_url("example.com")
    assert res["opened"] == "https://example.com"
    assert fake_tv.launched[-1]["target"] == "https://example.com"


async def test_switch_input_by_label(tv, fake_tv):
    assert (await tv.switch_input("PlayStation 5"))["input"] == "HDMI_2"
    assert (await tv.switch_input("hdmi 1"))["input"] == "HDMI_1"
    assert fake_tv.switched_inputs == ["HDMI_2", "HDMI_1"]


async def test_volume_and_mute(tv, fake_tv):
    await tv.set_volume(150)
    assert fake_tv.volume == 100  # clamped
    res = await tv.volume_step(False, 3)
    assert res["volume"] == 97
    await tv.set_mute(True)
    assert fake_tv.muted is True


async def test_settings_public_api_then_luna_fallback(tv, fake_tv):
    res = await tv.set_settings("general", {"homeAutoLaunch": "off"})
    assert res["method"] == "ssap" and res["verified"] == {"homeAutoLaunch": True}

    res = await tv.set_settings("option", {"livePlus": "off"})
    assert res["method"] == "luna"
    assert res["verified"] == {"livePlus": True}
    assert any("401" in e for e in res["errors"])


async def test_apply_tweak(tv, fake_tv):
    res = await tv.apply_tweak("no_screensaver_ads")
    assert res["verified"] == {"screenSaverAd": True}
    with pytest.raises(KeyError):
        await tv.apply_tweak("nope")


async def test_media_falls_back_to_remote_button(tv, fake_tv):
    assert (await tv.media("play")).get("via") is None
    res = await tv.media("rewind")  # fake TV has no media.controls/rewind
    assert res["via"] == "remote button"
    await asyncio.sleep(0.1)
    assert fake_tv.pointer_messages[-1] == "type:button\nname:REWIND\n\n"


async def test_button_aliases(tv, fake_tv):
    assert await tv.buttons(["ok", "vol+", "Back"], delay=0.01) == ["ENTER", "VOLUMEUP", "BACK"]


async def test_reconnects_after_drop(tv, fake_tv):
    await tv.status()
    await fake_tv.drop_connections()
    await asyncio.sleep(0.1)
    assert (await tv.audio())["volume"] == 10


async def test_toast(tv, fake_tv):
    await tv.toast("Dinner is ready")
    assert fake_tv.toasts == ["Dinner is ready"]


async def test_power_off_does_not_wait_for_reply(tv, fake_tv):
    res = await tv.power_off()
    assert res["ok"] is True


# ----------------------------------------------------------------- helpers
@pytest.mark.parametrize(
    "value",
    [
        "dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=abc",
        "youtube.com/shorts/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
    ],
)
def test_youtube_video_id(value):
    assert youtube_video_id(value) == "dQw4w9WgXcQ"


def test_youtube_video_id_rejects_garbage():
    with pytest.raises(ValueError):
        youtube_video_id("https://example.com/watch?v=nope")


def test_netflix_payload():
    assert netflix_launch_payload("https://www.netflix.com/title/80057281")["contentId"] == (
        "m=https://www.netflix.com/watch/80057281&source_type=4"
    )


def test_resolve_app_order():
    installed = [{"id": "netflix", "title": "Netflix"}, {"id": "cdp-30", "title": "Plex"}, {"id": "amazon", "title": "Prime Video"}]
    assert resolve_app("plex", installed) == "cdp-30"
    assert resolve_app("prime", installed) == "amazon"
    assert resolve_app("NETFLIX", installed) == "netflix"


def test_wol_packet():
    assert normalize_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"
    pkt = magic_packet("aa:bb:cc:dd:ee:ff")
    assert len(pkt) == 102 and pkt[:6] == b"\xff" * 6 and pkt[6:12] == bytes.fromhex("aabbccddeeff")


def test_config_resolution(monkeypatch, isolated_config):
    cfg = Config.load()
    with pytest.raises(KeyError, match="No TV configured"):
        cfg.resolve()
    monkeypatch.setenv("LGTV_HOST", "10.0.0.9")
    name, entry = cfg.resolve()
    assert (name, entry.host) == ("env", "10.0.0.9")
