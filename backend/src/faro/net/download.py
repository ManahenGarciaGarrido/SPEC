"""Explicit downloads: the only code path in Faro that reaches the Internet.

Used by the user-started "download model" (and, later, "download documentation")
actions. Every file is pinned by SHA-256 and size; a mismatch aborts the
download and nothing is kept. Files are written through ``DataDir``, so they
can only land inside the application's data directory.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx

from faro.datadir import DataDir
from faro.net import guard

_CHUNK = 1024 * 1024


class DownloadError(Exception):
    """A download failed or its content did not match the pinned hash."""


@dataclass(frozen=True)
class RemoteFile:
    url: str
    sha256: str
    size: int
    destination: tuple[str, ...]  # path parts below the data directory


@dataclass(frozen=True)
class DownloadProgress:
    file_index: int
    file_count: int
    name: str
    received: int
    total: int


ProgressCallback = Callable[[DownloadProgress], None]
HttpClient = httpx.Client


def download_files(
    datadir: DataDir,
    files: Sequence[RemoteFile],
    *,
    reason: str,
    progress: ProgressCallback | None = None,
    client: httpx.Client | None = None,
) -> None:
    """Download ``files`` into the data directory, verifying size and SHA-256."""
    with guard.allow_outbound(reason):
        owns_client = client is None
        http = client or httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=120.0),
            headers={"User-Agent": "faro-downloader"},
        )
        try:
            for index, remote in enumerate(files):
                _download_one(datadir, http, remote, index, len(files), progress)
        finally:
            if owns_client:
                http.close()


def _download_one(
    datadir: DataDir,
    http: httpx.Client,
    remote: RemoteFile,
    index: int,
    count: int,
    progress: ProgressCallback | None,
) -> None:
    name = "/".join(remote.destination)
    digest = hashlib.sha256()
    received = 0
    try:
        with datadir.atomic_writer(*remote.destination) as handle:
            with http.stream("GET", remote.url) as response:
                if response.status_code != 200:
                    raise DownloadError(f"{name}: HTTP {response.status_code} from {remote.url}")
                for block in response.iter_bytes(_CHUNK):
                    received += len(block)
                    if received > remote.size:
                        raise DownloadError(f"{name}: larger than the expected {remote.size} bytes")
                    digest.update(block)
                    handle.write(block)
                    if progress is not None:
                        progress(DownloadProgress(index, count, name, received, remote.size))
            if received != remote.size:
                raise DownloadError(f"{name}: got {received} bytes, expected {remote.size}")
            if digest.hexdigest() != remote.sha256:
                raise DownloadError(f"{name}: SHA-256 mismatch, the file was discarded")
    except httpx.HTTPError as exc:
        raise DownloadError(f"{name}: {exc}") from exc
