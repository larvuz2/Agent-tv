"""MCP server: exposes the TV as tools for Claude (or any MCP client).

Run it with ``agent-tv-mcp`` (stdio). The repo's ``.mcp.json`` starts it
automatically when Claude Code is opened in this folder.

Works with both the 1.x (``FastMCP``) and 2.x (``MCPServer``) Python SDKs.
"""

from __future__ import annotations

import functools
import logging
import sys
from typing import Any, Awaitable, Callable, Literal, TypeVar

try:  # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image  # type: ignore[no-redef]
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore[no-redef]

from .config import Config, TVEntry, slug
from .discovery import discover
from .tv import LGTV
from .tweaks import TWEAKS, describe

log = logging.getLogger("agent_tv.mcp")

INSTRUCTIONS = """\
These tools control the user's real LG webOS TV on their home network (SSAP over WebSocket).
Every call has a visible/audible effect in their living room, so:
- Start with tv_status when you need to know what is on screen, the volume, or whether the TV is on.
- Prefer direct tools (launch_app, play_youtube, switch_input, set_volume) over press_buttons.
  Use press_buttons for menu navigation the API does not cover; check tv_status between steps.
- To play a specific YouTube video, find its URL or 11-character id first, then call play_youtube.
- Turning the TV ON only works through Wake-on-LAN (power action 'on'), and only if the TV allows it.
- Only power off, reboot, or change system settings when the user asked for it.
- take_screenshot usually works on menus and Live TV but returns black or an error inside
  DRM apps (Netflix, etc.) and HDMI inputs.
- If no TV is configured, use discover_tvs then pair_tv (the user must accept a prompt on the TV).
All tools accept an optional `tv` argument (name or IP) for homes with several TVs.
"""

