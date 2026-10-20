"""Where TV addresses and pairing keys live.

The file is ``~/.config/agent-tv/config.json`` (override the folder with
``AGENT_TV_HOME``). It holds the pairing key, so it is written with 0600
permissions and is never stored in the git repo.

Layout::

    {
      "default": "living-room",
      "tvs": {
        "living-room": {
          "host": "192.168.1.50",
          "client_key": "...",
          "mac": ["aa:bb:cc:dd:ee:ff"],
          "transport": "auto",
          "port": null,
          "manifest": "default",
          "model": "OLED65C3PUA"
        }
      }
    }

Environment overrides (handy for one-off use): ``LGTV_HOST``,
``LGTV_CLIENT_KEY``, ``LGTV_MAC``, ``LGTV_TRANSPORT``, ``LGTV_PORT``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def config_dir() -> Path:
    return Path(os.environ.get("AGENT_TV_HOME") or Path.home() / ".config" / "agent-tv")


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class TVEntry:
    host: str
    client_key: str | None = None
    mac: list[str] = field(default_factory=list)
    transport: str = "auto"
    port: int | None = None
    manifest: str = "default"
    model: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TVEntry":
        mac = data.get("mac") or []
        if isinstance(mac, str):
            mac = [mac]
        return cls(
            host=data["host"],
            client_key=data.get("client_key"),
            mac=list(mac),
            transport=data.get("transport") or "auto",
            port=data.get("port"),
            manifest=data.get("manifest") or "default",
            model=data.get("model"),
        )


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "tv"


class Config:
    def __init__(self, data: dict[str, Any] | None = None, path: Path | None = None):
        self.path = path or config_path()
        data = data or {}
        self.default: str | None = data.get("default")
        self.tvs: dict[str, TVEntry] = {
            name: TVEntry.from_dict(entry) for name, entry in (data.get("tvs") or {}).items()
        }

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        if path.exists():
            return cls(json.loads(path.read_text() or "{}"), path)
        return cls({}, path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"default": self.default, "tvs": {n: asdict(e) for n, e in self.tvs.items()}}
        tmp = self.path.with_suffix(".tmp")
        # Create with 0600 from the start: the file holds the pairing key.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(data, indent=2) + "\n")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def upsert(self, name: str, entry: TVEntry, make_default: bool = False) -> str:
        name = slug(name)
        self.tvs[name] = entry
        if make_default or not self.default or self.default not in self.tvs:
            self.default = name
        return name

    def remove(self, name: str) -> bool:
        name = slug(name)
        existed = self.tvs.pop(name, None) is not None
        if self.default == name:
            self.default = next(iter(self.tvs), None)
        return existed

    def resolve(self, name: str | None = None) -> tuple[str, TVEntry]:
        """Pick a TV: explicit name > LGTV_HOST env > default > the only one."""
        if name:
            key = slug(name)
            if key in self.tvs:
                return key, self._with_env(self.tvs[key], allow_host=False)
            for key, entry in self.tvs.items():  # allow an IP as the "name"
                if entry.host == name:
                    return key, self._with_env(entry, allow_host=False)
            raise KeyError(f"No TV named {name!r}. Known: {', '.join(self.tvs) or 'none'}")
        env_host = os.environ.get("LGTV_HOST")
        if env_host:
            for key, entry in self.tvs.items():
                if entry.host == env_host:
                    return key, self._with_env(entry)
            return "env", self._with_env(TVEntry(host=env_host))
        if self.default and self.default in self.tvs:
            return self.default, self._with_env(self.tvs[self.default], allow_host=False)
        if len(self.tvs) == 1:
            key = next(iter(self.tvs))
            return key, self._with_env(self.tvs[key], allow_host=False)
        raise KeyError(
            "No TV configured yet. Run `agent-tv discover` then `agent-tv pair <ip>` "
            "(or set LGTV_HOST)."
        )

    @staticmethod
    def _with_env(entry: TVEntry, allow_host: bool = True) -> TVEntry:
        e = TVEntry(**asdict(entry))
        if allow_host and os.environ.get("LGTV_HOST"):
            e.host = os.environ["LGTV_HOST"]
        if os.environ.get("LGTV_CLIENT_KEY"):
            e.client_key = os.environ["LGTV_CLIENT_KEY"]
        if os.environ.get("LGTV_MAC"):
            e.mac = [m.strip() for m in os.environ["LGTV_MAC"].split(",") if m.strip()]
        if os.environ.get("LGTV_TRANSPORT"):
            e.transport = os.environ["LGTV_TRANSPORT"]
        if os.environ.get("LGTV_PORT"):
            e.port = int(os.environ["LGTV_PORT"])
        return e
