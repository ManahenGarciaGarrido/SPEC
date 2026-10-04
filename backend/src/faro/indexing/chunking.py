"""Split source files into citable chunks.

Languages with a bundled tree-sitter grammar are split along syntax:

1. A node that fits the size budget becomes one chunk.
2. A node that does not fit is split into its children. Children are first
   grouped into *units*: comments, decorators/annotations and Dart signatures
   attach forward to the node they describe, so a doc comment, ``@override``
   and ``Future<void> login()`` always travel with the body that follows.
3. Consecutive units are packed together while they fit the budget.
4. Tiny pieces (a lone ``class Foo {`` line, an import block...) are merged
   with a neighbour.

Other languages fall back to overlapping windows of whole lines.

Every chunk covers whole lines, so ``start_line``/``end_line`` (1-based,
inclusive) are exactly what an editor shows, and carries a ``symbol`` such as
``AuthRepository > login`` computed from the syntax node the chunk is built
around.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import tree_sitter

from faro.indexing import languages

CHUNKER_VERSION = "1"

_MAX_DEPTH = 200
_MAX_NAME = 80


@dataclass(frozen=True)
class Chunk:
    start_line: int
    end_line: int
    text: str
    symbol: str


@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int = 1800
    min_chars: int = 300
    fallback_overlap_lines: int = 3


DEFAULT_CONFIG = ChunkingConfig()


@dataclass(frozen=True)
class _Piece:
    start: int  # 0-based, inclusive
    end: int
    anchor: tree_sitter.Node | None


def normalize_newlines(text: str) -> str:
    """Use ``\\n`` everywhere so line numbers match what editors show."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_lines(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def chunk_document(
    text: str, language: str, config: ChunkingConfig = DEFAULT_CONFIG
) -> list[Chunk]:
    text = normalize_newlines(text)
    lines = split_lines(text)
    if not any(line.strip() for line in lines):
        return []
    sizer = _Sizer(lines)
    grammar = languages.grammar(language)
    if grammar is None:
        windows = _line_windows(0, len(lines) - 1, sizer, config)
        pieces = [p for p in (_trim(_Piece(s, e, None), lines) for s, e in windows) if p]
        return [_make_chunk(lines, piece, "") for piece in pieces]

    tree = tree_sitter.Parser(grammar).parse(text.encode("utf-8"))
    namer = _Namer(language)
    splitter = _Splitter(sizer, config, namer)
    pieces = splitter.split(tree.root_node, 0)
    pieces = _remove_overlaps(pieces, lines)
    pieces = _merge_small(pieces, sizer, config, namer)
    return [_make_chunk(lines, piece, namer.describe(piece)) for piece in pieces]


class _Sizer:
    """Character size of line ranges in O(1) using prefix sums."""

    def __init__(self, lines: Sequence[str]) -> None:
        self._offsets = [0]
        for line in lines:
            self._offsets.append(self._offsets[-1] + len(line) + 1)

    def size(self, start: int, end: int) -> int:
        return self._offsets[end + 1] - self._offsets[start]


def _rows(node: tree_sitter.Node) -> tuple[int, int]:
    start = node.start_point.row
    end = node.end_point.row
    if node.end_point.column == 0 and end > start:
        end -= 1
    return start, end


def _attaches_forward(node: tree_sitter.Node, following: tree_sitter.Node) -> bool:
    kind = node.type
    if "comment" in kind or kind in ("decorator", "annotation", "marker_annotation"):
        return True
    # Dart: signatures and bodies are siblings.
    return following.type == "function_body"


def _units(children: Sequence[tree_sitter.Node]) -> list[list[tree_sitter.Node]]:
    units: list[list[tree_sitter.Node]] = []
    pending: list[tree_sitter.Node] = []
    for index, child in enumerate(children):
        pending.append(child)
        following = children[index + 1] if index + 1 < len(children) else None
        if following is not None and _attaches_forward(child, following):
            continue
        units.append(pending)
        pending = []
    if pending:
        units.append(pending)
    return units


