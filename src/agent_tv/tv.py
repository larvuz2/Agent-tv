"""High-level, friendly API on top of ``SSAPClient``.

``LGTV`` keeps one connection open, reconnects once if the TV dropped it, and
exposes plain-Python methods that return JSON-friendly values. The CLI and the
MCP server are thin layers over this class.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import urllib.request
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from . import endpoints as ep
from . import wol
from .apps import netflix_launch_payload, resolve_app, youtube_launch_payload, youtube_search_payload
from .buttons import BUTTONS, normalize
from .client import (
    PermissionDenied,
    ServiceNotFound,
    SSAPClient,
    SSAPError,
    TVConnectionError,
    TVError,
)
from .config import Config, TVEntry
from .tweaks import TWEAKS

log = logging.getLogger(__name__)
T = TypeVar("T")

OFF_STATES = {None, "Power Off", "Suspend", "Active Standby"}


class LGTV:
    def __init__(
        self,
        entry: TVEntry,
        *,
        name: str = "tv",
        config: Config | None = None,
        on_prompt: Callable[[], None] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.entry = entry
        self.name = name
        self.config = config
        self.on_prompt = on_prompt
        self.timeout = timeout
        self.client: SSAPClient | None = None
        self._lock = asyncio.Lock()
        self._apps_cache: list[dict[str, Any]] | None = None

    # ---------------------------------------------------------- construction
    @classmethod
    def from_config(cls, name: str | None = None, **kw: Any) -> "LGTV":
        cfg = Config.load()
        key, entry = cfg.resolve(name)
        return cls(entry, name=key, config=cfg, **kw)

    @property
    def host(self) -> str:
        return self.entry.host

    # ------------------------------------------------------------ connection
    async def connect(self, pairing_timeout: float = 60.0) -> str:
        async with self._lock:
            return await self._connect(pairing_timeout)

    async def _connect(self, pairing_timeout: float = 60.0) -> str:
        if self.client is not None:
            await self.client.close()
        self.client = SSAPClient(
            self.entry.host,
            self.entry.client_key,
            transport=self.entry.transport,
            port=self.entry.port,
            manifest=self.entry.manifest,
            timeout=self.timeout,
            on_prompt=self.on_prompt,
        )
        key = await self.client.connect(pairing_timeout)
        if key != self.entry.client_key:
            self.entry.client_key = key
            self._persist()
        return key

    def _persist(self) -> None:
        """Save a new client key / MAC / model back to the config file."""
        if self.config is None or self.name == "env":
            return
        stored = self.config.tvs.get(self.name)
        if stored is None:
            return
        stored.client_key = self.entry.client_key
        if self.entry.mac:
            stored.mac = self.entry.mac
        if self.entry.model:
            stored.model = self.entry.model
        self.config.save()

    async def ensure_connected(self) -> SSAPClient:
        async with self._lock:
            if self.client is None or not self.client.connected:
                await self._connect()
            assert self.client is not None
            return self.client

    async def close(self) -> None:
        async with self._lock:
            if self.client is not None:
                await self.client.close()
                self.client = None

    async def _with_retry(self, fn: Callable[[SSAPClient], Awaitable[T]]) -> T:
        client = await self.ensure_connected()
        try:
            return await fn(client)
        except TVConnectionError:
            log.info("connection dropped; reconnecting once")
            async with self._lock:
                await self._connect()
            assert self.client is not None
            return await fn(self.client)

    async def request(self, uri: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Raw SSAP request (escape hatch for anything not wrapped below)."""
        return await self._with_retry(lambda c: c.request(uri, payload))

    async def luna(self, uri: str, params: dict[str, Any]) -> dict[str, Any]:
        """Raw luna call via the alert trick (write-only: no result comes back)."""
        return await self._with_retry(lambda c: c.luna(uri, params))

    async def _try(self, uri: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        try:
            return await self.request(uri, payload)
        except SSAPError as exc:
            log.debug("%s failed: %s", uri, exc)
            return None

    # ------------------------------------------------------------------ info
    async def system_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"host": self.host}
        if self.client is None or not self.client.connected:
            await self.ensure_connected()
        assert self.client is not None
        info["hello"] = self.client.hello
        info["system"] = await self._try(ep.GET_SYSTEM_INFO) or self.client.prereg_system_info
        info["software"] = await self._try(ep.GET_SOFTWARE_INFO)
        info["network"] = await self._try(ep.GET_CONNECTION_INFO)
        info["connection_url"] = self.client.url
        return info

    async def learn_identity(self) -> dict[str, Any]:
        """Record model + MAC addresses (needed later for Wake-on-LAN)."""
        info = await self.system_info()
        macs: list[str] = []
        net = info.get("network") or {}
        for section in ("wiredInfo", "wifiInfo"):
            mac = (net.get(section) or {}).get("macAddress")
            if mac and mac not in macs:
                macs.append(mac)
        if macs:
            self.entry.mac = macs
        model = (info.get("system") or {}).get("modelName") or (info.get("hello") or {}).get("deviceModel")
        if model:
            self.entry.model = model
        self._persist()
        return {"model": self.entry.model, "mac": self.entry.mac, "software": info.get("software")}

    async def services(self) -> list[dict[str, Any]]:
        return (await self.request(ep.GET_SERVICE_LIST)).get("services", [])

    async def power_state(self) -> dict[str, Any]:
        res = await self._try(ep.GET_POWER_STATE)
        if res is None:
            return {"state": "Active", "note": "power-state API missing; TV answered so it is on"}
        return res

    async def foreground_app(self) -> dict[str, Any]:
        res = await self.request(ep.GET_FOREGROUND_APP)
        app_id = res.get("appId")
        title = None
        try:
            for app in await self.list_apps(cache=True):
                if app.get("id") == app_id:
                    title = app.get("title")
                    break
        except SSAPError:
            pass
        return {"appId": app_id, "title": title, "windowId": res.get("windowId")}

    async def status(self) -> dict[str, Any]:
        """One-shot summary: power, current app, volume, sound output, media state."""
        out: dict[str, Any] = {"tv": self.name, "host": self.host, "model": self.entry.model}
        out["power"] = (await self.power_state()).get("state")
        out["screen_on"] = out["power"] not in OFF_STATES and out["power"] != "Screen Off"
        try:
            out["foreground_app"] = await self.foreground_app()
        except SSAPError as exc:
            out["foreground_app"] = {"error": str(exc)}
        try:
            out["audio"] = await self.audio()
        except SSAPError as exc:
            out["audio"] = {"error": str(exc)}
        media = await self._try(ep.GET_MEDIA_FOREGROUND_APP)
        if media:
            out["media"] = media.get("foregroundAppInfo")
        return out

    # ------------------------------------------------------------------ power
    async def power_off(self) -> dict[str, Any]:
        state = (await self.power_state()).get("state")
        if state in OFF_STATES and state is not None:
            return {"ok": True, "note": f"TV already in '{state}'"}
        await self._with_retry(lambda c: c.send(ep.POWER_OFF))
        return {"ok": True, "note": "power-off sent (the TV may not answer while shutting down)"}

    async def screen(self, on: bool) -> dict[str, Any]:
        """Screen off keeps sound playing (great for music). On restores it."""
        primary = ep.TURN_ON_SCREEN if on else ep.TURN_OFF_SCREEN
        legacy = ep.TURN_ON_SCREEN_LEGACY if on else ep.TURN_OFF_SCREEN_LEGACY
        try:
            return await self.request(primary, {"standbyMode": "active"})
        except ServiceNotFound:
            return await self.request(legacy, {"standbyMode": "active"})

    def wake(self, mac: str | None = None) -> dict[str, Any]:
        """Wake-on-LAN. Works only if the TV allows it (see wol.py)."""
        macs = [mac] if mac else self.entry.mac
        targets = wol.wake(macs, host=self.host)
        return {"ok": True, "mac": macs, "sent_to": targets, "note": "TV takes ~5-15 s to come up"}

    async def wait_until_reachable(self, timeout: float = 30.0) -> bool:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            try:
                await self.ensure_connected()
                return True
            except TVError:
                await asyncio.sleep(2)
        return False

    async def reboot(self) -> dict[str, Any]:
        return await self.request(ep.REQUEST_REBOOT, {"reason": "remoteControl"})

    # ------------------------------------------------------------------ audio
    async def audio(self) -> dict[str, Any]:
        vol = await self.request(ep.GET_VOLUME)
        status = vol.get("volumeStatus", vol)
        out = {
            "volume": status.get("volume"),
            "muted": status.get("muteStatus", status.get("mute")),
            "max": status.get("maxVolume"),
            "sound_output": status.get("soundOutput"),
        }
        if out["sound_output"] is None:
            so = await self._try(ep.GET_SOUND_OUTPUT)
            out["sound_output"] = (so or {}).get("soundOutput")
        return out

    async def set_volume(self, level: int) -> dict[str, Any]:
        level = max(0, min(100, int(level)))
        await self.request(ep.SET_VOLUME, {"volume": level})
        return {"volume": level}

    async def volume_step(self, up: bool, steps: int = 1) -> dict[str, Any]:
        for _ in range(max(1, min(steps, 50))):
            await self.request(ep.VOLUME_UP if up else ep.VOLUME_DOWN)
            await asyncio.sleep(0.15)
        return await self.audio()

    async def set_mute(self, muted: bool) -> dict[str, Any]:
        await self.request(ep.SET_MUTE, {"mute": bool(muted)})
        return {"muted": bool(muted)}

    async def set_sound_output(self, output: str) -> dict[str, Any]:
        """e.g. tv_speaker, external_arc, external_optical, bt_soundbar, headphone."""
        return await self.request(ep.CHANGE_SOUND_OUTPUT, {"output": output})

    # ------------------------------------------------------------------- apps
    async def list_apps(self, include_hidden: bool = False, cache: bool = False) -> list[dict[str, Any]]:
        if include_hidden:
            res = await self.request(ep.LIST_APPS)
            return [
                {"id": a.get("id"), "title": a.get("title"), "visible": a.get("visible"), "version": a.get("version")}
                for a in res.get("apps", [])
            ]
        if cache and self._apps_cache is not None:
            return self._apps_cache
        res = await self.request(ep.LIST_LAUNCH_POINTS)
        apps = [{"id": a.get("id"), "title": a.get("title")} for a in res.get("launchPoints", [])]
        self._apps_cache = apps
        return apps

    async def resolve_app(self, name: str) -> str:
        try:
            installed = await self.list_apps(cache=True)
        except SSAPError:
            installed = []
        try:
            return resolve_app(name, installed)
        except LookupError:
            self._apps_cache = None  # maybe newly installed; refresh once
            return resolve_app(name, await self.list_apps())

    async def launch(
        self,
        app: str,
        content_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        app_id = await self.resolve_app(app)
        payload: dict[str, Any] = {"id": app_id}
        if content_id:
            payload["contentId"] = content_id
        if params:
            payload["params"] = params
        res = await self.request(ep.LAUNCH, payload)
        return {"launched": app_id, "sessionId": res.get("sessionId")}

    async def close_app(self, app: str) -> dict[str, Any]:
        app_id = await self.resolve_app(app)
        await self.request(ep.CLOSE_APP, {"id": app_id})
        return {"closed": app_id}

    async def youtube(self, video: str, start_seconds: int | None = None) -> dict[str, Any]:
        payload = youtube_launch_payload(video, start_seconds)
        await self.request(ep.LAUNCH, payload)
        return {"launched": payload["id"], "video": payload["contentId"], "target": payload["params"]["contentTarget"]}

    async def youtube_search(self, query: str) -> dict[str, Any]:
        payload = youtube_search_payload(query)
        await self.request(ep.LAUNCH, payload)
        return {"launched": payload["id"], "target": payload["params"]["contentTarget"], "note": "best effort"}

    async def netflix(self, title: str) -> dict[str, Any]:
        payload = netflix_launch_payload(title)
        await self.request(ep.LAUNCH, payload)
        return {"launched": "netflix", "contentId": payload["contentId"]}

    async def open_url(self, url: str) -> dict[str, Any]:
        if "://" not in url:
            url = f"https://{url}"
        res = await self.request(ep.OPEN_URL, {"target": url})
        return {"opened": url, "app": res.get("id")}

    # ---------------------------------------------------------------- inputs
    async def list_inputs(self) -> list[dict[str, Any]]:
        res = await self.request(ep.GET_INPUTS)
        return [
            {
                "id": d.get("id"),
                "label": d.get("label"),
                "connected": d.get("connected"),
                "appId": d.get("appId"),
                "icon": d.get("icon"),
            }
            for d in res.get("devices", [])
        ]

    async def switch_input(self, input_id: str) -> dict[str, Any]:
        wanted = input_id.strip()
        try:
            for d in await self.list_inputs():
                if wanted.lower() in {str(d.get("id")).lower(), str(d.get("label")).lower()}:
                    wanted = d["id"]
                    break
        except SSAPError:
            pass
        if wanted.lower().replace(" ", "").startswith("hdmi") and "_" not in wanted:
            wanted = "HDMI_" + wanted.lower().replace(" ", "").replace("hdmi", "")
        await self.request(ep.SWITCH_INPUT, {"inputId": wanted})
        return {"input": wanted}

    # -------------------------------------------------------------- channels
    async def channels(self) -> list[dict[str, Any]]:
        res = await self.request(ep.GET_CHANNELS)
        return [
            {"id": c.get("channelId"), "number": c.get("channelNumber"), "name": c.get("channelName")}
            for c in res.get("channelList", [])
        ]

    async def current_channel(self) -> dict[str, Any]:
        return await self.request(ep.GET_CURRENT_CHANNEL)

    async def set_channel(self, channel: str) -> dict[str, Any]:
        """Accepts a channel number ("7", "7-1") or a channelId."""
        try:
            for c in await self.channels():
                if channel in (c["number"], c["id"]) or channel.lower() == (c["name"] or "").lower():
                    await self.request(ep.OPEN_CHANNEL, {"channelId": c["id"]})
                    return {"channel": c}
        except SSAPError:
            pass
        await self.request(ep.OPEN_CHANNEL, {"channelNumber": channel})
        return {"channel": channel}

    async def channel_step(self, up: bool) -> dict[str, Any]:
        await self.request(ep.CHANNEL_UP if up else ep.CHANNEL_DOWN)
        return {"ok": True}

    # ----------------------------------------------------------------- media
    async def media(self, action: str) -> dict[str, Any]:
        key = action.lower().replace("-", "_")
        key = {"fastforward": "fast_forward", "ff": "fast_forward", "rw": "rewind"}.get(key, key)
        table = {
            "play": (ep.MEDIA_PLAY, "PLAY"),
            "pause": (ep.MEDIA_PAUSE, "PAUSE"),
            "stop": (ep.MEDIA_STOP, "STOP"),
            "rewind": (ep.MEDIA_REWIND, "REWIND"),
            "fast_forward": (ep.MEDIA_FAST_FORWARD, "FASTFORWARD"),
        }
        if key not in table:
            raise ValueError("action must be play, pause, stop, rewind or fast_forward")
        uri, button = table[key]
        try:
            await self.request(uri)
        except SSAPError:
            # Some apps ignore media.controls but honour the remote's keys.
            await self.button(button)
            return {"ok": True, "action": key, "via": "remote button"}
        return {"ok": True, "action": key}

    # ---------------------------------------------------------------- remote
    async def button(self, name: str, strict: bool = False) -> str:
        key = normalize(name)
        if strict and key not in BUTTONS:
            raise ValueError(f"Unknown button {name!r}")
        await self._with_retry(lambda c: c.button(key))
        return key

    async def buttons(self, names: list[str], delay: float = 0.3) -> list[str]:
        sent = []
        for i, name in enumerate(names):
            if i:
                await asyncio.sleep(delay)
            sent.append(await self.button(name))
        return sent

    async def pointer(self, action: str, dx: int = 0, dy: int = 0) -> dict[str, Any]:
        if action == "move":
            await self._with_retry(lambda c: c.move(dx, dy))
        elif action == "click":
            await self._with_retry(lambda c: c.click())
        elif action == "scroll":
            await self._with_retry(lambda c: c.scroll(dx, dy))
        else:
            raise ValueError("action must be move, click or scroll")
        return {"ok": True}

    async def type_text(self, text: str, replace: bool = False, submit: bool = False) -> dict[str, Any]:
        """Type into the focused text field (an on-screen keyboard must be open)."""
        await self.request(ep.INSERT_TEXT, {"text": text, "replace": 1 if replace else 0})
        if submit:
            await self.request(ep.SEND_ENTER)
        return {"typed": text, "submitted": submit}

    async def delete_text(self, count: int) -> dict[str, Any]:
        await self.request(ep.DELETE_CHARACTERS, {"count": int(count)})
        return {"deleted": int(count)}

    # --------------------------------------------------------- notifications
    async def toast(self, message: str, icon: str | Path | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": message}
        if icon:
            path = Path(icon)
            payload["iconData"] = base64.b64encode(path.read_bytes()).decode()
            payload["iconExtension"] = path.suffix.lstrip(".") or "png"
        res = await self.request(ep.CREATE_TOAST, payload)
        return {"shown": message, "toastId": res.get("toastId")}

    # -------------------------------------------------------------- settings
    async def get_settings(self, category: str, keys: list[str]) -> dict[str, Any]:
        res = await self.request(ep.GET_SYSTEM_SETTINGS, {"category": category, "keys": keys})
        return res.get("settings", {})

    async def set_settings(self, category: str, settings: dict[str, Any], method: str = "auto") -> dict[str, Any]:
        """Write settings via the public API, falling back to the luna trick.

        Afterwards the values are read back so the caller knows what stuck.
        """
        used = None
        errors: list[str] = []
        if method in ("auto", "ssap"):
            try:
                await self.request(ep.SET_SYSTEM_SETTINGS, {"category": category, "settings": settings})
                used = "ssap"
            except SSAPError as exc:
                errors.append(f"ssap: {exc}")
                if method == "ssap":
                    raise
        if used is None and method in ("auto", "luna"):
            await self.luna(ep.LUNA_SET_SYSTEM_SETTINGS, {"category": category, "settings": settings})
            used = "luna"
            await asyncio.sleep(0.5)
        readback: dict[str, Any] = {}
        try:
            readback = await self.get_settings(category, list(settings))
        except SSAPError as exc:
            errors.append(f"readback: {exc}")
        verified = {k: readback.get(k) == v for k, v in settings.items()} if readback else {}
        return {
            "category": category,
            "requested": settings,
            "method": used,
            "now": readback,
            "verified": verified,
            "errors": errors,
        }

    async def picture_settings(self, keys: list[str] | None = None) -> dict[str, Any]:
        keys = keys or ["pictureMode", "backlight", "brightness", "contrast", "color", "energySaving"]
        return await self.get_settings("picture", keys)

    async def apply_tweak(self, name: str) -> dict[str, Any]:
        tweak = TWEAKS.get(name)
        if tweak is None:
            raise KeyError(f"Unknown tweak {name!r}. Options: {', '.join(TWEAKS)}")
        result = await self.set_settings(tweak.category, tweak.settings)
        result["tweak"] = name
        result["description"] = tweak.description
        return result

    # ------------------------------------------------------------ screenshot
    async def screenshot(self, save_to: str | Path | None = None) -> dict[str, Any]:
        """Grab the screen. Usually works for Live TV / menus; DRM apps and HDMI are blocked."""
        res = await self.request(ep.SCREENSHOT)
        uri = res.get("imageUri")
        if not uri:
            raise SSAPError("TV returned no imageUri", ep.SCREENSHOT, res)
        data = await asyncio.to_thread(_http_get, uri)
        out: dict[str, Any] = {"imageUri": uri, "bytes": len(data), "data": data}
        if save_to:
            Path(save_to).write_bytes(data)
            out["saved_to"] = str(save_to)
        return out


def _http_get(url: str, timeout: float = 10.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - URL comes from the TV on the LAN
        return resp.read()


__all__ = ["LGTV", "PermissionDenied", "ServiceNotFound", "SSAPError", "TVConnectionError", "TVError"]
