"""Wake-on-LAN, the only way to turn an LG TV on over the network.

For it to work the TV needs (names vary by year):
  Settings > General > Devices > External Devices > "TV On With Mobile" /
  "Turn on via Wi-Fi" = ON, and usually "Quick Start+" = ON.
A wired connection is the most reliable; Wi-Fi wake works on most 2018+ models.
"""

from __future__ import annotations

import ipaddress
import re
import socket

from .discovery import local_ipv4


def normalize_mac(mac: str) -> str:
    hexdigits = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(hexdigits) != 12:
        raise ValueError(f"not a MAC address: {mac!r}")
    return ":".join(hexdigits[i : i + 2] for i in range(0, 12, 2)).lower()


def magic_packet(mac: str) -> bytes:
    return b"\xff" * 6 + bytes.fromhex(normalize_mac(mac).replace(":", "")) * 16


def wake(macs: list[str] | str, host: str | None = None, repeat: int = 3) -> list[str]:
    """Send magic packets to every known MAC (wired + Wi-Fi). Returns targets used."""
    if isinstance(macs, str):
        macs = [macs]
    if not macs:
        raise ValueError("No MAC address known for this TV. Pair once while it is on, or pass --mac.")
    targets = {("255.255.255.255", 9)}
    ip = local_ipv4()
    if ip:
        targets.add((str(ipaddress.ip_network(f"{ip}/24", strict=False).broadcast_address), 9))
    if host:
        targets.add((host, 9))  # some TVs/routers only pass unicast to the last-known IP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        for _ in range(repeat):
            for mac in macs:
                packet = magic_packet(mac)
                for target in targets:
                    try:
                        sock.sendto(packet, target)
                    except OSError:
                        pass
    finally:
        sock.close()
    return sorted(f"{t[0]}:{t[1]}" for t in targets)
