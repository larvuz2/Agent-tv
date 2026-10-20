"""Curated settings changes for cleaning up the webOS experience.

The setting keys come from settings dumps of 2021-2025 LG models (see
bscpylgtv's ``docs/available_settings_*.md``). Not every key exists on every
model or firmware. ``LGTV.apply_tweak`` therefore reads each value back after
writing it and reports whether the change took effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Tweak:
    category: str
    settings: dict[str, Any]
    description: str
    note: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


TWEAKS: dict[str, Tweak] = {
    "no_home_autolaunch": Tweak(
        "general",
        {"homeAutoLaunch": "off"},
        "Stop the Home dashboard from popping up every time the TV turns on; "
        "the TV returns to the last input or app instead.",
        tags=("declutter",),
    ),
    "no_home_promotions": Tweak(
        "general",
        {"homePromotion": "off"},
        "Turn off promoted/sponsored tiles and banners on the Home screen.",
        tags=("declutter", "ads"),
    ),
    "no_screensaver_ads": Tweak(
        "general",
        {"screenSaverAd": "off"},
        "Turn off advertising in the screensaver.",
        tags=("declutter", "ads"),
    ),
    "no_customized_ads": Tweak(
        "general",
        {"customizedAd": "off"},
        "Opt out of personalised ads.",
        note="Some regions manage this only in the user agreements screen.",
        tags=("privacy", "ads"),
    ),
    "no_live_plus": Tweak(
        "option",
        {"livePlus": "off"},
        "Turn off LivePlus (ACR: content recognition that reports what is on screen).",
        tags=("privacy",),
    ),
    "no_ai_nudges": Tweak(
        "general",
        {"aiNudge": "off"},
        "Stop AI recommendation pop-ups.",
        note="Only on 2023+ models.",
        tags=("declutter",),
    ),
    "quick_start_on": Tweak(
        "option",
        {"quickStartMode": "on"},
        "Enable Quick Start+ so the TV stays reachable in standby; needed for "
        "reliable Wake-on-LAN and instant power-on. Uses a little more standby power.",
        tags=("power",),
    ),
    "standby_light_off": Tweak(
        "option",
        {"standByLight": "off"},
        "Turn off the standby LED.",
        tags=("cosmetic",),
    ),
}

DECLUTTER = [name for name, t in TWEAKS.items() if "declutter" in t.tags or "ads" in t.tags]


def describe() -> list[dict[str, Any]]:
    return [
        {"name": n, "category": t.category, "settings": t.settings, "description": t.description, "note": t.note}
        for n, t in TWEAKS.items()
    ]
