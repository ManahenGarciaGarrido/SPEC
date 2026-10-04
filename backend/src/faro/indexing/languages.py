"""Language detection and tree-sitter grammar loading.

Grammars come from individual wheels with the compiled parser inside, so
nothing is downloaded at runtime (docs/PLAN.md 4.1).
"""

from __future__ import annotations

import ctypes
import functools
import importlib
import posixpath
from dataclasses import dataclass

import tree_sitter


@dataclass(frozen=True)
class LanguageInfo:
    name: str
    grammar: tuple[str, str] | None  # (module, function) of the tree-sitter binding


_GRAMMARS: dict[str, tuple[str, str]] = {
    "dart": ("tree_sitter_dart", "language"),
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "lua": ("tree_sitter_lua", "language"),
    "luau": ("tree_sitter_luau", "language"),
    "markdown": ("tree_sitter_markdown", "language"),
    "yaml": ("tree_sitter_yaml", "language"),
    "json": ("tree_sitter_json", "language"),
}

_EXTENSIONS: dict[str, str] = {
    ".dart": "dart",
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".lua": "lua",
    ".luau": "luau",
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdx": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".arb": "json",  # Flutter localization files
    # Indexed with the line-based fallback (no grammar bundled).
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sql": "sql",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "scss",
    ".less": "css",
    ".vue": "vue",
    ".svelte": "svelte",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".properties": "properties",
    ".gradle": "gradle",
    ".xml": "xml",
    ".plist": "xml",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".tf": "terraform",
    ".hcl": "terraform",
    ".txt": "text",
    ".rst": "text",
}

_FILENAMES: dict[str, str] = {
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
    "makefile": "make",
    "jenkinsfile": "groovy",
    "procfile": "text",
    "gemfile": "ruby",
    "rakefile": "ruby",
    "vagrantfile": "ruby",
}


def detect(rel_path: str) -> LanguageInfo | None:
    """Language of a file from its name, or None when it is not indexed."""
    name = posixpath.basename(rel_path).lower()
    language = _FILENAMES.get(name)
    if language is None and name.startswith("dockerfile."):
        language = "dockerfile"
    if language is None:
        language = _EXTENSIONS.get(posixpath.splitext(name)[1])
    if language is None:
        return None
    return LanguageInfo(name=language, grammar=_GRAMMARS.get(language))


# PyCapsule keeps a pointer to its name (not a copy): this object must outlive
# every capsule, hence a module-level constant.
_CAPSULE_NAME = ctypes.create_string_buffer(b"tree_sitter.Language")
_capsule_new = ctypes.pythonapi.PyCapsule_New
_capsule_new.restype = ctypes.py_object
_capsule_new.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]


def _as_capsule(pointer: int) -> object:
    """Wrap a raw ``TSLanguage *`` (old-style bindings) in the capsule tree-sitter expects."""
    return _capsule_new(pointer, _CAPSULE_NAME, None)


@functools.cache
def grammar(language: str) -> tree_sitter.Language | None:
    """Loaded tree-sitter grammar for ``language``, or None if none is bundled."""
    spec = _GRAMMARS.get(language)
    if spec is None:
        return None
    module_name, function_name = spec
    handle = getattr(importlib.import_module(module_name), function_name)()
    if isinstance(handle, int):
        # The canonical Dart binding still returns a raw pointer, which
        # tree-sitter 0.26 deprecates; give it the modern capsule instead.
        handle = _as_capsule(handle)
    return tree_sitter.Language(handle)


def grammar_languages() -> tuple[str, ...]:
    return tuple(_GRAMMARS)