mcp = _Server("lg-tv", instructions=INSTRUCTIONS)
F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def tool(fn: F) -> F:
    """Register a tool and turn any failure into a readable message for the model.

    (MCP SDK 2.x hides the text of unexpected exceptions; ToolError keeps it.)
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except KeyError as exc:
            raise ToolError(str(exc.args[0]) if exc.args else repr(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface the reason to the model
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    mcp.tool()(wrapper)
    return fn


class _Manager:
    """Keeps one live connection per TV across tool calls."""

    def __init__(self) -> None:
        self._tvs: dict[str, LGTV] = {}

    async def get(self, name: str | None) -> LGTV:
        cfg = Config.load()
        key, entry = cfg.resolve(name)
        tv = self._tvs.get(key)
        stale_key = bool(entry.client_key) and tv is not None and tv.entry.client_key != entry.client_key
        if tv is None or tv.entry.host != entry.host or stale_key:
            if tv is not None:
                await tv.close()
            tv = LGTV(entry, name=key, config=cfg, on_prompt=_prompt_notice)
            self._tvs[key] = tv
        return tv

    async def drop(self, key: str) -> None:
        tv = self._tvs.pop(key, None)
        if tv is not None:
            await tv.close()


manager = _Manager()


def _prompt_notice() -> None:
    log.warning("Waiting for the user to accept the pairing prompt on the TV")


# ---------------------------------------------------------------- setup tools
@tool
async def discover_tvs(scan: bool = False) -> dict[str, Any]:
    """Find LG webOS TVs on the local network (SSDP, falling back to a port scan).

    Set scan=True to always port-scan the local /24 as well.
    """
    found = await discover(timeout=3.0, scan=True if scan else None)
    return {"found": found}


@tool
async def pair_tv(host: str, name: str = "living-room", make_default: bool = True) -> dict[str, Any]:
    """Pair with a TV at `host` (IP address). The TV shows a prompt the user must accept
    with their remote within 60 seconds. Saves the key so later calls need no prompt."""
    cfg = Config.load()
    key = slug(name)
    entry = cfg.tvs.get(key) or TVEntry(host=host)
    entry.host = host
    cfg.upsert(key, entry, make_default=make_default)
    cfg.save()
    await manager.drop(key)
    tv = LGTV(entry, name=key, config=cfg, on_prompt=_prompt_notice)
    await tv.connect(pairing_timeout=60)
    identity = await tv.learn_identity()
    try:
        await tv.toast("Claude is connected to this TV 👋")
    except Exception:  # noqa: BLE001 - cosmetic
        pass
    manager._tvs[key] = tv
    return {"paired": key, "host": host, "default": cfg.default == key, **identity}


@tool
async def list_tvs() -> dict[str, Any]:
    """List configured TVs and which one is the default."""
    cfg = Config.load()
    return {
        "default": cfg.default,
        "tvs": {n: {"host": e.host, "model": e.model, "paired": bool(e.client_key), "mac": e.mac} for n, e in cfg.tvs.items()},
    }


# ---------------------------------------------------------------- state / info
@tool
async def tv_status(tv: str | None = None) -> dict[str, Any]:
    """Power state, foreground app, volume/mute, sound output and media playback state."""
    return await (await manager.get(tv)).status()


@tool
async def tv_info(tv: str | None = None) -> dict[str, Any]:
    """Model, firmware / webOS version, and network details."""
    return await (await manager.get(tv)).system_info()


# ----------------------------------------------------------------------- power
@tool
async def power(action: Literal["on", "off", "screen_off", "screen_on"], tv: str | None = None) -> dict[str, Any]:
    """Power control. 'on' = Wake-on-LAN (needs 'Turn on via Wi-Fi'/Quick Start+ enabled).
    'screen_off' blanks the panel but keeps audio playing; 'screen_on' restores it."""
    t = await manager.get(tv)
    if action == "on":
        res = t.wake()
        res["reachable"] = await t.wait_until_reachable(timeout=25)
        return res
    if action == "off":
        return await t.power_off()
    return await t.screen(action == "screen_on")


@tool
async def reboot_tv(tv: str | None = None) -> dict[str, Any]:
    """Restart the TV. Only when the user asks for it."""
    return await (await manager.get(tv)).reboot()


# ----------------------------------------------------------------------- audio
@tool
async def set_volume(level: int, tv: str | None = None) -> dict[str, Any]:
    """Set the volume to an absolute level (0-100; most people use 5-30)."""
    return await (await manager.get(tv)).set_volume(level)


@tool
async def change_volume(direction: Literal["up", "down"], steps: int = 1, tv: str | None = None) -> dict[str, Any]:
    """Nudge the volume up/down by a number of steps. Works with soundbars over ARC too."""
    return await (await manager.get(tv)).volume_step(direction == "up", steps)


@tool
async def set_mute(muted: bool, tv: str | None = None) -> dict[str, Any]:
    """Mute or unmute."""
    return await (await manager.get(tv)).set_mute(muted)


@tool
async def set_sound_output(output: str, tv: str | None = None) -> dict[str, Any]:
    """Change audio output: tv_speaker, external_arc, external_optical, bt_soundbar,
    headphone, tv_external_speaker, ..."""
    return await (await manager.get(tv)).set_sound_output(output)


# ------------------------------------------------------------------------ apps
@tool
async def list_apps(include_hidden: bool = False, tv: str | None = None) -> dict[str, Any]:
    """List installed apps (id + title). include_hidden adds system apps."""
    return {"apps": await (await manager.get(tv)).list_apps(include_hidden=include_hidden)}


@tool
async def launch_app(
    app: str,
    content_id: str | None = None,
    params: dict[str, Any] | None = None,
    tv: str | None = None,
) -> dict[str, Any]:
    """Launch an app by name ('Netflix', 'Disney+', 'Spotify') or id. Optional
    content_id / params are passed to the app for deep links."""
    return await (await manager.get(tv)).launch(app, content_id, params)


@tool
async def close_app(app: str, tv: str | None = None) -> dict[str, Any]:
    """Close an app by name or id."""
    return await (await manager.get(tv)).close_app(app)


@tool
async def play_youtube(video: str, start_seconds: int | None = None, tv: str | None = None) -> dict[str, Any]:
    """Play a YouTube video in the TV's YouTube app. `video` is a URL
    (watch, youtu.be, shorts, live) or an 11-character video id."""
    return await (await manager.get(tv)).youtube(video, start_seconds)


@tool
async def search_youtube(query: str, tv: str | None = None) -> dict[str, Any]:
    """Open YouTube on the TV with a search query (best effort; depends on the app version).
    For a specific video, prefer finding its URL and calling play_youtube."""
    return await (await manager.get(tv)).youtube_search(query)


@tool
async def open_netflix(title: str, tv: str | None = None) -> dict[str, Any]:
    """Open a Netflix title by numeric id or netflix.com/title|watch URL."""
    return await (await manager.get(tv)).netflix(title)


@tool
async def open_url(url: str, tv: str | None = None) -> dict[str, Any]:
    """Open a web page in the TV's built-in browser."""
    return await (await manager.get(tv)).open_url(url)


# -------------------------------------------------------------- inputs/channels
@tool
async def list_inputs(tv: str | None = None) -> dict[str, Any]:
    """List HDMI/AV inputs with labels and whether something is connected."""
    return {"inputs": await (await manager.get(tv)).list_inputs()}


@tool
async def switch_input(input_id: str, tv: str | None = None) -> dict[str, Any]:
    """Switch to an input by id or label, e.g. 'HDMI_2', 'hdmi 2', 'PlayStation'."""
    return await (await manager.get(tv)).switch_input(input_id)


@tool
async def list_channels(tv: str | None = None) -> dict[str, Any]:
    """List broadcast channels (needs an antenna/cable source set up on the TV)."""
    return {"channels": await (await manager.get(tv)).channels()}


@tool
async def set_channel(channel: str, tv: str | None = None) -> dict[str, Any]:
    """Tune Live TV to a channel number ('7', '7-1'), name, or channelId."""
    return await (await manager.get(tv)).set_channel(channel)


