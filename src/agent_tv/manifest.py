"""Pairing manifests sent in the SSAP ``register`` message.

Two variants are kept:

* ``default`` - unsigned manifest that lists every permission directly. This is
  what the Home Assistant library (aiowebostv) uses today and it works on
  current firmware (webOS 6 through webOS 25).
* ``signed`` - the classic manifest signed with LG's own "LG Remote App" test
  key. Older libraries (lgtv2, bscpylgtv) use it. Try it if the default one is
  rejected or a command fails with "401 insufficient permissions".
"""

from __future__ import annotations

import copy
from typing import Any

PERMISSIONS = [
    "APP_TO_APP",
    "CLOSE",
    "CONTROL_AUDIO",
    "CONTROL_DISPLAY",
    "CONTROL_INPUT_JOYSTICK",
    "CONTROL_INPUT_MEDIA_PLAYBACK",
    "CONTROL_INPUT_MEDIA_RECORDING",
    "CONTROL_INPUT_TEXT",
    "CONTROL_INPUT_TV",
    "CONTROL_MOUSE_AND_KEYBOARD",
    "CONTROL_POWER",
    "CONTROL_TV_SCREEN",
    "CONTROL_TV_STANBY",
    "LAUNCH",
    "LAUNCH_WEBAPP",
    "READ_APP_STATUS",
    "READ_COUNTRY_INFO",
    "READ_CURRENT_CHANNEL",
    "READ_INPUT_DEVICE_LIST",
    "READ_INSTALLED_APPS",
    "READ_LGE_SDX",
    "READ_LGE_TV_INPUT_EVENTS",
    "READ_NETWORK_STATE",
    "READ_NOTIFICATIONS",
    "READ_POWER_STATE",
    "READ_RUNNING_APPS",
    "READ_SETTINGS",
    "READ_STORAGE_DEVICE_LIST",
    "READ_TV_CHANNEL_LIST",
    "READ_TV_CURRENT_TIME",
    "READ_UPDATE_INFO",
    "SEARCH",
    "TEST_OPEN",
    "TEST_PROTECTED",
    "TEST_SECURE",
    "UPDATE_FROM_REMOTE_APP",
    "WRITE_NOTIFICATION_ALERT",
    "WRITE_NOTIFICATION_TOAST",
    "WRITE_SETTINGS",
]

DEFAULT_MANIFEST: dict[str, Any] = {
    "manifestVersion": 1,
    "appVersion": "1.1",
    "permissions": PERMISSIONS,
}

# Public, well-known signature used by every open-source LG client since 2014.
_SIGNATURE = (
    "eyJhbGdvcml0aG0iOiJSU0EtU0hBMjU2Iiwia2V5SWQiOiJ0ZXN0LXNpZ25pbm"
    "ctY2VydCIsInNpZ25hdHVyZVZlcnNpb24iOjF9.hrVRgjCwXVvE2OOSpDZ58hR"
    "+59aFNwYDyjQgKk3auukd7pcegmE2CzPCa0bJ0ZsRAcKkCTJrWo5iDzNhMBWRy"
    "aMOv5zWSrthlf7G128qvIlpMT0YNY+n/FaOHE73uLrS/g7swl3/qH/BGFG2Hu4"
    "RlL48eb3lLKqTt2xKHdCs6Cd4RMfJPYnzgvI4BNrFUKsjkcu+WD4OO2A27Pq1n"
    "50cMchmcaXadJhGrOqH5YmHdOCj5NSHzJYrsW0HPlpuAx/ECMeIZYDh6RMqaFM"
    "2DXzdKX9NmmyqzJ3o/0lkk/N97gfVRLW5hA29yeAwaCViZNCP8iC9aO0q9fQoj"
    "oa7NQnAtw=="
)

SIGNED_MANIFEST: dict[str, Any] = {
    "manifestVersion": 1,
    "appVersion": "1.1",
    "signed": {
        "created": "20140509",
        "appId": "com.lge.test",
        "vendorId": "com.lge",
        "localizedAppNames": {
            "": "LG Remote App",
            "ko-KR": "리모컨 앱",
            "zxx-XX": "ЛГ Rэмotэ AПП",
        },
        "localizedVendorNames": {"": "LG Electronics"},
        "permissions": [
            "TEST_SECURE",
            "CONTROL_INPUT_TEXT",
            "CONTROL_MOUSE_AND_KEYBOARD",
            "READ_INSTALLED_APPS",
            "READ_LGE_SDX",
            "READ_NOTIFICATIONS",
            "SEARCH",
            "WRITE_SETTINGS",
            "WRITE_NOTIFICATION_ALERT",
            "CONTROL_POWER",
            "READ_CURRENT_CHANNEL",
            "READ_RUNNING_APPS",
            "READ_UPDATE_INFO",
            "UPDATE_FROM_REMOTE_APP",
            "READ_LGE_TV_INPUT_EVENTS",
            "READ_TV_CURRENT_TIME",
        ],
        "serial": "2f930e2d2cfe083771f68e4fe7bb07",
    },
    "permissions": PERMISSIONS,
    "signatures": [{"signatureVersion": 1, "signature": _SIGNATURE}],
}

MANIFESTS = {"default": DEFAULT_MANIFEST, "signed": SIGNED_MANIFEST}


def registration_message(client_key: str | None, manifest: str = "default") -> dict[str, Any]:
    """Build the ``register`` message. A saved client key skips the on-screen prompt."""
    if manifest not in MANIFESTS:
        raise ValueError(f"unknown manifest {manifest!r}; choose one of {sorted(MANIFESTS)}")
    payload: dict[str, Any] = {
        "forcePairing": False,
        "pairingType": "PROMPT",
        "manifest": copy.deepcopy(MANIFESTS[manifest]),
    }
    if client_key:
        payload["client-key"] = client_key
    return {"type": "register", "id": "register_0", "payload": payload}
