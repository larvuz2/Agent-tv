"""Find LG webOS TVs on the local network.

1. SSDP (UPnP multicast) search for the webOS second-screen service. Fast and
   gives the model name, but some routers / VPNs / mesh setups block multicast.
2. Fallback: probe every address in the local /24 for the SSAP ports
   (3001/3000). Slower but works whenever unicast does.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
import urllib.request
from typing import Any

SSDP_ADDR = ("239.255.255.250", 1900)
SEARCH_TARGETS = (
    "urn:lge-com:service:webos-second-screen:1",
    "urn:schemas-upnp-org:device:MediaRenderer:1",
)


def _parse_headers(data: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in data.decode(errors="replace").split("\r\n")[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return headers


def _looks_like_webos(headers: dict[str, str]) -> bool:
    blob = " ".join(headers.values()).lower()
    return "webos" in blob or "lge-com" in blob or "lg electronics" in blob


def _describe(location: str, timeout: float = 2.0) -> dict[str, str]:
    """Fetch the UPnP device description for a friendly name / model."""
    try:
        with urllib.request.urlopen(location, timeout=timeout) as resp:  # noqa: S310 - LAN URL from SSDP
            xml = resp.read(64_000).decode(errors="replace")
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for tag in ("friendlyName", "modelName", "modelNumber", "manufacturer"):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
        if m:
            out[tag] = m.group(1).strip()
    return out


def ssdp_search(timeout: float = 3.0) -> list[dict[str, Any]]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.5)
    found: dict[str, dict[str, Any]] = {}
    try:
        for _ in range(2):
            for st in SEARCH_TARGETS:
                msg = (
                    "M-SEARCH * HTTP/1.1\r\n"
                    f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
                    'MAN: "ssdp:discover"\r\n'
                    "MX: 2\r\n"
                    f"ST: {st}\r\n\r\n"
                )
                sock.sendto(msg.encode(), SSDP_ADDR)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, (ip, _port) = sock.recvfrom(65507)
            except socket.timeout:
                continue
            headers = _parse_headers(data)
            if not _looks_like_webos(headers) or ip in found:
                continue
            found[ip] = {"host": ip, "via": "ssdp", "server": headers.get("server"), "location": headers.get("location")}
    except OSError:
        pass
    finally:
        sock.close()
    for info in found.values():
        if info.get("location"):
            info.update(_describe(info["location"]))
    return list(found.values())


def local_ipv4() -> str | None:
    """Our LAN address (no packets are sent; connect() on UDP only picks a route)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


async def _port_open(ip: str, port: int, timeout: float) -> bool:
    try:
        _r, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    w.close()
    try:
        await w.wait_closed()
    except OSError:
        pass
    return True


async def scan_subnet(subnet: str | None = None, timeout: float = 0.6) -> list[dict[str, Any]]:
    """Probe each host of a /24 (default: ours) for SSAP ports 3001 / 3000."""
    if subnet is None:
        ip = local_ipv4()
        if not ip:
            return []
        subnet = str(ipaddress.ip_network(f"{ip}/24", strict=False))
    net = ipaddress.ip_network(subnet, strict=False)
    sem = asyncio.Semaphore(128)

    async def probe(addr: str) -> dict[str, Any] | None:
        async with sem:
            ports = [p for p in (3001, 3000) if await _port_open(addr, p, timeout)]
        return {"host": addr, "via": "port-scan", "ports": ports} if ports else None

    results = await asyncio.gather(*(probe(str(h)) for h in net.hosts()))
    return [r for r in results if r]


async def discover(timeout: float = 3.0, scan: bool | None = None) -> list[dict[str, Any]]:
    """SSDP first; fall back to a port scan when SSDP finds nothing (or scan=True)."""
    found = await asyncio.to_thread(ssdp_search, timeout)
    if scan or (scan is None and not found):
        known = {f["host"] for f in found}
        found += [r for r in await scan_subnet() if r["host"] not in known]
    return found
