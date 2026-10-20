"""Protocol-level tests for SSAPClient against the FakeTV simulator."""

from __future__ import annotations

import asyncio
import json
import socket

import pytest
from fake_tv import FakeTV

from agent_tv.client import PairingError, ServiceNotFound, SSAPClient, TVConnectionError


def _client(tv: FakeTV, key: str | None = None, **kw) -> SSAPClient:
    kw.setdefault("transport", "ws")
    return SSAPClient("127.0.0.1", key, port=tv.port, **kw)


async def test_first_pairing_shows_prompt_and_returns_key(fake_tv):
    prompts = []
    client = _client(fake_tv, on_prompt=lambda: prompts.append(1))
    key = await client.connect(pairing_timeout=5)
    assert key == "fake-key-1"
    assert prompts == [1]
    assert fake_tv.prompts_shown == 1
    assert client.hello["deviceModel"] == "FakeTV"
    assert client.prereg_system_info["modelName"] == "OLED65C3PUA"
    # handshake order: hello, pre-registration system info, register
    assert [m["type"] for m in fake_tv.received[:3]] == ["hello", "request", "register"]
    await client.close()


async def test_saved_key_skips_prompt(fake_tv):
    fake_tv.known_keys.add("saved")
    prompts = []
    client = _client(fake_tv, "saved", on_prompt=lambda: prompts.append(1))
    assert await client.connect(pairing_timeout=5) == "saved"
    assert prompts == []
    assert fake_tv.prompts_shown == 0
    reg = next(m for m in fake_tv.received if m["type"] == "register")
    assert reg["payload"]["client-key"] == "saved"
    assert reg["payload"]["pairingType"] == "PROMPT"
    await client.close()


async def test_signed_manifest_variant(fake_tv):
    client = _client(fake_tv, manifest="signed")
    await client.connect(pairing_timeout=5)
    reg = next(m for m in fake_tv.received if m["type"] == "register")
    assert reg["payload"]["manifest"]["signed"]["appId"] == "com.lge.test"
    assert reg["payload"]["manifest"]["signatures"][0]["signatureVersion"] == 1
    await client.close()


async def test_rejected_pairing_raises():
    tv = await FakeTV(accept_pairing=False).start()
    try:
        with pytest.raises(PairingError, match="403"):
            await _client(tv).connect(pairing_timeout=5)
    finally:
        await tv.stop()


async def test_pairing_timeout():
    tv = await FakeTV(pairing_delay=3).start()
    try:
        with pytest.raises(PairingError, match="Timed out"):
            await _client(tv).connect(pairing_timeout=0.8)
    finally:
        await tv.stop()


async def test_requests_and_errors(fake_tv):
    async with _client(fake_tv) as client:
        await client.request("ssap://audio/setVolume", {"volume": 17})
        res = await client.request("audio/getVolume")  # scheme optional
        assert res["volumeStatus"]["volume"] == 17
        with pytest.raises(ServiceNotFound):
            await client.request("ssap://does/notExist")
        # concurrent requests are matched by id
        results = await asyncio.gather(*(client.request("ssap://audio/getVolume") for _ in range(10)))
        assert all(r["volumeStatus"]["volume"] == 17 for r in results)


async def test_subscription_receives_updates(fake_tv):
    async with _client(fake_tv) as client:
        updates: list[int] = []
        got = asyncio.Event()

        def on_volume(payload):
            updates.append(payload["volumeStatus"]["volume"])
            got.set()

        sid, first = await client.subscribe("ssap://audio/getVolume", on_volume)
        assert first["subscribed"] is True
        await client.request("ssap://audio/setVolume", {"volume": 33})
        await asyncio.wait_for(got.wait(), 2)
        assert updates == [33]
        await client.unsubscribe(sid)


async def test_pointer_socket_buttons(fake_tv):
    async with _client(fake_tv) as client:
        await client.button("HOME")
        await client.move(10, -5)
        await client.click()
        await client.scroll(0, 3)
        for _ in range(50):
            if len(fake_tv.pointer_messages) == 4:
                break
            await asyncio.sleep(0.02)
    assert fake_tv.pointer_messages == [
        "type:button\nname:HOME\n\n",
        "type:move\ndx:10\ndy:-5\ndown:0\n\n",
        "type:click\n\n",
        "type:scroll\ndx:0\ndy:3\n\n",
    ]


async def test_luna_alert_trick(fake_tv):
    async with _client(fake_tv) as client:
        await client.luna("com.webos.settingsservice/setSystemSettings", {"category": "option", "settings": {"livePlus": "off"}})
    create = next(m for m in fake_tv.received if m.get("uri", "").endswith("createAlert"))
    assert create["payload"]["onclose"]["uri"] == "luna://com.webos.settingsservice/setSystemSettings"
    assert create["payload"]["buttons"][0]["onClick"] == "luna://com.webos.settingsservice/setSystemSettings"
    assert fake_tv.settings["option"]["livePlus"] == "off"


async def test_auto_transport_falls_back_to_plain_ws(fake_tv):
    client = SSAPClient("127.0.0.1", transport="auto", port=fake_tv.port, connect_timeout=2)
    await client.connect(pairing_timeout=5)
    assert client.url == f"ws://127.0.0.1:{fake_tv.port}"
    await client.close()


async def test_secure_websocket_with_self_signed_cert(server_tls):
    tv = await FakeTV(tls=server_tls).start()
    try:
        client = SSAPClient("127.0.0.1", transport="auto", port=tv.port)
        await client.connect(pairing_timeout=5)
        assert client.url.startswith("wss://")
        await client.button("ENTER")  # pointer socket over wss too
        await asyncio.sleep(0.1)
        assert tv.pointer_messages == ["type:button\nname:ENTER\n\n"]
        await client.close()
    finally:
        await tv.stop()


async def test_unreachable_tv_gives_clear_error():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listens here now
    client = SSAPClient("127.0.0.1", transport="auto", port=port, connect_timeout=1)
    with pytest.raises(TVConnectionError, match="Could not reach the TV"):
        await client.connect()


async def test_dropped_connection_fails_pending_requests(fake_tv):
    client = _client(fake_tv)
    await client.connect(pairing_timeout=5)
    await fake_tv.drop_connections()
    await asyncio.sleep(0.1)
    assert not client.connected
    with pytest.raises(TVConnectionError):
        await client.request("ssap://audio/getVolume")
    await client.close()


def test_messages_are_valid_json_shapes():
    from agent_tv.manifest import registration_message

    msg = registration_message("abc")
    assert json.loads(json.dumps(msg))["payload"]["client-key"] == "abc"
    assert "client-key" not in registration_message(None)["payload"]
