# SSAP protocol notes (LG webOS)

Reference for anyone extending `src/agent_tv/client.py`.

## Transport

* `wss://<tv>:3001/` with a self-signed certificate (no verification possible).
  Required on most 2022+ firmware.
* `ws://<tv>:3000/` on older firmware; newer firmware refuses it.
* The TV answers WebSocket pings. We ping every 20 s.

## Handshake

```jsonc
→ {"id":"hello","type":"hello","payload":{}}
← {"id":"hello","type":"hello","payload":{"deviceModel":"...","deviceOSVersion":"..."}}

// newer webOS wants this before registering
→ {"id":"prereg_sysinfo","type":"request","uri":"ssap://system/getSystemInfo","payload":{}}

→ {"id":"register_0","type":"register","payload":{
     "pairingType":"PROMPT","forcePairing":false,
     "client-key":"<saved key, if any>",
     "manifest":{"manifestVersion":1,"appVersion":"1.1","permissions":[...]}}}
← {"id":"register_0","type":"response","payload":{"pairingType":"PROMPT","returnValue":true}}
   // TV shows "allow this device?"; the user accepts with the remote
← {"id":"register_0","type":"registered","payload":{"client-key":"<save me>"}}
```

Rejection: `{"type":"error","error":"403 User denied access"}`.

## Requests

```jsonc
→ {"id":"request_7","type":"request","uri":"ssap://audio/setVolume","payload":{"volume":12}}
← {"id":"request_7","type":"response","payload":{"returnValue":true}}
```

Errors arrive as `type: "error"` (`401 insufficient permissions`,
`404 no such service or method`) or as `payload.returnValue: false` with
`errorText`.

`type: "subscribe"` returns the current value, then pushes updates with the same
id until `type: "unsubscribe"`.

## Pointer / buttons

`ssap://com.webos.service.networkinput/getPointerInputSocket` returns
`socketPath`, a second websocket. Messages are line-based:

```
type:button\nname:HOME\n\n
type:move\ndx:10\ndy:-5\ndown:0\n\n
type:click\n\n
type:scroll\ndx:0\ndy:3\n\n
```

## Luna "alert trick"

Internal `luna://` services are not reachable through SSAP directly. Creating an
alert whose `onclose` action is a luna URI and then closing it makes the TV's
notification service perform the call:

```jsonc
→ ssap://system.notifications/createAlert
  {"message":" ","buttons":[{"label":"","onClick":"luna://X","params":{...}}],
   "onclose":{"uri":"luna://X","params":{...}},"onfail":{"uri":"luna://X","params":{...}}}
← {"alertId":"..."}
→ ssap://system.notifications/closeAlert {"alertId":"..."}
```

The luna result is not returned, so verify the effect separately (we read
settings back after writing them).

## Useful endpoints

See `src/agent_tv/endpoints.py`. Run `agent-tv services` on your TV to list the
services its firmware exposes.

## Setting keys

Per-model dumps of every settings category/key live in bscpylgtv's
`docs/available_settings_*.md`. Examples: `picture/pictureMode`,
`picture/backlight`, `general/homeAutoLaunch`, `general/homePromotion`,
`general/screenSaverAd`, `option/livePlus`, `option/quickStartMode`.
