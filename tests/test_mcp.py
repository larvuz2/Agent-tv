"""The MCP server exposes the expected tools and they reach the TV."""

from __future__ import annotations

import json

from agent_tv import mcp_server

EXPECTED = {
    "discover_tvs", "pair_tv", "list_tvs", "tv_status", "tv_info", "power", "reboot_tv",
    "set_volume", "change_volume", "set_mute", "set_sound_output", "list_apps", "launch_app",
    "close_app", "play_youtube", "search_youtube", "open_netflix", "open_url", "list_inputs",
    "switch_input", "list_channels", "set_channel", "channel_step", "media_control",
    "press_buttons", "pointer", "type_text", "show_message", "take_screenshot", "get_settings",
    "set_settings", "list_tweaks", "apply_tweaks", "ssap_request", "luna_request",
}


def _text(result) -> str:
    content = result.content if hasattr(result, "content") else result[0] if isinstance(result, tuple) else result
    return "".join(getattr(c, "text", "") for c in content)


async def test_tool_catalog():
    names = {t.name for t in await mcp_server.mcp.list_tools()}
    assert EXPECTED <= names


async def test_tools_drive_the_tv(paired_config, fake_tv):
    mcp_server.manager._tvs.clear()
    status = await mcp_server.mcp.call_tool("tv_status", {})
    assert "Active" in _text(status)

    await mcp_server.mcp.call_tool("play_youtube", {"video": "https://youtu.be/dQw4w9WgXcQ"})
    assert fake_tv.launched[-1]["contentId"] == "dQw4w9WgXcQ"

    await mcp_server.mcp.call_tool("press_buttons", {"buttons": ["HOME", "DOWN"], "delay_seconds": 0.05})
    await mcp_server.mcp.call_tool("show_message", {"message": "hi from Claude"})
    assert fake_tv.toasts == ["hi from Claude"]

    tweaks = json.loads(_text(await mcp_server.mcp.call_tool("list_tweaks", {})))
    assert any(t["name"] == "no_home_autolaunch" for t in tweaks["tweaks"])

    res = await mcp_server.mcp.call_tool("apply_tweaks", {"names": ["no_home_autolaunch", "no_live_plus"]})
    assert fake_tv.settings["general"]["homeAutoLaunch"] == "off"
    assert fake_tv.settings["option"]["livePlus"] == "off"
    assert "verified" in _text(res)

    for tv in mcp_server.manager._tvs.values():
        await tv.close()
    mcp_server.manager._tvs.clear()
