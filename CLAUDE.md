# Agent TV: notes for Claude

This repo controls the user's LG webOS TV (living room) over the local network
via SSAP. The `lg-tv` MCP server (`.mcp.json` → `scripts/agent-tv-mcp`) exposes
it as tools.

## Before acting

* The TV is a physical device in someone's home. Every tool call is seen/heard.
* Only works when this session runs on a machine on the same LAN as the TV.
  Cloud sessions cannot reach it; say so instead of guessing results.
* If `tv_status` fails with "No TV configured", run `discover_tvs` then
  `pair_tv(host)` and tell the user to accept the prompt on the TV.

## First run on a new computer

* If `.venv` is missing, the `lg-tv` server can't start. Set up first:
  macOS/Linux `sh scripts/setup.sh`; Windows: the commands in README › Windows
  (venv + `claude mcp add lg-tv --scope local ...`).
* After setup, the user needs to restart Claude (`/exit`, then `claude`) or
  reconnect via `/mcp` so the tools load. Until then use the CLI:
  `.venv/bin/agent-tv discover`, `.venv/bin/agent-tv pair <ip>`.
* The user is not technical: give one action at a time, and tell them exactly
  when to look at the TV and press Accept.

## How to drive it

* Start with `tv_status` to see power, current app, volume, playback state.
* Prefer direct tools (`launch_app`, `play_youtube`, `switch_input`,
  `set_volume`, `media_control`) over `press_buttons`.
* For "play X on YouTube": find the video URL/id (web search), then `play_youtube`.
* Menu navigation: `press_buttons` in small steps; use `take_screenshot` where it
  works (menus, Live TV) to check where you are. It does not work in DRM apps.
* Power off, reboot, and settings changes only when the user asks.
* `set_settings` / `apply_tweaks` report `verified` per key: tell the user which
  changes actually took effect.

## Code

* `src/agent_tv/client.py`: protocol. `tv.py`: friendly API. `mcp_server.py`: tools.
* Tests: `.venv/bin/python -m pytest -q` (uses `tests/fake_tv.py`, an SSAP simulator).
  Add simulator behaviour + a test for every new endpoint.
* Pairing keys live in `~/.config/agent-tv/config.json`; never commit them.
* Keep the MCP server working with both mcp SDK 1.x (`FastMCP`) and 2.x (`MCPServer`).
