"""A small SSAP simulator that behaves like an LG webOS TV.

It is only for tests: it lets us exercise pairing, requests, errors,
subscriptions, the pointer socket and the luna alert trick without a TV.
Response shapes mirror what real webOS 6-25 firmware sends.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import ssl
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

PUBLIC_SETTABLE = {"general": {"homeAutoLaunch", "homePromotion"}}


class FakeTV:
    def __init__(
        self,
        *,
        accept_pairing: bool = True,
        pairing_delay: float = 0.1,
        known_keys: set[str] | None = None,
        tls: ssl.SSLContext | None = None,
    ) -> None:
        self.accept_pairing = accept_pairing
        self.pairing_delay = pairing_delay
        self.known_keys = set(known_keys or ())
        self.tls = tls
        self.port = 0
        self.received: list[dict[str, Any]] = []
        self.pointer_messages: list[str] = []
        self.launched: list[dict[str, Any]] = []
        self.toasts: list[str] = []
        self.luna_calls: list[dict[str, Any]] = []
        self.switched_inputs: list[str] = []
        self.prompts_shown = 0
        self.volume = 10
        self.muted = False
        self.app = "com.webos.app.home"
        self.settings: dict[str, dict[str, Any]] = {
            "general": {"homeAutoLaunch": "on", "homePromotion": "on", "screenSaverAd": "on"},
            "option": {"livePlus": "on", "quickStartMode": "off"},
            "picture": {"pictureMode": "vivid", "backlight": 80},
        }
        self._keys = itertools.count(1)
        self._alerts: dict[str, dict[str, Any]] = {}
        self._subs: list[tuple[ServerConnection, str, str]] = []
        self._conns: set[ServerConnection] = set()
        self._server = None

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> "FakeTV":
        self._server = await serve(self._handler, "127.0.0.1", 0, ssl=self.tls)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def drop_connections(self) -> None:
        """Simulate the TV going to sleep / Wi-Fi blip."""
        for ws in list(self._conns):
            await ws.close()

    # ------------------------------------------------------------- handlers
    async def _handler(self, ws: ServerConnection) -> None:
        if ws.request.path.startswith("/resources/"):
            try:
                async for msg in ws:
                    self.pointer_messages.append(msg)
            except ConnectionClosed:
                pass
            return
        self._conns.add(ws)
        registered = False
        try:
            async for raw in ws:
                msg = json.loads(raw)
                self.received.append(msg)
                kind, mid = msg.get("type"), msg.get("id")
                if kind == "hello":
                    await self._send(ws, {"type": "hello", "id": mid, "payload": {"deviceModel": "FakeTV", "deviceOSVersion": "10.2.0"}})
                elif kind == "register":
                    registered = await self._register(ws, mid, msg.get("payload") or {})
                elif kind in ("request", "subscribe"):
                    uri = msg.get("uri", "")
                    if not registered and not uri.endswith("system/getSystemInfo"):
                        await self._send(ws, {"type": "error", "id": mid, "error": "401 insufficient permissions", "payload": {}})
                        continue
                    if uri == "ssap://system/turnOff":
                        await ws.close()
                        return
                    reply = await self._handle(uri, msg.get("payload") or {})
                    if kind == "subscribe" and reply.get("type") == "response":
                        reply["payload"]["subscribed"] = True
                        self._subs.append((ws, mid, uri))
                    reply["id"] = mid
                    await self._send(ws, reply)
                elif kind == "unsubscribe":
                    self._subs = [s for s in self._subs if s[1] != mid]
        except ConnectionClosed:
            pass
        finally:
            self._conns.discard(ws)
            self._subs = [s for s in self._subs if s[0] is not ws]

    async def _register(self, ws: ServerConnection, mid: str, payload: dict[str, Any]) -> bool:
        key = payload.get("client-key")
        if key and key in self.known_keys:
            await self._send(ws, {"type": "response", "id": mid, "payload": {"pairingType": "PROMPT", "returnValue": True}})
            await self._send(ws, {"type": "registered", "id": mid, "payload": {"client-key": key}})
            return True
        self.prompts_shown += 1
        await self._send(ws, {"type": "response", "id": mid, "payload": {"pairingType": "PROMPT", "returnValue": True}})
        await asyncio.sleep(self.pairing_delay)
        if not self.accept_pairing:
            await self._send(ws, {"type": "error", "id": mid, "error": "403 User denied access", "payload": {}})
            return False
        new_key = f"fake-key-{next(self._keys)}"
        self.known_keys.add(new_key)
        await self._send(ws, {"type": "registered", "id": mid, "payload": {"client-key": new_key}})
        return True

    @staticmethod
    async def _send(ws: ServerConnection, msg: dict[str, Any]) -> None:
        await ws.send(json.dumps(msg))

    async def _notify(self, uri: str, payload: dict[str, Any]) -> None:
        for ws, sid, sub_uri in list(self._subs):
            if sub_uri == uri:
                try:
                    await self._send(ws, {"type": "response", "id": sid, "payload": payload})
                except ConnectionClosed:
                    pass

    def _volume_payload(self) -> dict[str, Any]:
        return {
            "returnValue": True,
            "volumeStatus": {"volume": self.volume, "muteStatus": self.muted, "soundOutput": "tv_speaker", "maxVolume": 100},
        }

    @staticmethod
    def ok(**payload: Any) -> dict[str, Any]:
        return {"type": "response", "payload": {"returnValue": True, **payload}}

    @staticmethod
    def err(error: str) -> dict[str, Any]:
        return {"type": "error", "error": error, "payload": {}}

    async def _handle(self, uri: str, p: dict[str, Any]) -> dict[str, Any]:
        name = uri.split("://", 1)[1]
        scheme = "wss" if self.tls else "ws"
        if name == "system/getSystemInfo":
            return self.ok(modelName="OLED65C3PUA", features={"3d": False})
        if name == "com.webos.service.update/getCurrentSWInformation":
            return self.ok(product_name="webOSTV 10.2", major_ver="33", minor_ver="21.81")
        if name == "com.webos.service.connectionmanager/getinfo":
            return self.ok(wiredInfo={"macAddress": "aa:bb:cc:dd:ee:01"}, wifiInfo={"macAddress": "aa:bb:cc:dd:ee:02"})
        if name == "com.webos.service.tvpower/power/getPowerState":
            return self.ok(state="Active")
        if name == "audio/getVolume":
            return {"type": "response", "payload": self._volume_payload()}
        if name == "audio/setVolume":
            self.volume = int(p["volume"])
            await self._notify("ssap://audio/getVolume", self._volume_payload())
            return self.ok()
        if name in ("audio/volumeUp", "audio/volumeDown"):
            self.volume += 1 if name.endswith("Up") else -1
            await self._notify("ssap://audio/getVolume", self._volume_payload())
            return self.ok()
        if name == "audio/setMute":
            self.muted = bool(p["mute"])
            return self.ok()
        if name == "com.webos.applicationManager/listLaunchPoints":
            return self.ok(
                launchPoints=[
                    {"id": "youtube.leanback.v4", "title": "YouTube"},
                    {"id": "netflix", "title": "Netflix"},
                    {"id": "com.disney.disneyplus-prod", "title": "Disney+"},
                    {"id": "spotify-beehive", "title": "Spotify - Music and Podcasts"},
                ]
            )
        if name == "system.launcher/launch":
            self.launched.append(p)
            self.app = p["id"]
            await self._notify("ssap://com.webos.applicationManager/getForegroundAppInfo", {"appId": self.app, "returnValue": True})
            return self.ok(id=p["id"], sessionId="session-1")
        if name == "system.launcher/open":
            self.launched.append({"id": "com.webos.app.browser", "target": p.get("target")})
            return self.ok(id="com.webos.app.browser")
        if name == "system.launcher/close":
            return self.ok()
        if name == "com.webos.applicationManager/getForegroundAppInfo":
            return self.ok(appId=self.app, windowId="")
        if name == "tv/getExternalInputList":
            return self.ok(
                devices=[
                    {"id": "HDMI_1", "label": "HDMI 1", "connected": False, "appId": "com.webos.app.hdmi1"},
                    {"id": "HDMI_2", "label": "PlayStation 5", "connected": True, "appId": "com.webos.app.hdmi2"},
                ]
            )
        if name == "tv/switchInput":
            self.switched_inputs.append(p["inputId"])
            return self.ok()
        if name == "system.notifications/createToast":
            self.toasts.append(p["message"])
            return self.ok(toastId="toast-1")
        if name == "system.notifications/createAlert":
            alert_id = f"alert-{len(self._alerts) + 1}"
            self._alerts[alert_id] = p
            return self.ok(alertId=alert_id)
        if name == "system.notifications/closeAlert":
            alert = self._alerts.pop(p.get("alertId"), None)
            if alert is None:
                return self.err("400 unknown alert")
            call = alert["onclose"]
            self.luna_calls.append(call)
            if call["uri"] == "luna://com.webos.settingsservice/setSystemSettings":
                params = call["params"]
                self.settings.setdefault(params["category"], {}).update(params["settings"])
            return self.ok()
        if name == "settings/getSystemSettings":
            cat = self.settings.get(p.get("category"), {})
            return self.ok(category=p.get("category"), settings={k: cat[k] for k in p.get("keys", []) if k in cat})
        if name == "settings/setSystemSettings":
            allowed = PUBLIC_SETTABLE.get(p.get("category"), set())
            if not set(p.get("settings", {})) <= allowed:
                return self.err("401 insufficient permissions")
            self.settings[p["category"]].update(p["settings"])
            return self.ok()
        if name == "com.webos.service.networkinput/getPointerInputSocket":
            return self.ok(socketPath=f"{scheme}://127.0.0.1:{self.port}/resources/abc123/netinput.pointer.sock")
        if name == "media.controls/play":
            return self.ok()
        if name == "com.webos.media/getForegroundAppInfo":
            return self.ok(foregroundAppInfo=[{"appId": self.app, "playState": "playing"}])
        return self.err("404 no such service or method")
