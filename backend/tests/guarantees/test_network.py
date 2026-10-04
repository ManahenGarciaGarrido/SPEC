"""Guarantee: no network traffic leaves the machine during normal use.

The guard is installed for the whole test session (see conftest.py), exactly
as the application installs it at start-up. These tests check what it blocks
and what it lets through. None of them sends a packet outside the machine:
blocked calls are stopped before reaching the OS, and the "allowed" paths are
exercised with stubs or in-memory transports.
"""

from __future__ import annotations

import hashlib
import socket
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

from faro.datadir import DataDir
from faro.net import download, guard
from faro.net.guard import NetworkBlockedError


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.8.9.10", True),
        ("::1", True),
        ("[::1]", True),
        ("::ffff:127.0.0.1", True),
        ("localhost", True),
        ("LOCALHOST.", True),
        ("0.0.0.0", True),
        (None, True),
        ("", True),
        ("192.0.2.1", False),
        ("10.0.0.1", False),
        ("::ffff:8.8.8.8", False),
        ("2001:db8::1", False),
        ("example.com", False),
        ("localhost.evil.com", False),
        (b"8.8.8.8", False),
        (1234, False),
    ],
)
def test_loopback_detection(host: object, expected: bool) -> None:
    assert guard.is_loopback_host(host) is expected


def test_tcp_connections_outside_are_blocked() -> None:
    before = guard.blocked_attempts()
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("192.0.2.1", 443), timeout=0.1)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(NetworkBlockedError):
            sock.connect(("192.0.2.1", 80))
        with pytest.raises(NetworkBlockedError):
            sock.connect_ex(("192.0.2.1", 80))
    assert guard.blocked_attempts() >= before + 3


def test_dns_lookups_are_blocked() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(NetworkBlockedError):
        socket.gethostbyname("example.com")
    with pytest.raises(NetworkBlockedError):
        socket.gethostbyname_ex("example.com")
    with pytest.raises(NetworkBlockedError):
        socket.gethostbyaddr("8.8.8.8")


def test_udp_datagrams_outside_are_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with pytest.raises(NetworkBlockedError):
            sock.sendto(b"x", ("8.8.8.8", 53))
        with pytest.raises(NetworkBlockedError):
            sock.connect(("8.8.8.8", 53))


def test_http_clients_are_blocked() -> None:
    with pytest.raises(httpx.ConnectError):
        httpx.get("http://example.com", timeout=1)


def test_loopback_traffic_is_allowed() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            conn, _ = server.accept()
            with conn:
                client.sendall(b"ping")
                assert conn.recv(4) == b"ping"
    assert socket.getaddrinfo("localhost", 80)


def test_allow_outbound_is_scoped_to_the_download(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def fake_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> list[Any]:
        calls.append(host)
        return []

    monkeypatch.setitem(guard._originals, "getaddrinfo", fake_getaddrinfo)
    with guard.allow_outbound("test download"):
        assert guard.active_outbound() == ["test download"]
        socket.getaddrinfo("example.com", 443)  # allowed: reaches the (stubbed) resolver
    assert calls == ["example.com"]
    assert guard.active_outbound() == []
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)


def test_permission_does_not_leak_into_other_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(guard._originals, "getaddrinfo", lambda *a, **k: [])
    outcome: list[str] = []

    def worker() -> None:
        try:
            socket.getaddrinfo("example.com", 443)
            outcome.append("allowed")
        except NetworkBlockedError:
            outcome.append("blocked")

    with guard.allow_outbound("test download"):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    assert outcome == ["blocked"]


def test_install_is_idempotent() -> None:
    guard.install()
    guard.install()
    assert guard.is_installed()


# --- Explicit downloads ----------------------------------------------------------


def _transport(payloads: dict[str, bytes], seen: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.extend(guard.active_outbound())
        body = payloads.get(str(request.url))
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    return httpx.MockTransport(handler)


def _remote(url: str, body: bytes, *parts: str) -> download.RemoteFile:
    return download.RemoteFile(url, hashlib.sha256(body).hexdigest(), len(body), parts)


def test_download_verifies_and_stores_inside_the_data_dir(tmp_path: Path) -> None:
    datadir = DataDir(tmp_path / "data")
    body = b"model weights"
    seen: list[str] = []
    client = httpx.Client(transport=_transport({"https://x.test/m.onnx": body}, seen))
    progress: list[download.DownloadProgress] = []
    download.download_files(
        datadir,
        [_remote("https://x.test/m.onnx", body, "models", "m.onnx")],
        reason="test model",
        progress=progress.append,
        client=client,
    )
    assert (tmp_path / "data" / "models" / "m.onnx").read_bytes() == body
    assert seen == ["test model"], "the request did not run inside an explicit download"
    assert progress[-1].received == len(body)
    assert guard.active_outbound() == []


@pytest.mark.parametrize("problem", ["hash", "size", "status"])
def test_download_rejects_bad_files_and_keeps_nothing(tmp_path: Path, problem: str) -> None:
    datadir = DataDir(tmp_path / "data")
    body = b"model weights"
    remote = _remote("https://x.test/m.onnx", body, "models", "m.onnx")
    served = {"https://x.test/m.onnx": body}
    if problem == "hash":
        served = {"https://x.test/m.onnx": b"tampered data"}
        remote = download.RemoteFile(
            remote.url, remote.sha256, len(b"tampered data"), remote.destination
        )
    elif problem == "size":
        served = {"https://x.test/m.onnx": body + b"extra"}
    else:
        served = {}
    client = httpx.Client(transport=_transport(served, []))
    with pytest.raises(download.DownloadError):
        download.download_files(datadir, [remote], reason="test", client=client)
    models_dir = tmp_path / "data" / "models"
    assert not models_dir.exists() or not any(models_dir.iterdir())
