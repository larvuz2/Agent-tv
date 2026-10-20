"""``agent-tv`` command-line interface.

Examples::

    agent-tv discover
    agent-tv pair 192.168.1.50 --name living-room
    agent-tv status
    agent-tv volume 15
    agent-tv launch netflix
    agent-tv youtube https://youtu.be/dQw4w9WgXcQ
    agent-tv button HOME DOWN DOWN ENTER
    agent-tv declutter --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from . import __version__
from .client import TVError
from .config import Config, TVEntry, slug
from .discovery import discover
from .tv import LGTV
from .tweaks import DECLUTTER, TWEAKS, describe


def _print(obj: Any) -> None:
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    elif obj is not None:
        print(obj)


def _prompt_notice() -> None:
    print(">>> Look at the TV and accept the connection request with your remote (60 s)...", file=sys.stderr)


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


async def cmd_discover(args: argparse.Namespace) -> Any:
    found = await discover(timeout=args.timeout, scan=True if args.scan else None)
    if not found:
        return "No LG TVs found. Make sure the TV is on, on the same network, and try --scan."
    return found


async def cmd_pair(args: argparse.Namespace) -> Any:
    cfg = Config.load()
    name = slug(args.name or "living-room")
    entry = cfg.tvs.get(name) or TVEntry(host=args.host)
    entry.host = args.host
    if args.transport:
        entry.transport = args.transport
    if args.port:
        entry.port = args.port
    if args.manifest:
        entry.manifest = args.manifest
    if args.force:
        entry.client_key = None
    cfg.upsert(name, entry, make_default=args.default or len(cfg.tvs) == 0)
    cfg.save()
    tv = LGTV(entry, name=name, config=cfg, on_prompt=_prompt_notice)
    try:
        await tv.connect(pairing_timeout=60)
        identity = await tv.learn_identity()
        try:
            await tv.toast("Agent TV is connected 👋")
        except TVError:
            pass
        return {"paired": name, "host": entry.host, "default": cfg.default == name, **identity, "config": str(cfg.path)}
    finally:
        await tv.close()


async def run_with_tv(args: argparse.Namespace) -> Any:
    tv = LGTV.from_config(args.tv, on_prompt=_prompt_notice)
    try:
        return await DISPATCH[args.cmd](tv, args)
    finally:
        await tv.close()


async def _volume(tv: LGTV, a: argparse.Namespace) -> Any:
    if a.level is None:
        return await tv.audio()
    if a.level in ("up", "+"):
        return await tv.volume_step(True, a.steps)
    if a.level in ("down", "-"):
        return await tv.volume_step(False, a.steps)
    return await tv.set_volume(int(a.level))


async def _mute(tv: LGTV, a: argparse.Namespace) -> Any:
    if a.state == "toggle":
        return await tv.set_mute(not (await tv.audio()).get("muted"))
    return await tv.set_mute(a.state == "on")


async def _channel(tv: LGTV, a: argparse.Namespace) -> Any:
    if a.channel is None:
        return await tv.current_channel()
    if a.channel in ("up", "down"):
        return await tv.channel_step(a.channel == "up")
    return await tv.set_channel(a.channel)


async def _settings(tv: LGTV, a: argparse.Namespace) -> Any:
    if a.action == "get":
        return await tv.get_settings(a.category, a.items)
    pairs = {}
    for item in a.items:
        k, _, v = item.partition("=")
        pairs[k] = _parse_value(v)
    return await tv.set_settings(a.category, pairs, method=a.method)


async def _declutter(tv: LGTV, a: argparse.Namespace) -> Any:
    names = a.names or DECLUTTER
    if not a.apply:
        return {"would_apply": [d for d in describe() if d["name"] in names], "hint": "re-run with --apply"}
    results = []
    for name in names:
        try:
            results.append(await tv.apply_tweak(name))
        except (TVError, KeyError) as exc:
            results.append({"tweak": name, "error": str(exc)})
    return results


async def _screenshot(tv: LGTV, a: argparse.Namespace) -> Any:
    res = await tv.screenshot(a.output)
    res.pop("data", None)
    return res


async def _watch(tv: LGTV, a: argparse.Namespace) -> Any:
    from . import endpoints as ep

    client = await tv.ensure_connected()

    def show(label: str):
        return lambda payload: print(json.dumps({label: payload}, ensure_ascii=False), flush=True)

    for label, uri in (
        ("power", ep.GET_POWER_STATE),
        ("app", ep.GET_FOREGROUND_APP),
        ("volume", ep.GET_VOLUME),
        ("media", ep.GET_MEDIA_FOREGROUND_APP),
    ):
        try:
            _sid, first = await client.subscribe(uri, show(label))
            show(label)(first)
        except TVError as exc:
            print(json.dumps({label: f"unavailable: {exc}"}), file=sys.stderr)
    print("Watching (Ctrl+C to stop)...", file=sys.stderr)
    while client.connected:
        await asyncio.sleep(1)
    return "TV closed the connection."


DISPATCH = {
    "status": lambda tv, a: tv.status(),
    "info": lambda tv, a: tv.system_info(),
    "services": lambda tv, a: tv.services(),
    "apps": lambda tv, a: tv.list_apps(include_hidden=a.all),
    "launch": lambda tv, a: tv.launch(a.app, a.content_id, json.loads(a.params) if a.params else None),
    "close": lambda tv, a: tv.close_app(a.app),
    "youtube": lambda tv, a: tv.youtube_search(a.video) if a.search else tv.youtube(a.video, a.start),
    "netflix": lambda tv, a: tv.netflix(a.title),
    "open-url": lambda tv, a: tv.open_url(a.url),
    "volume": _volume,
    "mute": _mute,
    "sound-output": lambda tv, a: tv.set_sound_output(a.output),
    "inputs": lambda tv, a: tv.list_inputs(),
    "input": lambda tv, a: tv.switch_input(a.input),
    "channels": lambda tv, a: tv.channels(),
    "channel": _channel,
    "media": lambda tv, a: tv.media(a.action),
    "button": lambda tv, a: tv.buttons(a.names, delay=a.delay),
    "type": lambda tv, a: tv.type_text(a.text, replace=a.replace, submit=a.enter),
    "toast": lambda tv, a: tv.toast(a.message, icon=a.icon),
    "off": lambda tv, a: tv.power_off(),
    "screen": lambda tv, a: tv.screen(a.state == "on"),
    "reboot": lambda tv, a: tv.reboot(),
    "settings": _settings,
    "picture": lambda tv, a: tv.picture_settings(),
    "declutter": _declutter,
    "screenshot": _screenshot,
    "raw": lambda tv, a: tv.request(a.uri, json.loads(a.payload) if a.payload else None),
    "luna": lambda tv, a: tv.luna(a.uri, json.loads(a.params)),
    "watch": _watch,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-tv", description="Control an LG webOS TV on your network.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--tv", help="TV name or IP from the config (default: the default TV)")
    p.add_argument("-v", "--verbose", action="count", default=0)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("discover", help="find LG TVs on the network")
    s.add_argument("--scan", action="store_true", help="also port-scan the local /24")
    s.add_argument("--timeout", type=float, default=3.0)

    s = sub.add_parser("pair", help="pair with a TV (accept the prompt on screen)")
    s.add_argument("host")
    s.add_argument("--name", default="living-room")
    s.add_argument("--default", action="store_true", help="make this the default TV")
    s.add_argument("--transport", choices=["auto", "wss", "ws"])
    s.add_argument("--port", type=int)
    s.add_argument("--manifest", choices=["default", "signed"])
    s.add_argument("--force", action="store_true", help="ignore the saved key and re-pair")

    sub.add_parser("tvs", help="list configured TVs")
    s = sub.add_parser("forget", help="remove a TV from the config")
    s.add_argument("name")

    s = sub.add_parser("on", help="power on via Wake-on-LAN")
    s.add_argument("--mac")
    s.add_argument("--wait", action="store_true", help="wait until the TV answers")

    sub.add_parser("status", help="power, app, volume, media state")
    sub.add_parser("info", help="model, firmware, network")
    sub.add_parser("services", help="SSAP services this firmware exposes")

    s = sub.add_parser("apps", help="list apps")
    s.add_argument("--all", action="store_true", help="include hidden/system apps")
    s = sub.add_parser("launch", help="launch an app by name or id")
    s.add_argument("app")
    s.add_argument("--content-id")
    s.add_argument("--params", help="JSON object passed as launch params")
    s = sub.add_parser("close", help="close an app")
    s.add_argument("app")
    s = sub.add_parser("youtube", help="play a YouTube video (URL or id)")
    s.add_argument("video")
    s.add_argument("--start", type=int, help="start offset in seconds")
    s.add_argument("--search", action="store_true", help="treat the argument as a search query")
    s = sub.add_parser("netflix", help="open a Netflix title (id or URL)")
    s.add_argument("title")
    s = sub.add_parser("open-url", help="open a web page in the TV browser")
    s.add_argument("url")

    s = sub.add_parser("volume", help="show / set volume: N, up, down")
    s.add_argument("level", nargs="?")
    s.add_argument("--steps", type=int, default=1)
    s = sub.add_parser("mute", help="mute on|off|toggle")
    s.add_argument("state", choices=["on", "off", "toggle"])
    s = sub.add_parser("sound-output", help="tv_speaker, external_arc, external_optical, bt_soundbar, ...")
    s.add_argument("output")

    sub.add_parser("inputs", help="list HDMI/AV inputs")
    s = sub.add_parser("input", help="switch input, e.g. HDMI_2")
    s.add_argument("input")
    sub.add_parser("channels", help="list broadcast channels")
    s = sub.add_parser("channel", help="show / set channel: number, up, down")
    s.add_argument("channel", nargs="?")

    s = sub.add_parser("media", help="play | pause | stop | rewind | fast_forward")
    s.add_argument("action")
    s = sub.add_parser("button", help="press remote buttons in order, e.g. HOME DOWN ENTER")
    s.add_argument("names", nargs="+")
    s.add_argument("--delay", type=float, default=0.3)
    s = sub.add_parser("type", help="type into the focused text field")
    s.add_argument("text")
    s.add_argument("--replace", action="store_true")
    s.add_argument("--enter", action="store_true", help="press Enter afterwards")
    s = sub.add_parser("toast", help="show a notification bubble")
    s.add_argument("message")
    s.add_argument("--icon")

    sub.add_parser("off", help="power off")
    s = sub.add_parser("screen", help="screen on|off (sound keeps playing)")
    s.add_argument("state", choices=["on", "off"])
    sub.add_parser("reboot", help="restart the TV")

    s = sub.add_parser("settings", help="get/set system settings")
    s.add_argument("action", choices=["get", "set"])
    s.add_argument("category", help="picture, general, option, sound, ...")
    s.add_argument("items", nargs="+", help="keys for get; key=value for set")
    s.add_argument("--method", choices=["auto", "ssap", "luna"], default="auto")
    sub.add_parser("picture", help="current picture settings")
    s = sub.add_parser("declutter", help="turn off home auto-launch, promos, ads (dry run unless --apply)")
    s.add_argument("names", nargs="*", help=f"subset of: {', '.join(TWEAKS)}")
    s.add_argument("--apply", action="store_true")
    s = sub.add_parser("screenshot", help="save a screenshot (Live TV/menus only)")
    s.add_argument("-o", "--output", default="tv-screenshot.jpg")

    s = sub.add_parser("raw", help="send any ssap:// request")
    s.add_argument("uri")
    s.add_argument("payload", nargs="?", help="JSON payload")
    s = sub.add_parser("luna", help="call an internal luna:// service (no result returned)")
    s.add_argument("uri")
    s.add_argument("params", help="JSON params")
    sub.add_parser("watch", help="stream power/app/volume/media events")
    sub.add_parser("mcp", help="run the MCP server on stdio (for Claude)")
    return p


async def amain(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING - 10 * min(args.verbose, 2),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        if args.cmd == "discover":
            result = await cmd_discover(args)
        elif args.cmd == "pair":
            result = await cmd_pair(args)
        elif args.cmd == "tvs":
            cfg = Config.load()
            result = {
                "default": cfg.default,
                "config": str(cfg.path),
                "tvs": {n: {"host": e.host, "model": e.model, "mac": e.mac, "paired": bool(e.client_key)} for n, e in cfg.tvs.items()},
            }
        elif args.cmd == "forget":
            cfg = Config.load()
            result = {"removed": cfg.remove(args.name)}
            cfg.save()
        elif args.cmd == "on":
            tv = LGTV.from_config(args.tv)
            result = tv.wake(args.mac)
            if args.wait:
                result["reachable"] = await tv.wait_until_reachable()
                await tv.close()
        else:
            result = await run_with_tv(args)
    except KeyboardInterrupt:
        return 130
    except (TVError, KeyError, LookupError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print(result)
    return 0


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["mcp"]:
        from .mcp_server import main as mcp_main

        mcp_main()
        return
    try:
        sys.exit(asyncio.run(amain(argv)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
