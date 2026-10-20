# Agent TV

Control an LG webOS TV over your home network from Python, the command line, or
**Claude** (via MCP). It speaks LG's own second-screen protocol (SSAP over
WebSocket), the same one the LG ThinQ app uses. Nothing is installed on the TV.

```
 you ──▶ Claude ──MCP──▶ agent-tv-mcp ──SSAP / wss:3001──▶ LG TV
                         (this repo, on a computer on your Wi-Fi)
```

> **It has to run on a computer on the same network as the TV.**
> The TV only answers on your LAN. A Claude session running in the cloud (like
> claude.ai/code) cannot reach it. Run this on a Mac/PC/Raspberry Pi at home,
> then talk to it from Claude Code there, or from the Claude app through
> Remote Control (see below).

## 1. One-time TV settings

Names move around between model years; search the TV's settings if needed.

| Setting | Where (2020+ models) | Why |
| --- | --- | --- |
| **Turn on via Wi-Fi** / "TV On With Mobile" | General › Devices › External Devices › TV On With Mobile | Lets us wake the TV and keeps the API reachable |
| **Quick Start+** | General › Additional Settings | Keeps the network alive in standby (needed for Wake-on-LAN) |
| LG Connect Apps (2016–2019 only) | Network | Turns the SSAP API on |
| A fixed IP for the TV | Your router's DHCP reservation | So the saved address keeps working |

## 2. Install and pair (on the home computer)

```sh
git clone <this repo> agent-tv && cd agent-tv
sh scripts/setup.sh                    # creates .venv and installs everything
.venv/bin/agent-tv discover            # finds the TV (SSDP, then a port scan)
.venv/bin/agent-tv pair 192.168.1.50   # accept the prompt on the TV with the remote
.venv/bin/agent-tv status              # power, app, volume, what's playing
```

Pairing stores the TV's address, MAC addresses and pairing key in
`~/.config/agent-tv/config.json` (permissions 600, never in git). After that no
prompt appears again. Re-pair with `agent-tv pair <ip> --force`.

## 3. Talk to it through Claude

**Claude Code, at home.** Run `claude` in this folder. The repo's `.mcp.json`
registers the `lg-tv` MCP server; approve it the first time. Then just ask:
*"put on lo-fi beats on YouTube"*, *"switch to the PlayStation and set volume to 18"*,
*"turn the screen off but keep the music"*, *"clean up the home screen ads"*.

**From the Claude app / phone.** On the home computer, in this folder:

```sh
claude            # once, to trust the folder and approve the lg-tv server
claude remote-control
```

The session then shows up in the Claude app; it runs on the home computer, so
it can reach the TV.

**Claude Desktop or any MCP client.** Point it at the launcher:

```json
{
  "mcpServers": {
    "lg-tv": { "command": "/absolute/path/to/agent-tv/scripts/agent-tv-mcp" }
  }
}
```

Or register it for every Claude Code project:
`claude mcp add lg-tv --scope user -- /absolute/path/to/agent-tv/scripts/agent-tv-mcp`.
(Windows: use `.venv\Scripts\agent-tv-mcp.exe` as the command.)

### MCP tools

| Area | Tools |
| --- | --- |
| Setup | `discover_tvs`, `pair_tv`, `list_tvs` |
| State | `tv_status`, `tv_info`, `take_screenshot` |
| Power | `power` (on via Wake-on-LAN / off / screen_off / screen_on), `reboot_tv` |
| Sound | `set_volume`, `change_volume`, `set_mute`, `set_sound_output` |
| Apps | `list_apps`, `launch_app`, `close_app`, `play_youtube`, `search_youtube`, `open_netflix`, `open_url` |
| Inputs / TV | `list_inputs`, `switch_input`, `list_channels`, `set_channel`, `channel_step` |
| Remote | `media_control`, `press_buttons`, `pointer`, `type_text`, `show_message` |
| Settings | `get_settings`, `set_settings`, `list_tweaks`, `apply_tweaks` |
| Raw | `ssap_request`, `luna_request` |

## 4. Command line

```sh
agent-tv status | info | services
agent-tv apps [--all]            agent-tv launch "disney+"      agent-tv close netflix
agent-tv youtube https://youtu.be/dQw4w9WgXcQ --start 30
agent-tv open-url example.com    agent-tv netflix 80057281
agent-tv volume 15 | up --steps 3 | down      agent-tv mute toggle
agent-tv inputs                  agent-tv input "PlayStation 5"
agent-tv media pause             agent-tv button HOME DOWN DOWN ENTER
agent-tv type "severance" --enter            agent-tv toast "Dinner's ready"
agent-tv screen off | on         agent-tv off              agent-tv on --wait
agent-tv settings get picture pictureMode backlight
agent-tv settings set picture backlight=40
agent-tv declutter               # dry run; add --apply to turn off home auto-launch, promos, ads
agent-tv screenshot -o shot.jpg  agent-tv watch            # live event stream
agent-tv raw ssap://api/getServiceList
```

Use `--tv <name>` to target another TV (pair it with `--name bedroom`).

## 5. What it can and cannot do

See **[docs/CAPABILITIES.md](docs/CAPABILITIES.md)**. Short version: apps,
YouTube deep links, volume, inputs, media keys, every remote button, typing,
notifications, screen off, many settings (including turning off home-screen
ads), and Wake-on-LAN all work over the API. Uninstalling apps, reading what's
playing inside Netflix, screenshots of DRM content, and anything that needs a
shell on the TV do not, unless you enable Developer Mode or root the TV.

## Troubleshooting

* **"Could not reach the TV"**: check the IP (`agent-tv discover`), that the TV is
  on, and that the computer is on the same network (not a guest Wi-Fi or VPN).
* **Pairing times out**: the prompt disappears after a while. Run `pair` again and
  press *Accept* on the TV within a minute.
* **"401 insufficient permissions"**: re-pair with `--force`, or try the older
  signed manifest: `agent-tv pair <ip> --force --manifest signed`.
* **`on` does nothing**: enable *Turn on via Wi-Fi* and *Quick Start+*, pair once
  while the TV is on so its MAC is saved, and prefer Ethernet.
* **A setting did not change**: `set_settings` reports `verified` per key. Some keys
  don't exist on every model, and LG has locked some internal services over time.

## Development

```sh
.venv/bin/python -m pytest -q    # runs against tests/fake_tv.py, an SSAP simulator
```

```
src/agent_tv/
  client.py       SSAP protocol: TLS/plain transport, pairing, requests, subscriptions,
                  pointer socket, luna "alert trick"
  tv.py           LGTV: friendly API used by the CLI and MCP server
  mcp_server.py   MCP tools (works with mcp SDK 1.x and 2.x)
  cli.py          `agent-tv` command
  discovery.py    SSDP + port-scan discovery
  wol.py          Wake-on-LAN
  apps.py         app-name resolution, YouTube/Netflix deep links
  tweaks.py       curated settings changes (declutter / privacy / power)
  manifest.py     pairing manifests (current unsigned + legacy signed)
  endpoints.py    SSAP / luna URIs
  buttons.py      remote button names + aliases
tests/            simulator + tests for protocol, API and MCP tools
docs/             capabilities, protocol notes
```

Protocol details were cross-checked against
[aiowebostv](https://github.com/home-assistant-libs/aiowebostv) (Home Assistant),
[bscpylgtv](https://github.com/chros73/bscpylgtv),
[lgtv2](https://github.com/hobbyquaker/lgtv2) and
[lgtv-control-mcp](https://github.com/brunofgmag/lgtv-control-mcp).
