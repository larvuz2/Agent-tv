"""App-id helpers: friendly names -> webOS app ids, and deep-link payloads."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

# Common ids. The TV's own app list is always checked first; these only help
# when a name is ambiguous or the app title differs from what people say.
KNOWN_APPS: dict[str, str] = {
    "youtube": "youtube.leanback.v4",
    "netflix": "netflix",
    "prime video": "amazon",
    "amazon": "amazon",
    "prime": "amazon",
    "disney+": "com.disney.disneyplus-prod",
    "disney plus": "com.disney.disneyplus-prod",
    "disney": "com.disney.disneyplus-prod",
    "apple tv": "com.apple.appletv",
    "spotify": "spotify-beehive",
    "plex": "cdp-30",
    "browser": "com.webos.app.browser",
    "web browser": "com.webos.app.browser",
    "live tv": "com.webos.app.livetv",
    "tv": "com.webos.app.livetv",
    "settings": "com.palm.app.settings",
    "lg content store": "com.webos.app.discovery",
    "app store": "com.webos.app.discovery",
    "home": "com.webos.app.home",
    "hdmi1": "com.webos.app.hdmi1",
    "hdmi 1": "com.webos.app.hdmi1",
    "hdmi2": "com.webos.app.hdmi2",
    "hdmi 2": "com.webos.app.hdmi2",
    "hdmi3": "com.webos.app.hdmi3",
    "hdmi 3": "com.webos.app.hdmi3",
    "hdmi4": "com.webos.app.hdmi4",
    "hdmi 4": "com.webos.app.hdmi4",
}

YOUTUBE_APP = "youtube.leanback.v4"
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def resolve_app(name: str, installed: list[dict[str, Any]]) -> str:
    """Match a friendly name against installed launch points.

    Order: exact id > exact title > known alias that is installed > title prefix
    > title substring. Raises ``LookupError`` with suggestions if nothing fits.
    """
    want = name.strip().lower()
    ids = {a.get("id", "").lower(): a.get("id") for a in installed}
    if want in ids:
        return ids[want]
    for app in installed:
        if (app.get("title") or "").strip().lower() == want:
            return app["id"]
    alias = KNOWN_APPS.get(want)
    if alias and (alias.lower() in ids or not installed):
        return alias
    for app in installed:
        if (app.get("title") or "").lower().startswith(want):
            return app["id"]
    for app in installed:
        if want in (app.get("title") or "").lower() or want in (app.get("id") or "").lower():
            return app["id"]
    if alias:
        return alias
    titles = ", ".join(sorted({a.get("title") or a.get("id") for a in installed})[:40])
    raise LookupError(f"No installed app matches {name!r}. Installed: {titles}")


def youtube_video_id(value: str) -> str:
    """Accept a YouTube URL (watch, youtu.be, shorts, live, embed) or a bare id."""
    value = value.strip()
    if _YT_ID.match(value):
        return value
    url = urlparse(value if "://" in value else f"https://{value}")
    host = (url.hostname or "").lower()
    if host.endswith("youtu.be"):
        candidate = url.path.strip("/").split("/")[0]
    elif "youtube" in host:
        qs = parse_qs(url.query)
        if "v" in qs:
            candidate = qs["v"][0]
        else:
            parts = [p for p in url.path.split("/") if p]
            candidate = parts[1] if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v") else ""
    else:
        candidate = ""
    if not _YT_ID.match(candidate or ""):
        raise ValueError(f"Could not find a YouTube video id in {value!r}")
    return candidate


def youtube_launch_payload(video: str, start_seconds: int | None = None) -> dict[str, Any]:
    """Deep link into the YouTube TV app (``youtube.leanback.v4``)."""
    vid = youtube_video_id(video)
    target = f"https://www.youtube.com/tv?v={vid}"
    if start_seconds:
        target += f"&t={int(start_seconds)}"
    return {"id": YOUTUBE_APP, "contentId": vid, "params": {"contentTarget": target}}


def youtube_search_payload(query: str) -> dict[str, Any]:
    """Open YouTube on its search results page (best effort; depends on app version)."""
    target = f"https://www.youtube.com/tv#/search?q={quote(query)}"
    return {"id": YOUTUBE_APP, "params": {"contentTarget": target}}


def netflix_launch_payload(title_or_url: str) -> dict[str, Any]:
    """Deep link into Netflix with a title / watch id (or a netflix.com URL)."""
    m = re.search(r"(\d{6,})", title_or_url)
    if not m:
        raise ValueError("Give a Netflix title id or a netflix.com/title/... or /watch/... URL")
    nid = m.group(1)
    return {"id": "netflix", "contentId": f"m=https://www.netflix.com/watch/{nid}&source_type=4"}
