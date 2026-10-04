"""Guarantee: module boundaries are enforced statically, by reading the code.

* Only ``faro.safe_fs`` and ``faro.datadir`` may touch the filesystem.
* Only ``faro.net`` may import networking libraries.
* No product module may start processes, ``eval``/``exec`` code or import
  modules dynamically (except the grammar loader, which imports fixed names).

The checker parses every module under ``src/faro`` with ``ast``. It is
deliberately strict: a new exception must be proposed and added here
explicitly, never worked around.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
PACKAGE = SRC / "faro"

FS_MODULES = {"faro/safe_fs/__init__.py", "faro/safe_fs/_windows.py", "faro/datadir.py"}
NET_MODULES = {"faro/net/guard.py", "faro/net/download.py"}
CTYPES_MODULES = {"faro/safe_fs/_windows.py", "faro/indexing/languages.py"}
DYNAMIC_IMPORT_MODULES = {"faro/indexing/languages.py"}
PROCESS_MODULES: set[str] = set()  # Phase 2 will add the llama-server manager here.

NETWORK_IMPORTS = {
    "socket",
    "ssl",
    "http",
    "urllib.request",
    "urllib3",
    "requests",
    "httpx",
    "httpcore",
    "aiohttp",
    "websockets",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "socketserver",
    "huggingface_hub",
}
FS_IMPORTS = {"shutil", "tempfile", "glob", "fileinput", "mmap"}
PROCESS_IMPORTS = {"subprocess", "multiprocessing", "pty", "pexpect"}

OS_FS_CALLS = {
    "open", "fdopen", "listdir", "scandir", "walk", "fwalk", "remove", "unlink", "rename",
    "renames", "replace", "mkdir", "makedirs", "rmdir", "removedirs", "chmod", "chown",
    "lchown", "link", "symlink", "readlink", "truncate", "utime", "stat", "lstat", "access",
    "startfile", "mkfifo", "mknod", "chdir", "chroot",
}  # fmt: skip
OS_PROCESS_CALLS = {
    "system", "popen", "fork", "forkpty", "kill", "killpg", "posix_spawn", "posix_spawnp",
    "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
}  # fmt: skip
OS_PATH_FS_CALLS = {
    "exists", "lexists", "isfile", "isdir", "islink", "isjunction", "ismount", "getsize",
    "getmtime", "getatime", "getctime", "realpath", "samefile", "expanduser",
}  # fmt: skip
# Method names that only exist for filesystem I/O (pathlib and friends). Faro's
# own boundary APIs deliberately use other verbs (read_file, locate, load_text...).
FS_METHODS = {
    "read_text", "read_bytes", "write_text", "write_bytes", "open", "mkdir", "rmdir",
    "unlink", "touch", "iterdir", "glob", "rglob", "symlink_to", "hardlink_to", "chmod",
    "lchmod", "exists", "is_dir", "is_file", "is_symlink", "is_junction", "stat", "lstat",
    "resolve", "readlink", "samefile", "rename", "absolute", "expanduser",
}  # fmt: skip
FORBIDDEN_BUILTINS = {"open", "eval", "exec", "compile", "__import__", "breakpoint"}
RISKY_GETATTR_TARGETS = {"os", "shutil", "socket", "builtins", "io", "pathlib", "subprocess"}


@dataclass(frozen=True)
class Violation:
    module: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.module}:{self.line}: {self.message}"


def _imported_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    base = node.module or ""
    return [base] + [f"{base}.{alias.name}" if base else alias.name for alias in node.names]


def _matches(name: str, forbidden: set[str]) -> bool:
    return any(name == f or name.startswith(f + ".") for f in forbidden)


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def check_source(module: str, source: str) -> list[Violation]:
    tree = ast.parse(source, filename=module)
    found: list[Violation] = []

    def flag(node: ast.AST, message: str) -> None:
        found.append(Violation(module, getattr(node, "lineno", 0), message))

    fs_ok = module in FS_MODULES
    net_ok = module in NET_MODULES
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in _imported_names(node):
                if not net_ok and _matches(name, NETWORK_IMPORTS):
                    flag(node, f"network import '{name}' outside faro.net")
                if not fs_ok and _matches(name, FS_IMPORTS):
                    flag(node, f"filesystem import '{name}' outside safe_fs/datadir")
                if module not in PROCESS_MODULES and _matches(name, PROCESS_IMPORTS):
                    flag(node, f"process import '{name}'")
                if module not in CTYPES_MODULES and _matches(name, {"ctypes"}):
                    flag(node, "ctypes import")
                if module not in DYNAMIC_IMPORT_MODULES and _matches(name, {"importlib"}):
                    flag(node, "importlib import")
        elif isinstance(node, ast.Call):
            func = node.func
            dotted = _dotted(func)
            if (
                isinstance(func, ast.Name)
                and func.id in FORBIDDEN_BUILTINS
                and not (fs_ok and func.id == "open")
            ):
                flag(node, f"call to builtin '{func.id}'")
            if isinstance(func, ast.Name) and func.id == "getattr" and node.args:
                target = _dotted(node.args[0])
                if target in RISKY_GETATTR_TARGETS and not (fs_ok or net_ok):
                    flag(node, f"getattr on '{target}'")
            if dotted is not None:
                parts = dotted.split(".")
                if parts[0] == "os" and len(parts) == 2:
                    if parts[1] in OS_PROCESS_CALLS and module not in PROCESS_MODULES:
                        flag(node, f"process call '{dotted}'")
                    if parts[1] in OS_FS_CALLS and not fs_ok:
                        flag(node, f"filesystem call '{dotted}'")
                is_os_path = parts[:2] == ["os", "path"] and len(parts) == 3
                if is_os_path and parts[2] in OS_PATH_FS_CALLS and not fs_ok:
                    flag(node, f"filesystem call '{dotted}'")
                if dotted in {"io.open", "sqlite3.connect", "lancedb.connect"} and not fs_ok:
                    flag(node, f"filesystem call '{dotted}'")
                if dotted == "urllib.request.urlopen" and not net_ok:
                    flag(node, f"network call '{dotted}'")
            if isinstance(func, ast.Attribute) and func.attr in FS_METHODS and not fs_ok:
                flag(node, f"filesystem method '.{func.attr}()'")
    return found


def product_modules() -> list[tuple[str, Path]]:
    return [(path.relative_to(SRC).as_posix(), path) for path in sorted(PACKAGE.rglob("*.py"))]


def test_every_product_module_respects_the_boundaries() -> None:
    modules = product_modules()
    assert len(modules) > 15, "the checker did not find the product modules"
    violations = [
        violation
        for name, path in modules
        for violation in check_source(name, path.read_text(encoding="utf-8"))
    ]
    assert not violations, "Boundary violations:\n" + "\n".join(map(str, violations))


def test_allowed_modules_exist() -> None:
    names = {name for name, _ in product_modules()}
    for allowed in FS_MODULES | NET_MODULES | CTYPES_MODULES | DYNAMIC_IMPORT_MODULES:
        assert allowed in names, f"stale allow-list entry: {allowed}"


def test_the_checker_detects_violations() -> None:
    """The checker must not pass vacuously: feed it every kind of violation."""
    bad = """
