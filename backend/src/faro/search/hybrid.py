"""Hybrid search: semantic (vectors) + exact words (full text), fused with RRF.

Reciprocal Rank Fusion scores each chunk by ``sum(1 / (k + rank))`` over the
two rankings, so a chunk that ranks well in both wins, and neither score scale
dominates the other. In code, exact identifiers matter as much as meaning,
which is why both signals are combined.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from faro.indexing.embedder import Embedder
from faro.indexing.store import ChunkStore, in_filter
from faro.search import tokenize

RRF_K = 60
ORIGINS = ("code", "doc")


@dataclass(frozen=True)
class SearchHit:
    id: str
    root_id: str
    rel_path: str
    start_line: int
    end_line: int
    language: str
    symbol: str
    origin: str
    text: str
    score: float
    vector_rank: int | None
    text_rank: int | None
    vector_distance: float | None  # cosine distance (0 = identical); None if not retrieved
    text_score: float | None  # BM25 score; None if no exact-word match


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return scores


def _where(origin: str | None, root_ids: Sequence[str] | None) -> str | None:
    clauses: list[str] = []
    if origin is not None:
        if origin not in ORIGINS:
            raise ValueError(f"Unknown origin: {origin}")
        clauses.append(f"origin = '{origin}'")
    if root_ids:
        clauses.append(in_filter("root_id", root_ids))
    return " AND ".join(clauses) or None


def hybrid_search(
    store: ChunkStore,
    embedder: Embedder,
    query: str,
    *,
    limit: int = 8,
    candidates: int = 50,
    origin: str | None = None,
    root_ids: Sequence[str] | None = None,
) -> list[SearchHit]:
    if not query.strip():
        return []
    where = _where(origin, root_ids)
    by_vector = store.vector_search(embedder.embed_query(query), candidates, where)
    by_text = store.text_search(tokenize.text_query(query), candidates, where)
    rows: dict[str, dict[str, Any]] = {}
    vector_ranks: dict[str, int] = {}
    text_ranks: dict[str, int] = {}
    distances: dict[str, float] = {}
    text_scores: dict[str, float] = {}
    for rank, row in enumerate(by_vector, start=1):
        rows.setdefault(row["id"], row)
        vector_ranks[row["id"]] = rank
        distances[row["id"]] = float(row["_distance"])
    for rank, row in enumerate(by_text, start=1):
        rows.setdefault(row["id"], row)
        text_ranks[row["id"]] = rank
        text_scores[row["id"]] = float(row["_score"])
    scores = reciprocal_rank_fusion([[r["id"] for r in by_vector], [r["id"] for r in by_text]])
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:limit]
    return [
        SearchHit(
            id=chunk_id,
            root_id=rows[chunk_id]["root_id"],
            rel_path=rows[chunk_id]["rel_path"],
            start_line=int(rows[chunk_id]["start_line"]),
            end_line=int(rows[chunk_id]["end_line"]),
            language=rows[chunk_id]["language"],
            symbol=rows[chunk_id]["symbol"],
            origin=rows[chunk_id]["origin"],
            text=rows[chunk_id]["text"],
            score=scores[chunk_id],
            vector_rank=vector_ranks.get(chunk_id),
            text_rank=text_ranks.get(chunk_id),
            vector_distance=distances.get(chunk_id),
            text_score=text_scores.get(chunk_id),
        )
        for chunk_id in ordered
    ]
