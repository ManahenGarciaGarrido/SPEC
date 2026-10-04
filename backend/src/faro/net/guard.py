"""Process-wide outbound network guard.

Faro must not talk to the network during normal use. ``install()`` patches the
Python socket layer so that connecting, sending datagrams or resolving a name
for anything other than loopback raises ``NetworkBlockedError``. The only
exception is code running inside ``allow_outbound()``, which is used solely by
``faro.net.download`` for downloads the user starts explicitly.

Native code that opens sockets by itself (Rust, C++) bypasses the Python socket
layer; the test suite therefore also runs inside an OS network namespace with
only loopback available (see the CI workflow).
"""

from __future__ import annotations

import contextlib
import contextvars
import ipaddress
import socket
import threading
from collections.abc import Callable, Iterator
from typing import Any

_LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost", "ip6-loopback"})

_outbound_reason: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "faro_outbound_reason", default=None
)
_lock = threading.Lock()
_originals: dict[str, Any] = {}
_installed: dict[str, Any] = {}
_active: dict[int, str] = {}
_blocked_attempts = 0


class NetworkBlockedError(ConnectionRefusedError):
    """Raised when code tries to reach a non-loopback address outside a download."""


def is_loopback_host(host: object) -> bool:
    """True for loopback (or unspecified, i.e. local) addresses and ``localhost``."""
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    name = host.strip().lower().rstrip(".")
    if name == "" or name in _LOOPBACK_NAMES:
        return True
    name = name.strip("[]").split("%", 1)[0]
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback or address.is_unspecified


def _address_allowed(family: int, address: object) -> bool:
    af_unix = getattr(socket, "AF_UNIX", None)
    if af_unix is not None and family == af_unix:
        return True  # local IPC, never leaves the machine
    if isinstance(address, tuple) and address:
        return is_loopback_host(address[0])
    return False


def _deny(what: str, target: object) -> None:
    global _blocked_attempts
    with _lock:
        _blocked_attempts += 1
    raise NetworkBlockedError(
        f"Faro blocked outbound network access ({what} {target!r}). "
        "The network is only used inside an explicit, user-started download."
    )


def _check_address(family: int, address: object, what: str) -> None:
    if _outbound_reason.get() is None and not _address_allowed(family, address):
        _deny(what, address)


def _check_host(host: object, what: str) -> None:
    if _outbound_reason.get() is None and not is_loopback_host(host):
        _deny(what, host)


def install() -> None:
    """Install the guard (idempotent)."""
    with _lock:
        if _originals:
            return
        # The wrappers look the originals up in ``_originals`` at call time.
        _originals.update(
            {
                "connect": socket.socket.connect,
                "connect_ex": socket.socket.connect_ex,
                "sendto": socket.socket.sendto,
                "sendmsg": getattr(socket.socket, "sendmsg", None),
                "getaddrinfo": socket.getaddrinfo,
                "gethostbyname": socket.gethostbyname,
                "gethostbyname_ex": socket.gethostbyname_ex,
                "gethostbyaddr": socket.gethostbyaddr,
            }
        )

        def connect(self: socket.socket, address: Any) -> None:
            _check_address(self.family, address, "connect to")
            return _originals["connect"](self, address)  # type: ignore[no-any-return]

        def connect_ex(self: socket.socket, address: Any) -> int:
            _check_address(self.family, address, "connect to")
            return _originals["connect_ex"](self, address)  # type: ignore[no-any-return]

        def sendto(self: socket.socket, data: Any, *args: Any) -> int:
            if args:
                _check_address(self.family, args[-1], "send datagram to")
            return _originals["sendto"](self, data, *args)  # type: ignore[no-any-return]

        def sendmsg(self: socket.socket, buffers: Any, *args: Any) -> int:
            if len(args) >= 3 and args[2] is not None:
                _check_address(self.family, args[2], "send message to")
            return _originals["sendmsg"](self, buffers, *args)  # type: ignore[no-any-return]

        def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
            _check_host(host, "resolve")
            return _originals["getaddrinfo"](host, *args, **kwargs)

        def gethostbyname(host: str) -> str:
            _check_host(host, "resolve")
            return _originals["gethostbyname"](host)  # type: ignore[no-any-return]

        def gethostbyname_ex(host: str) -> Any:
            _check_host(host, "resolve")
            return _originals["gethostbyname_ex"](host)

        def gethostbyaddr(host: str) -> Any:
            _check_host(host, "reverse-resolve")
            return _originals["gethostbyaddr"](host)

        socket.socket.connect = connect  # type: ignore[method-assign,assignment]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign,assignment]
        socket.socket.sendto = sendto  # type: ignore[method-assign,assignment]
        if _originals["sendmsg"] is not None:  # not available on Windows
            setattr(socket.socket, "sendmsg", sendmsg)  # noqa: B010
        socket.getaddrinfo = getaddrinfo
        socket.gethostbyname = gethostbyname
        socket.gethostbyname_ex = gethostbyname_ex
        socket.gethostbyaddr = gethostbyaddr
        _installed.update({"connect": connect, "getaddrinfo": getaddrinfo})


def is_installed() -> bool:
    """True when the guard is installed and still in place (nothing undid it)."""
    with _lock:
        if not _originals:
            return False
        return bool(
            socket.socket.connect is _installed["connect"]
            and socket.getaddrinfo is _installed["getaddrinfo"]
        )


def blocked_attempts() -> int:
    """Number of outbound attempts blocked since start-up."""
    with _lock:
        return _blocked_attempts


def active_outbound() -> list[str]:
    """Reasons of the explicit outbound operations currently running."""
    with _lock:
        return list(_active.values())


@contextlib.contextmanager
def allow_outbound(reason: str) -> Iterator[None]:
    """Allow outbound network access in the current context (explicit downloads only)."""
    token = _outbound_reason.set(reason)
    key = id(token)
    with _lock:
        _active[key] = reason
    try:
        yield
    finally:
        with _lock:
            _active.pop(key, None)
        _outbound_reason.reset(token)


def original(name: str) -> Callable[..., Any]:
    """The unguarded socket function ``name`` (for the guard's own tests)."""
    return _originals[name]  # type: ignore[no-any-return]
