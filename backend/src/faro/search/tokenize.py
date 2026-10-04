"""Make identifiers searchable word by word.

``getUserById``, ``get_user_by_id`` and ``GetUserByID`` are indexed both as
written and split into ``get user by id``, so a query can match either the
exact identifier or its words.
"""

from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"\w+")
_MAX_QUERY_TERMS = 64

# Function words of a question carry no signal for exact-word search and, in a
# Spanish question over English code, they only match unrelated Spanish comments
# (measured: they pushed the right file out of the top 3). Removed from queries
# only, never from the index, so identifiers are untouched. Compared accent-free.
_QUERY_STOPWORDS = frozenset(
    """
    a al algo algun alguna algunas alguno algunos ante antes aqui asi bajo cada como con
    contra cual cuales cuando de del desde donde dos el ella ellas ello ellos en entre era
    eres es esa esas ese eso esos esta estan estas este esto estos fue fueron ha han hay
    hace hacer hacen la las le les lo los mas me mi mis mucho muy nada ni no nos o otra
    otro para pero poco por porque puede pueden que quien se segun ser si sin sobre son
    su sus tambien tan te tiene tienen todo todos tu tus un una unas uno unos usa usar y ya
    about above after an and any are as at be been being but by can could did do does
    doing during each for from had has have having he her here how i if in into is it its
    me more most my no not of off on once only or other our out over own same she should
    so some such than that the their them then there these they this those through to
    too under until up very was we were what when where which while who whom why will with
    would you your
    """.split()  # noqa: SIM905 - a word block reads better than a list literal
)


def _fold(term: str) -> str:
    decomposed = unicodedata.normalize("NFD", term.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def split_identifier(token: str) -> list[str]:
    """Split on ``_``, lower-to-upper changes, letter/digit changes and acronym ends.

    Unicode-aware (``str.isupper``/``islower``), so ``validaciónDeUsuario`` gives
    ``validación De Usuario``.
    """
    parts: list[str] = []
    for segment in token.split("_"):
        if not segment:
            continue
        current = segment[0]
        for index in range(1, len(segment)):
            previous, char = segment[index - 1], segment[index]
            following = segment[index + 1] if index + 1 < len(segment) else ""
            boundary = (
                (previous.islower() and char.isupper())
                or (previous.isdigit() != char.isdigit())
                or (previous.isupper() and char.isupper() and following.islower())
            )
            if boundary:
                parts.append(current)
                current = char
            else:
                current += char
        parts.append(current)
    return parts


def expand(text: str) -> list[str]:
    terms: list[str] = []
    for match in _WORD.finditer(text):
        token = match.group()
        terms.append(token)
        parts = split_identifier(token)
        if len(parts) > 1:
            terms.extend(parts)
    return terms


def search_text(*fields: str) -> str:
    """Text stored in the full-text index for a chunk."""
    return " ".join(term for field in fields for term in expand(field))


def text_query(query: str) -> str:
    """Full-text query: expanded terms, deduplicated, without operator characters."""
    seen: dict[str, None] = {}
    for term in expand(query):
        if _fold(term) not in _QUERY_STOPWORDS:
            seen.setdefault(term.lower(), None)
    return " ".join(list(seen)[:_MAX_QUERY_TERMS])
