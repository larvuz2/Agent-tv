"""Remote-control button names accepted by the pointer input socket.

Not every model supports every button. Unknown names are usually ignored by
the TV rather than rejected, so ``LGTV.button`` lets you send names outside this
list with ``strict=False``.
"""

BUTTONS: dict[str, str] = {
    # navigation
    "UP": "D-pad up",
    "DOWN": "D-pad down",
    "LEFT": "D-pad left",
    "RIGHT": "D-pad right",
    "ENTER": "OK / select",
    "BACK": "Back",
    "EXIT": "Exit to the current source",
    "HOME": "Home dashboard",
    "MENU": "Quick settings menu",
    "QMENU": "Quick settings menu",
    "INFO": "Info banner",
    "SEARCH": "Search",
    "RECENT": "Recent apps",
    "MYAPPS": "App list",
    "INPUT_HUB": "Home hub / input picker",
    "SCREEN_REMOTE": "On-screen remote panel",
    # volume / channels
    "VOLUMEUP": "Volume up",
    "VOLUMEDOWN": "Volume down",
    "MUTE": "Mute toggle",
    "CHANNELUP": "Channel up",
    "CHANNELDOWN": "Channel down",
    "GUIDE": "TV guide",
    "PROGRAM": "TV guide",
    "LIST": "Channel list",
    "DASH": "Dash (for sub-channels, e.g. 7-1)",
    "TV": "Live TV",
    # media
    "PLAY": "Play",
    "PAUSE": "Pause",
    "STOP": "Stop",
    "REWIND": "Rewind",
    "FASTFORWARD": "Fast forward",
    "RECORD": "Record",
    "RECLIST": "Recordings list",
    # colors / misc
    "RED": "Red",
    "GREEN": "Green",
    "YELLOW": "Yellow",
    "BLUE": "Blue",
    "ASTERISK": "*",
    "CC": "Closed captions",
    "AD": "Audio description",
    "SAP": "Audio track / multi-audio",
    "ASPECT_RATIO": "Aspect ratio",
    "TELETEXT": "Teletext",
    "TEXTOPTION": "Teletext options",
    "TIMER": "Sleep timer",
    "EZPIC": "Picture mode presets",
    "EYE_Q": "Energy saving",
    "MAGNIFIER_ZOOM": "Magnifier",
    "LIVE_ZOOM": "Live zoom",
    "3D_MODE": "3D mode",
    "EMANUAL": "User guide",
    "POWER": "Power (turns the TV off; cannot turn it on)",
    # app hotkeys
    "NETFLIX": "Netflix",
    "AMAZON": "Prime Video",
    "ALEXA": "Alexa",
}
BUTTONS.update({str(d): f"Digit {d}" for d in range(10)})

# Friendly aliases people (and models) tend to use.
ALIASES = {
    "OK": "ENTER",
    "SELECT": "ENTER",
    "RETURN": "BACK",
    "VOL_UP": "VOLUMEUP",
    "VOL+": "VOLUMEUP",
    "VOL_DOWN": "VOLUMEDOWN",
    "VOL-": "VOLUMEDOWN",
    "CH_UP": "CHANNELUP",
    "CH+": "CHANNELUP",
    "CH_DOWN": "CHANNELDOWN",
    "CH-": "CHANNELDOWN",
    "FF": "FASTFORWARD",
    "FAST_FORWARD": "FASTFORWARD",
    "RW": "REWIND",
    "SETTINGS": "MENU",
    "APPS": "MYAPPS",
    "INPUT": "INPUT_HUB",
}


def normalize(name: str) -> str:
    key = name.strip().upper().replace(" ", "_")
    return ALIASES.get(key, key)