@tool
async def channel_step(direction: Literal["up", "down"], tv: str | None = None) -> dict[str, Any]:
    """Channel up or down."""
    return await (await manager.get(tv)).channel_step(direction == "up")


# --------------------------------------------------------------- media/remote
@tool
async def media_control(
    action: Literal["play", "pause", "stop", "rewind", "fast_forward"], tv: str | None = None
) -> dict[str, Any]:
    """Play/pause/stop/rewind/fast-forward the current media."""
    return await (await manager.get(tv)).media(action)


@tool
async def press_buttons(buttons: list[str], delay_seconds: float = 0.3, tv: str | None = None) -> dict[str, Any]:
    """Press remote-control buttons in order, e.g. ["HOME"], ["DOWN","DOWN","ENTER"].
    Names: UP DOWN LEFT RIGHT ENTER BACK EXIT HOME MENU INFO SEARCH, VOLUMEUP VOLUMEDOWN MUTE,
    CHANNELUP CHANNELDOWN GUIDE LIST, PLAY PAUSE STOP REWIND FASTFORWARD, RED GREEN YELLOW BLUE,
    0-9, NETFLIX AMAZON, CC SAP ASPECT_RATIO, SCREEN_REMOTE, POWER (off only)."""
    sent = await (await manager.get(tv)).buttons(buttons, delay=max(0.05, min(delay_seconds, 5.0)))
    return {"pressed": sent}


@tool
async def pointer(
    action: Literal["move", "click", "scroll"], dx: int = 0, dy: int = 0, tv: str | None = None
) -> dict[str, Any]:
    """Magic-remote pointer: move by (dx, dy) pixels, click, or scroll (dy>0 scrolls down)."""
    return await (await manager.get(tv)).pointer(action, dx, dy)


@tool
async def type_text(text: str, submit: bool = False, replace: bool = False, tv: str | None = None) -> dict[str, Any]:
    """Type into the focused text field (search boxes etc.; the on-screen keyboard
    must be open). submit=True presses Enter afterwards."""
    return await (await manager.get(tv)).type_text(text, replace=replace, submit=submit)


@tool
async def show_message(message: str, tv: str | None = None) -> dict[str, Any]:
    """Show a notification bubble (toast) on the TV screen."""
    return await (await manager.get(tv)).toast(message)


@tool
async def take_screenshot(tv: str | None = None) -> Image:
    """Capture what the TV shows (works for menus/Live TV; DRM apps and HDMI are usually blocked)."""
    shot = await (await manager.get(tv)).screenshot()
    return Image(data=shot["data"], format="jpeg")


# -------------------------------------------------------------------- settings
@tool
async def get_settings(category: str, keys: list[str], tv: str | None = None) -> dict[str, Any]:
    """Read system settings. Categories: picture, sound, general, option, aspectRatio,
    caption, lock, network, time, ... e.g. ('picture', ['pictureMode','backlight'])."""
    return await (await manager.get(tv)).get_settings(category, keys)


@tool
async def set_settings(
    category: str,
    settings: dict[str, Any],
    method: Literal["auto", "ssap", "luna"] = "auto",
    tv: str | None = None,
) -> dict[str, Any]:
    """Change system settings, e.g. ('picture', {'backlight': 40}) or
    ('picture', {'pictureMode': 'cinema'}). Tries the public API, then the luna
    trick, then reads the values back and reports which ones actually changed."""
    return await (await manager.get(tv)).set_settings(category, settings, method=method)


@tool
async def list_tweaks() -> dict[str, Any]:
    """Curated cleanup changes (no home auto-launch, no promos/ads, no LivePlus tracking, ...)."""
    return {"tweaks": describe()}


@tool
async def apply_tweaks(names: list[str], tv: str | None = None) -> dict[str, Any]:
    """Apply tweaks from list_tweaks by name. Each one is verified by reading it back."""
    t = await manager.get(tv)
    results = []
    for name in names:
        if name not in TWEAKS:
            results.append({"tweak": name, "error": f"unknown; options: {', '.join(TWEAKS)}"})
            continue
        try:
            results.append(await t.apply_tweak(name))
        except Exception as exc:  # noqa: BLE001 - report per tweak
            results.append({"tweak": name, "error": str(exc)})
    return {"results": results}


# ------------------------------------------------------------------ raw access
@tool
async def ssap_request(uri: str, payload: dict[str, Any] | None = None, tv: str | None = None) -> dict[str, Any]:
    """Send any SSAP request, e.g. 'ssap://api/getServiceList'. Escape hatch for
    endpoints without a dedicated tool."""
    return await (await manager.get(tv)).request(uri, payload)


@tool
async def luna_request(uri: str, params: dict[str, Any], tv: str | None = None) -> dict[str, Any]:
    """Call an internal luna:// service through the notification-alert trick.
    The TV never returns the luna result; verify effects another way."""
    return await (await manager.get(tv)).luna(uri, params)


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()
