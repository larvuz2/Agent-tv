"""Low-level SSAP (Simple Service Access Protocol) client for LG webOS TVs.

Protocol summary
----------------
* The TV listens on ``wss://<tv>:3001`` (self-signed TLS, required on recent
  firmware) and, on older firmware, ``ws://<tv>:3000``.
* Every message is JSON: ``{"id", "type", "uri", "payload"}``. The TV answers
  with the same ``id`` and ``type`` ``response`` / ``error`` / ``registered``.
* Before any command works the client must ``register``. The first time, the
  TV shows an "allow this device?" prompt; accepting it returns a
  ``client-key`` that we store and send on later connections (no prompt).
* Remote-control buttons and the pointer go over a second websocket whose URL
  comes from ``getPointerInputSocket``. It speaks a tiny line format,
  e.g. ``type:button\\nname:HOME\\n\\n``.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import json
import logging
import ssl
import warnings
from typing import Any, Awaitable, Callable

from websockets.asyncio.client import ClientConnection, connect as ws_connect
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State

from . import endpoints as ep
from .manifest import registration_message

log = logging.getLogger(__name__)

SECURE_PORT = 3001
PLAIN_PORT = 3000

Callback = Callable[[dict[str, Any]], "Awaitable[None] | None"]


class TVError(Exception):
    """Base class for every error raised by this package."""


class TVConnectionError(TVError):
    """The TV could not be reached, or the connection dropped."""


class PairingError(TVError):
    """Registration with the TV failed (prompt rejected, timed out, ...)."""


class SSAPError(TVError):
    """The TV answered a request with an error."""

    def __init__(self, message: str, uri: str | None = None, payload: dict | None = None):
        super().__init__(f"{message} ({uri})" if uri else message)
        self.error = message
        self.uri = uri
        self.payload = payload or {}


class ServiceNotFound(SSAPError):
    """``404 no such service or method`` - endpoint missing on this firmware."""


class PermissionDenied(SSAPError):
    """``401 insufficient permissions`` - not paired, or permission not granted."""


def make_ssl_context(legacy: bool = False) -> ssl.SSLContext:
    """TLS context for the TV's self-signed certificate (no verification possible)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    if legacy:
        # Older TVs use small keys / old ciphers that OpenSSL 3 rejects by default.
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                ctx.minimum_version = ssl.TLSVersion.TLSv1
        except (ssl.SSLError, ValueError):  # pragma: no cover - depends on OpenSSL build
            pass
    return ctx