class _Splitter:
    def __init__(self, sizer: _Sizer, config: ChunkingConfig, namer: _Namer) -> None:
        self._sizer = sizer
        self._config = config
        self._namer = namer

    def _fits(self, start: int, end: int) -> bool:
        return self._sizer.size(start, end) <= self._config.max_chars

    def split(self, node: tree_sitter.Node, depth: int) -> list[_Piece]:
        start, end = _rows(node)
        if self._fits(start, end):
            return [_Piece(start, end, node)]
        children = node.children
        if not children or depth >= _MAX_DEPTH:
            windows = _line_windows(start, end, self._sizer, self._config)
            return [_Piece(s, e, node) for s, e in windows]
        pieces: list[_Piece] = []
        current: _Piece | None = None
        for unit in _units(children):
            main = unit[-1]
            u_start = _rows(unit[0])[0]
            u_end = max(_rows(n)[1] for n in unit)
            if not self._fits(u_start, u_end):
                # The unit's prefix (doc comment, decorators, Dart signature) and a
                # small header packed just before it (``export async function f()``)
                # travel with the first piece of the body, even if that slightly
                # exceeds the budget: a body without its signature is hard to cite.
                head_start = u_start
                if current is not None and self._is_header_of(current, u_start):
                    head_start = current.start
                elif current is not None:
                    pieces.append(current)
                current = None
                body = self.split(main, depth + 1)
                first = body[0]
                anchor = main if self._namer.own_name(main) else first.anchor
                body[0] = _Piece(min(head_start, first.start), first.end, anchor)
                pieces.extend(body)
                continue
            if current is None:
                current = _Piece(u_start, u_end, main)
            elif self._fits(current.start, max(current.end, u_end)):
                anchor = current.anchor
                if not self._namer.own_name(anchor) and self._namer.own_name(main):
                    anchor = main
                current = _Piece(current.start, max(current.end, u_end), anchor)
            else:
                pieces.append(current)
                current = _Piece(u_start, u_end, main)
        if current is not None:
            pieces.append(current)
        # The piece that holds this node's header is best described by the node.
        if pieces and pieces[0].start <= start and self._namer.own_name(node):
            pieces[0] = _Piece(pieces[0].start, pieces[0].end, node)
        return pieces

    def _is_header_of(self, piece: _Piece, body_start: int) -> bool:
        """``piece`` introduces the body starting at ``body_start``.

        True when it shares the body's first line (``function f(...) {``), or is
        small and ends on the line just before it (``def f():``). Sibling
        definitions packed earlier do not qualify, so they are not absorbed.
        """
        if piece.end >= body_start:
            return True
        small = self._sizer.size(piece.start, piece.end) < self._config.min_chars
        return small and piece.end == body_start - 1


def _line_windows(
    start: int, end: int, sizer: _Sizer, config: ChunkingConfig
) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    first = start
    while first <= end:
        last = first
        while last + 1 <= end and sizer.size(first, last + 1) <= config.max_chars:
            last += 1
        windows.append((first, last))
        if last >= end:
            break
        first = max(last + 1 - config.fallback_overlap_lines, first + 1)
    return windows


def _trim(piece: _Piece, lines: Sequence[str]) -> _Piece | None:
    start, end = piece.start, piece.end
    while start <= end and not lines[start].strip():
        start += 1
    while end >= start and not lines[end].strip():
        end -= 1
    return _Piece(start, end, piece.anchor) if start <= end else None


def _remove_overlaps(pieces: Sequence[_Piece], lines: Sequence[str]) -> list[_Piece]:
    result: list[_Piece] = []
    previous_end = -1
    for piece in sorted(pieces, key=lambda p: (p.start, p.end)):
        trimmed = _trim(_Piece(max(piece.start, previous_end + 1), piece.end, piece.anchor), lines)
        if trimmed is None:
            continue
        result.append(trimmed)
        previous_end = trimmed.end
    return result


def _merge_small(
    pieces: Sequence[_Piece], sizer: _Sizer, config: ChunkingConfig, namer: _Namer
) -> list[_Piece]:
    def depth(piece: _Piece) -> int:
        return len(namer.chain(piece.anchor)) if piece.anchor is not None else -1

    def combine(first: _Piece, second: _Piece) -> _Piece:
        # Keep the more specific description (ties go to the first piece).
        anchor = first.anchor if depth(first) >= depth(second) else second.anchor
        return _Piece(first.start, second.end, anchor)

    result: list[_Piece] = []
    index = 0
    while index < len(pieces):
        current = pieces[index]
        while (
            sizer.size(current.start, current.end) < config.min_chars
            and index + 1 < len(pieces)
            and sizer.size(current.start, pieces[index + 1].end) <= config.max_chars
        ):
            index += 1
            current = combine(current, pieces[index])
        if (
            sizer.size(current.start, current.end) < config.min_chars
            and result
            and sizer.size(result[-1].start, current.end) <= config.max_chars
        ):
            result[-1] = combine(result[-1], current)
        else:
            result.append(current)
        index += 1
    return result


def _make_chunk(lines: Sequence[str], piece: _Piece, symbol: str) -> Chunk:
    return Chunk(
        start_line=piece.start + 1,
        end_line=piece.end + 1,
        text="\n".join(lines[piece.start : piece.end + 1]),
        symbol=symbol,
    )


# --- Symbols -----------------------------------------------------------------

NameFn = Callable[[tree_sitter.Node], "str | None"]


