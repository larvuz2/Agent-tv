# What Agent TV can and cannot do

Status key: **API** = a direct network call, reliable. **UI** = done by pressing
remote buttons, works but is "blind" (no reliable screen reading inside apps).
**Varies** = depends on model year / firmware; the tool reports what happened.

Nothing below has been run against your specific TV yet. The first thing to do
at home is `agent-tv info` and `agent-tv services` to see what your firmware exposes.

## Can do

| What | How | Notes |
| --- | --- | --- |
| Power off | API | |
| Power **on** | Wake-on-LAN | Needs *Turn on via Wi-Fi* + *Quick Start+*; Ethernet most reliable |
| Screen off / on (audio keeps playing) | API | Good for music |
| Volume, mute, step up/down | API | Absolute volume may be ignored when audio goes to some soundbars; steps still work |
| Switch audio output (TV speaker, ARC, optical, Bluetooth) | API | |
| List / launch / close apps by name | API | |
| YouTube: play a specific video, with start time | API deep link | Most reliable deep link on webOS |
| YouTube search | API deep link | Best effort, depends on app version |
| Netflix title deep link | API | Format varies by app version |
| Open any web page in the TV browser | API | |
| Inputs: list, switch by name ("PlayStation 5") | API | |
| Live TV: channel list, tune, up/down, current program | API | Needs an antenna/cable source |
| Play / pause / stop / rewind / fast-forward | API, falls back to remote keys | |
| Every remote button (HOME, arrows, OK, BACK, colour keys, digits, ...) | API (pointer socket) | |
| Magic-remote pointer: move, click, scroll | API | |
| Type into search boxes | API | On-screen keyboard must be open |
| Notifications on screen | API | |
| Read state: power, foreground app, volume, playback state, model, firmware, MACs | API | |
| Live event stream (app changes, volume, power) | API | `agent-tv watch` |
| Read many settings (picture, sound, general, option, ...) | API | |
| Change settings: picture mode, backlight, contrast, energy saving, ... | API or luna trick | Verified by reading back |
| **Declutter**: stop Home auto-launch, Home promotions, screensaver ads, personalised ads, AI nudges | API / luna | `agent-tv declutter --apply`; varies by model |
| Privacy: turn off LivePlus (content recognition) | luna | Varies |
| Screenshot of menus / Live TV | API | Lets Claude "see" the screen in those cases |
| Reboot | API | Varies; some firmware blocks it |
| Several TVs | config | `--tv bedroom` / `tv` argument |
| Any other SSAP endpoint | `ssap_request` / `agent-tv raw` | Escape hatch |

## Can do, but only by driving the UI (UI)

These have no API; Claude can press buttons, but without screen reading inside
apps it is slow and can go wrong. Fine for "open Settings > Picture" style tasks.

* Rearranging or hiding apps on the Home bar.
* Uninstalling apps (through the TV's own *Edit App List* screen).
* Signing in / out of streaming apps, picking profiles.
* Navigating inside Netflix / Prime / Disney+ beyond what a deep link reaches.

## Cannot do (over the network API)

* **Reach the TV from a cloud session.** Must run on a device on your LAN.
* Turn on a TV that is fully off with Wake-on-LAN disabled.
* Install apps from the LG Content Store, or uninstall apps directly.
* Read what is playing *inside* third-party apps (title, position, subtitles);
  only the app id and a playing/paused state are exposed.
* Screenshots of DRM-protected apps (Netflix etc.) or HDMI inputs: the TV
  returns black or refuses.
* Get results back from internal `luna://` services (the alert trick is write-only).
* Shell / file-system access, changing the launcher itself, blocking ads system-wide.
* Use the TV's microphone / voice assistant.
* Firmware updates (we can read the version, not trigger an update).

## Next steps toward "full coding control"

1. **Developer Mode** (free LG developer account + the *Developer Mode* app on the
   TV): lets us install our **own web apps** on the TV with `ares-cli`, for
   example a custom home screen, a dashboard, or an app Claude can render content
   into. The developer session expires periodically and has to be extended
   (this can be scripted).
2. **Root** (webOS Homebrew Channel; works only on certain firmware versions):
   shell access, SSH, custom services, real ad blocking, startup scripts. Higher
   risk; check your firmware version first (`agent-tv info`).
3. **Network-level ad blocking**: point the TV's DNS at Pi-hole / NextDNS /
   AdGuard to cut most webOS ads and telemetry without touching the TV.