import socket
import shutil, subprocess
from urllib.request import urlopen
import importlib, ctypes
from pathlib import Path
import os, io, sqlite3

def sneaky(p):
    open(p, "w")
    Path(p).write_text("x")
    Path(p).read_bytes()
    Path(p).resolve()
    os.remove(p)
    os.path.exists(p)
    os.system("dir")
    io.open(p)
    sqlite3.connect(p)
    getattr(os, "unlink")(p)
    eval("1")
    __import__("socket")
"""
    messages = [v.message for v in check_source("faro/evil.py", bad)]
    expected = [
        "network import 'socket'",
        "filesystem import 'shutil'",
        "process import 'subprocess'",
        "network import 'urllib.request'",
        "importlib import",
        "ctypes import",
        "call to builtin 'open'",
        "filesystem method '.write_text()'",
        "filesystem method '.read_bytes()'",
        "filesystem method '.resolve()'",
        "filesystem call 'os.remove'",
        "filesystem call 'os.path.exists'",
        "process call 'os.system'",
        "filesystem call 'io.open'",
        "filesystem call 'sqlite3.connect'",
        "getattr on 'os'",
        "call to builtin 'eval'",
        "call to builtin '__import__'",
    ]
    for message in expected:
        assert any(m.startswith(message) for m in messages), f"not detected: {message}"


def test_allowed_modules_may_use_their_own_capabilities() -> None:
    assert not check_source("faro/net/download.py", "import httpx\n")
    assert not check_source("faro/datadir.py", "import shutil\nopen('x', 'w')\n")
