"""Windows read path for ``safe_fs``: shared read-only open and final-path check."""

from __future__ import annotations

import sys

# Imported only on Windows. This exact form also makes mypy skip the module elsewhere.
assert sys.platform == "win32"  # noqa: S101

import ctypes  # noqa: E402
import msvcrt  # noqa: E402
import os  # noqa: E402
from ctypes import wintypes  # noqa: E402

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
FILE_NAME_NORMALIZED = 0x0
VOLUME_NAME_DOS = 0x0
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_CreateFileW = _kernel32.CreateFileW
_CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
_CreateFileW.restype = wintypes.HANDLE

_GetFinalPathNameByHandleW = _kernel32.GetFinalPathNameByHandleW
_GetFinalPathNameByHandleW.argtypes = [
    wintypes.HANDLE,
    wintypes.LPWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
]
_GetFinalPathNameByHandleW.restype = wintypes.DWORD

_CloseHandle = _kernel32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]
_CloseHandle.restype = wintypes.BOOL


def _strip_extended_prefix(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[len("\\\\?\\UNC\\") :]
    if path.startswith("\\\\?\\"):
        return path[len("\\\\?\\") :]
    return path


def final_path(handle: int) -> str:
    """Path of the file behind an open handle, after every link was resolved."""
    size = 1024
    while True:
        buffer = ctypes.create_unicode_buffer(size)
        length = _GetFinalPathNameByHandleW(
            handle, buffer, size, FILE_NAME_NORMALIZED | VOLUME_NAME_DOS
        )
        if length == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        if length < size:
            return _strip_extended_prefix(buffer.value)
        size = length + 1


def open_shared(real: str) -> int:
    """Open for reading only, letting other programs read, write, rename or delete it."""
    handle = _CreateFileW(
        real,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN,
        None,
    )
    if handle is None or handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def close(handle: int) -> None:
    _CloseHandle(handle)


def read_file(real: str, max_bytes: int) -> tuple[bytes, str]:
    """Read ``real`` through a shared, read-only handle; return data and final path."""
    handle = open_shared(real)
    try:
        resolved = final_path(handle)
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _CloseHandle(handle)
        raise
    # From here on the C runtime owns the handle: closing ``fd`` closes it.
    try:
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            block = os.read(fd, min(remaining, 1024 * 1024))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        return b"".join(chunks), resolved
    finally:
        os.close(fd)