class SSAPClient:
    """One authenticated connection to a TV.

    Usage::

        client = SSAPClient("192.168.1.50", client_key=saved_key)
        key = await client.connect()          # prompts on the TV the first time
        await client.request("ssap://audio/setVolume", {"volume": 12})
        await client.button("HOME")
        await client.close()
    """

    def __init__(
        self,
        host: str,
        client_key: str | None = None,
        *,
        transport: str = "auto",
        port: int | None = None,
        manifest: str = "default",
        timeout: float = 10.0,
        connect_timeout: float = 5.0,
        on_prompt: Callable[[], None] | None = None,
    ) -> None:
        if transport not in ("auto", "wss", "ws"):
            raise ValueError("transport must be 'auto', 'wss' or 'ws'")
        self.host = host
        self.client_key = client_key
        self.transport = transport
        self.port = port
        self.manifest = manifest
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.on_prompt = on_prompt

        self.url: str | None = None
        self.hello: dict[str, Any] = {}
        self.prereg_system_info: dict[str, Any] = {}

        self._ws: ClientConnection | None = None
        self._ssl: ssl.SSLContext | None = None
        self._reader: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._subs: dict[str, tuple[str, Callback]] = {}
        self._ids = itertools.count(1)
        self._bg: set[asyncio.Task] = set()
        self._pointer: ClientConnection | None = None
        self._pointer_lock = asyncio.Lock()

    # ------------------------------------------------------------------ state
    @property
    def connected(self) -> bool:
        return (
            self._ws is not None
            and self._ws.state is State.OPEN
            and self._reader is not None
            and not self._reader.done()
        )

    async def __aenter__(self) -> "SSAPClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ------------------------------------------------------------- connecting
    def _candidates(self) -> list[tuple[str, ssl.SSLContext | None]]:
        wss = f"wss://{self.host}:{self.port or SECURE_PORT}"
        ws = f"ws://{self.host}:{self.port or PLAIN_PORT}"
        if self.transport == "wss":
            return [(wss, make_ssl_context()), (wss, make_ssl_context(legacy=True))]
        if self.transport == "ws":
            return [(ws, None)]
        # auto: secure first (required on 2022+ firmware), then plain for old sets.
        # A custom port applies to both attempts.
        return [
            (wss, make_ssl_context()),
            (wss, make_ssl_context(legacy=True)),
            (ws, None),
        ]

    async def _open(self, url: str, ctx: ssl.SSLContext | None, **kw: Any) -> ClientConnection:
        return await asyncio.wait_for(
            ws_connect(
                url,
                ssl=ctx,
                open_timeout=self.connect_timeout,
                close_timeout=2,
                max_size=None,
                **kw,
            ),
            self.connect_timeout + 1,
        )

    async def connect(self, pairing_timeout: float = 60.0) -> str:
        """Open the socket and register. Returns the client key (save it)."""
        await self.close()
        errors: list[str] = []
        ws: ClientConnection | None = None
        for url, ctx in self._candidates():
            try:
                ws = await self._open(url, ctx, ping_interval=20, ping_timeout=20)
            except Exception as exc:  # noqa: BLE001 - try the next transport
                errors.append(f"{url} -> {type(exc).__name__}: {exc}")
                log.debug("connect %s failed: %r", url, exc)
                continue
            self.url, self._ssl = url, ctx
            break
        if ws is None:
            raise TVConnectionError(
                f"Could not reach the TV at {self.host}. Is it on and on this network? "
                + " | ".join(errors)
            )
        try:
            await self._handshake(ws, pairing_timeout)
        except BaseException:
            await ws.close()
            raise
        self._ws = ws
        self._reader = asyncio.create_task(self._read_loop(ws), name="ssap-reader")
        assert self.client_key is not None
        return self.client_key

    async def _wait_for_id(self, ws: ClientConnection, msg_id: str, timeout: float) -> dict[str, Any]:
        """Read raw messages until one carries ``msg_id`` (used before the reader starts)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            raw = await asyncio.wait_for(ws.recv(), remaining)
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if msg.get("id") == msg_id:
                return msg

    async def _handshake(self, ws: ClientConnection, pairing_timeout: float) -> None:
        # 1) hello: harmless on old firmware, gives model/OS info on new firmware.
        try:
            await ws.send(json.dumps({"id": "hello", "type": "hello", "payload": {}}))
            msg = await self._wait_for_id(ws, "hello", 3)
            if msg.get("type") == "hello":
                self.hello = msg.get("payload") or {}
        except asyncio.TimeoutError:
            log.debug("no hello reply; continuing")

        # 2) newer webOS wants getSystemInfo before registration.
        try:
            await ws.send(json.dumps({"id": "prereg_sysinfo", "type": "request", "uri": ep.GET_SYSTEM_INFO, "payload": {}}))
            msg = await self._wait_for_id(ws, "prereg_sysinfo", 3)
            if msg.get("type") == "response":
                self.prereg_system_info = msg.get("payload") or {}
        except asyncio.TimeoutError:
            log.debug("no pre-registration system info; continuing")

        # 3) register (shows the on-screen prompt the first time).
        await ws.send(json.dumps(registration_message(self.client_key, self.manifest)))
        loop = asyncio.get_running_loop()
        start = loop.time()
        deadline = start + pairing_timeout
        # Without a key the TV shows a prompt right away. With a saved key it is
        # normally accepted at once; if not (key revoked), the TV prompts again,
        # so tell the user to look at the TV after a short grace period.
        prompt_at = start + 2.0
        prompted = False

        def notify() -> None:
            nonlocal prompted
            if not prompted:
                prompted = True
                if self.on_prompt:
                    self.on_prompt()

        while True:
            until = deadline if (prompted or not self.client_key) else min(prompt_at, deadline)
            try:
                msg = await self._wait_for_id(ws, "register_0", max(until - loop.time(), 0.01))
            except asyncio.TimeoutError:
                if not prompted and loop.time() < deadline:
                    notify()
                    continue
                raise PairingError(
                    "Timed out waiting for pairing. Accept the 'connection request' "
                    "prompt on the TV with your remote, then try again."
                ) from None
            kind = msg.get("type")
            payload = msg.get("payload") or {}
            if kind == "response" and payload.get("pairingType") == "PROMPT" and not self.client_key:
                notify()
            if kind == "registered":
                key = payload.get("client-key")
                if not key:
                    raise PairingError(f"TV registered us but sent no client key: {msg}")
                self.client_key = key
                return
            if kind == "error":
                raise PairingError(f"TV refused pairing: {msg.get('error') or msg}")
            if kind == "response" and payload.get("pairingType") not in (None, "PROMPT"):
                raise PairingError(f"TV asked for unsupported pairing type {payload.get('pairingType')}")
            # "response" with pairingType PROMPT -> keep waiting for "registered".

    async def close(self) -> None:
        """Close both sockets. Safe to call more than once."""
        pointer, self._pointer = self._pointer, None
        ws, self._ws = self._ws, None
        reader, self._reader = self._reader, None
        for sock in (pointer, ws):
            if sock is not None:
                try:
                    await sock.close()
                except Exception:  # noqa: BLE001
                    pass
        if reader is not None and not reader.done():
            reader.cancel()
            try:
                await reader
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._fail_pending(TVConnectionError("connection closed"))
        self._subs.clear()

    # ---------------------------------------------------------------- reading
    async def _read_loop(self, ws: ClientConnection) -> None:
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    log.debug("ignoring non-JSON message: %r", raw[:200])
                    continue
                mid = msg.get("id")
                fut = self._pending.get(mid)
                if fut is not None and not fut.done():
                    fut.set_result(msg)
                    continue
                sub = self._subs.get(mid)
                if sub is not None:
                    self._dispatch(sub[1], msg.get("payload") or {})
        except ConnectionClosed as exc:
            log.debug("TV connection closed: %s", exc)
        finally:
            self._fail_pending(TVConnectionError("Connection to the TV was closed"))

    def _dispatch(self, callback: Callback, payload: dict[str, Any]) -> None:
        try:
            result = callback(payload)
        except Exception:  # noqa: BLE001
            log.exception("subscription callback failed")
            return
        if inspect.isawaitable(result):
            task = asyncio.ensure_future(result)
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)

    def _fail_pending(self, exc: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    # --------------------------------------------------------------- requests
    def _require_ws(self) -> ClientConnection:
        if not self.connected:
            raise TVConnectionError("Not connected to the TV")
        assert self._ws is not None
        return self._ws

    @staticmethod
    def _uri(uri: str) -> str:
        return uri if "://" in uri else f"ssap://{uri}"

    @staticmethod
    def parse_response(msg: dict[str, Any], uri: str | None = None) -> dict[str, Any]:
        payload = msg.get("payload") or {}
        if msg.get("type") == "error":
            err = str(msg.get("error") or "unknown error")
            if err.startswith("404"):
                raise ServiceNotFound(err, uri, payload)
            if err.startswith("401"):
                raise PermissionDenied(err, uri, payload)
            raise SSAPError(err, uri, payload)
        if payload.get("returnValue") is False:
            err = payload.get("errorText") or payload.get("errorMessage") or f"request failed: {payload}"
            raise SSAPError(str(err), uri, payload)
        return payload

    async def request(
        self,
        uri: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        _kind: str = "request",
        _id: str | None = None,
    ) -> dict[str, Any]:
        """Send one request and return the response payload (raises on error)."""
        uri = self._uri(uri)
        ws = self._require_ws()
        mid = _id or f"{_kind}_{next(self._ids)}"
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        try:
            await ws.send(json.dumps({"id": mid, "type": _kind, "uri": uri, "payload": payload or {}}))
            msg = await asyncio.wait_for(fut, timeout or self.timeout)
        except asyncio.TimeoutError:
            raise SSAPError("timed out waiting for the TV to answer", uri) from None
        except ConnectionClosed as exc:
            raise TVConnectionError(f"Connection to the TV was closed: {exc}") from exc
        finally:
            self._pending.pop(mid, None)
        return self.parse_response(msg, uri)

    async def send(self, uri: str, payload: dict[str, Any] | None = None) -> None:
        """Fire-and-forget (used for power off, where the TV may never answer)."""
        ws = self._require_ws()
        mid = f"request_{next(self._ids)}"
        await ws.send(json.dumps({"id": mid, "type": "request", "uri": self._uri(uri), "payload": payload or {}}))

    async def subscribe(
        self, uri: str, callback: Callback, payload: dict[str, Any] | None = None
    ) -> tuple[str, dict[str, Any]]:
        """Subscribe to updates. Returns ``(subscription_id, first_payload)``."""
        mid = f"subscribe_{next(self._ids)}"
        self._subs[mid] = (self._uri(uri), callback)
        try:
            first = await self.request(uri, payload, _kind="subscribe", _id=mid)
        except BaseException:
            self._subs.pop(mid, None)
            raise
        return mid, first

    async def unsubscribe(self, sub_id: str) -> None:
        sub = self._subs.pop(sub_id, None)
        if sub is None or not self.connected:
            return
        assert self._ws is not None
        await self._ws.send(json.dumps({"id": sub_id, "type": "unsubscribe", "uri": sub[0], "payload": {}}))

    async def luna(self, uri: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call an internal ``luna://`` service via the notification "alert trick".

        We create an invisible alert whose close/click/fail actions point at the
        luna URI, then close it, so the TV's own notification service makes the
        call with its (higher) privileges. The luna result is NOT returned to us,
        so callers must verify the effect another way (e.g. read the setting back).
        """
        luna_uri = uri if uri.startswith("luna://") else f"luna://{uri}"
        alert = await self.request(
            ep.CREATE_ALERT,
            {
                "message": " ",
                "buttons": [{"label": "", "onClick": luna_uri, "params": params}],
                "onclose": {"uri": luna_uri, "params": params},
                "onfail": {"uri": luna_uri, "params": params},
            },
        )
        alert_id = alert.get("alertId")
        if not alert_id:
            raise SSAPError("TV did not return an alertId for the luna call", ep.CREATE_ALERT, alert)
        return await self.request(ep.CLOSE_ALERT, {"alertId": alert_id})

    # ---------------------------------------------------------- pointer input
    async def _pointer_socket(self) -> ClientConnection:
        async with self._pointer_lock:
            if self._pointer is not None and self._pointer.state is State.OPEN:
                return self._pointer
            res = await self.request(ep.POINTER_SOCKET)
            path = res.get("socketPath")
            if not path:
                raise SSAPError("TV returned no pointer socket path", ep.POINTER_SOCKET, res)
            ctx = (self._ssl or make_ssl_context()) if path.startswith("wss") else None
            sock = await self._open(path, ctx, ping_interval=None)
            self._pointer = sock
            task = asyncio.create_task(self._drain(sock), name="ssap-pointer-drain")
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)
            return sock

    @staticmethod
    async def _drain(sock: ClientConnection) -> None:
        try:
            async for _ in sock:
                pass
        except ConnectionClosed:
            pass

    async def send_input(self, message: str) -> None:
        """Send one raw pointer-socket message (retries once on a stale socket)."""
        for attempt in (1, 2):
            sock = await self._pointer_socket()
            try:
                await sock.send(message)
                return
            except ConnectionClosed:
                self._pointer = None
                if attempt == 2:
                    raise TVConnectionError("Pointer socket closed by the TV") from None

    async def button(self, name: str) -> None:
        await self.send_input(f"type:button\nname:{name}\n\n")

    async def move(self, dx: int, dy: int, drag: bool = False) -> None:
        await self.send_input(f"type:move\ndx:{dx}\ndy:{dy}\ndown:{1 if drag else 0}\n\n")

    async def click(self) -> None:
        await self.send_input("type:click\n\n")

    async def scroll(self, dx: int, dy: int) -> None:
        await self.send_input(f"type:scroll\ndx:{dx}\ndy:{dy}\n\n")