def _text(node: tree_sitter.Node | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = node.text.decode("utf-8", "replace").strip()
    return value[:_MAX_NAME] if value else None


def _field_name(node: tree_sitter.Node) -> str | None:
    return _text(node.child_by_field_name("name"))


def _first_child_of_type(*types: str) -> NameFn:
    def name(node: tree_sitter.Node) -> str | None:
        for child in node.named_children:
            if child.type in types:
                return _text(child)
        return None

    return name


def _dart_method(node: tree_sitter.Node) -> str | None:
    for child in node.named_children:
        found = _field_name(child)
        if found:
            return found
    return None


def _python_decorated(node: tree_sitter.Node) -> str | None:
    return _field_name(node.child_by_field_name("definition") or node)


_FUNCTION_VALUES = frozenset(
    {"arrow_function", "function_expression", "function", "class", "generator_function"}
)


def _js_declarator(node: tree_sitter.Node) -> str | None:
    value = node.child_by_field_name("value")
    if value is None or value.type not in _FUNCTION_VALUES:
        return None
    return _field_name(node)


def _markdown_section(node: tree_sitter.Node) -> str | None:
    for child in node.named_children:
        if child.type in ("atx_heading", "setext_heading"):
            heading = _text(child)
            if not heading:
                return None
            first_line = heading.splitlines()[0]
            return first_line.lstrip("#").strip() or None
    return None


def _key_field(node: tree_sitter.Node) -> str | None:
    key = _text(node.child_by_field_name("key"))
    return key.strip("\"'") if key else None


def _lua_assignment(node: tree_sitter.Node) -> str | None:
    for values in node.named_children:
        if values.type == "expression_list":
            if any(v.type == "function_definition" for v in values.named_children):
                return _first_child_of_type("variable_list")(node)
            return None
    return None


_JS_DEFS: dict[str, NameFn] = {
    "function_declaration": _field_name,
    "generator_function_declaration": _field_name,
    "class_declaration": _field_name,
    "abstract_class_declaration": _field_name,
    "method_definition": _field_name,
    "variable_declarator": _js_declarator,
}
_TS_DEFS: dict[str, NameFn] = {
    **_JS_DEFS,
    "interface_declaration": _field_name,
    "type_alias_declaration": _field_name,
    "enum_declaration": _field_name,
    "internal_module": _field_name,
    "abstract_method_signature": _field_name,
    "function_signature": _field_name,
}
_LUA_DEFS: dict[str, NameFn] = {
    "function_declaration": _field_name,
    "assignment_statement": _lua_assignment,
}

_DEFINITIONS: dict[str, dict[str, NameFn]] = {
    "python": {
        "class_definition": _field_name,
        "function_definition": _field_name,
        "decorated_definition": _python_decorated,
    },
    "javascript": _JS_DEFS,
    "typescript": _TS_DEFS,
    "tsx": _TS_DEFS,
    "dart": {
        "class_definition": _field_name,
        "mixin_declaration": _first_child_of_type("identifier"),
        "extension_declaration": _field_name,
        "enum_declaration": _field_name,
        "type_alias": _first_child_of_type("type_identifier"),
        "function_signature": _field_name,
        "getter_signature": _field_name,
        "setter_signature": _field_name,
        "constructor_signature": _field_name,
        "method_signature": _dart_method,
    },
    "lua": _LUA_DEFS,
    "luau": {**_LUA_DEFS, "type_definition": _first_child_of_type("identifier")},
    "markdown": {"section": _markdown_section},
    "yaml": {"block_mapping_pair": _key_field},
    "json": {"pair": _key_field},
}


class _Namer:
    def __init__(self, language: str) -> None:
        self._defs = _DEFINITIONS.get(language, {})

    def _name(self, node: tree_sitter.Node) -> str | None:
        fn = self._defs.get(node.type)
        return fn(node) if fn is not None else None

    def own_name(self, node: tree_sitter.Node | None) -> str | None:
        """Name of the definition ``node`` is (a Dart body takes its signature's name)."""
        if node is None or not self._defs:
            return None
        name = self._name(node)
        if name is None and node.type == "function_body":
            previous = node.prev_named_sibling
            if previous is not None:
                name = self._name(previous)
        return name

    def chain(self, node: tree_sitter.Node) -> list[str]:
        names: list[str] = []
        current: tree_sitter.Node | None = node
        while current is not None:
            name = self.own_name(current)
            if name:
                names.append(name)
            current = current.parent
        names.reverse()
        return names

    def describe(self, piece: _Piece) -> str:
        anchor = piece.anchor
        if anchor is None or not self._defs:
            return ""
        names = self.chain(anchor)
        if not self.own_name(anchor):
            # e.g. a whole small file anchored at the root: name its first definition.
            for child in anchor.named_children:
                row = child.start_point.row
                if row < piece.start:
                    continue
                if row > piece.end:
                    break
                name = self.own_name(child)
                if name:
                    names.append(name)
                    break
        return " > ".join(names)
