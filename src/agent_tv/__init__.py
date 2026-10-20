"""agent-tv: drive an LG webOS TV over the local network (SSAP over WebSocket).

Layers:
  client.SSAPClient  - raw protocol: pairing, requests, subscriptions, pointer socket
  tv.LGTV            - friendly API (volume, apps, YouTube, inputs, settings, ...)
  cli                - ``agent-tv`` command
  mcp_server         - ``agent-tv-mcp``: MCP tools so Claude can drive the TV
"""

from .client import (
    PairingError,
    PermissionDenied,
    ServiceNotFound,
    SSAPClient,
    SSAPError,
    TVConnectionError,
    TVError,
)
from .config import Config, TVEntry
from .tv import LGTV

__version__ = "0.1.0"

__all__ = [
    "LGTV",
    "Config",
    "PairingError",
    "PermissionDenied",
    "SSAPClient",
    "SSAPError",
    "ServiceNotFound",
    "TVConnectionError",
    "TVEntry",
    "TVError",
]
