"""LanceDB table holding every chunk with its vector and its searchable text."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Sequence
from typing import Any

import lancedb
import numpy as np
import pyarrow as pa
from lancedb.index import FTS
from lancedb.query import LanceVectorQueryBuilder

from faro.indexing.embedder import Vector

TABLE = "chunks"
SCHEMA_VERSION = "1"

RESULT_COLUMNS = [
    "id",
    "file_id",
    "root_id",
    "origin",
    "rel_path",
    "language",
    "start_line",
    "end_line",
    "symbol",
    "text",
]

_HEX = re.compile(r"[0-9a-f]+")
_DELETE_BATCH = 500


def table_exists(db: lancedb.DBConnection, name: str = TABLE) -> bool:
    """Whether ``name`` exists, walking every page of the (paginated) table listing."""
    response = db.list_tables()
    while True:
        if name in response.tables:
            return True
        if not response.page_token:
            return False
        response = db.list_tables(page_token=response.page_token)


def schema(dim: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("file_id", pa.string(), nullable=False),
            pa.field("root_id", pa.string(), nullable=False),
            pa.field("origin", pa.string(), nullable=False),
            pa.field("rel_path", pa.string(), nullable=False),
            pa.field("language", pa.string(), nullable=False),
            pa.field("start_line", pa.int32(), nullable=False),
            pa.field("end_line", pa.int32(), nullable=False),
            pa.field("symbol", pa.string(), nullable=False),
            pa.field("text", pa.string(), nullable=False),
            pa.field("search_text", pa.string(), nullable=False),
            pa.field("vector", pa.list_(pa.float32(), dim), nullable=False),
        ]
    )


def _hex_list(values: Iterable[str]) -> list[str]:
    checked = list(values)
    for value in checked:
        if not _HEX.fullmatch(value):
            raise ValueError(f"Not a hexadecimal identifier: {value!r}")
    return checked


def in_filter(column: str, values: Iterable[str]) -> str:
    """SQL filter ``column IN (...)`` for hexadecimal identifiers only (no injection)."""
    quoted = ", ".join(f"'{v}'" for v in _hex_list(values))
    return f"{column} IN ({quoted})"


class ChunkStore:
    def __init__(self, db: lancedb.DBConnection, dim: int) -> None:
        self._db = db
        self._dim = dim
        self._table: lancedb.table.Table | None = db.open_table(TABLE) if table_exists(db) else None
        if self._table is not None:
            vector_type = self._table.schema.field("vector").type
            if getattr(vector_type, "list_size", dim) != dim:
                raise ValueError("The index was built with a different vector size")

    @property
    def dim(self) -> int:
        return self._dim

    def _require(self) -> lancedb.table.Table:
        if self._table is None:
            self._table = self._db.create_table(TABLE, schema=schema(self._dim))
        return self._table

    def count(self) -> int:
        return 0 if self._table is None else int(self._table.count_rows())

    def add(self, rows: Sequence[dict[str, Any]]) -> None:
        if rows:
            self._require().add(list(rows))

    def delete_files(self, file_ids: Iterable[str]) -> None:
        if self._table is None:
            return
        ids = _hex_list(file_ids)
        for start in range(0, len(ids), _DELETE_BATCH):
            self._table.delete(in_filter("file_id", ids[start : start + _DELETE_BATCH]))

    def delete_root(self, root_id: str) -> None:
        if self._table is not None:
            self._table.delete(in_filter("root_id", [root_id]))

    def drop(self) -> None:
        if table_exists(self._db):
            self._db.drop_table(TABLE)
        self._table = None

    def has_text_index(self) -> bool:
        if self._table is None:
            return False
        return any(index.index_type == "FTS" for index in self._table.list_indices())

    def finalize(self) -> None:
        """Build the text index if missing, then compact and fold new rows into it."""
        if self._table is None or self.count() == 0:
            return
        if not self.has_text_index():
            self._table.create_index(
                "search_text",
                config=FTS(
                    base_tokenizer="simple",
                    lower_case=True,
                    stem=False,
                    remove_stop_words=False,
                    ascii_folding=True,
                    with_position=False,
                ),
                replace=True,
            )
        self._table.optimize(cleanup_older_than=dt.timedelta(0))

    def vector_search(
        self, vector: Vector, limit: int, where: str | None = None
    ) -> list[dict[str, Any]]:
        if self._table is None or self.count() == 0:
            return []
        builder = self._table.search(
            np.asarray(vector, dtype=np.float32), vector_column_name="vector"
        )
        if not isinstance(builder, LanceVectorQueryBuilder):
            raise TypeError("LanceDB did not return a vector query")
        query = builder.distance_type("cosine").select([*RESULT_COLUMNS, "_distance"]).limit(limit)
        if where:
            query = query.where(where, prefilter=True)
        return list(query.to_list())

    def text_search(self, text: str, limit: int, where: str | None = None) -> list[dict[str, Any]]:
        table = self._table
        if table is None or not text.strip() or not self.has_text_index():
            return []
        query = (
            table.search(text, query_type="fts", fts_columns="search_text")
            .select([*RESULT_COLUMNS, "_score"])
            .limit(limit)
        )
        if where:
            query = query.where(where, prefilter=True)
        return list(query.to_list())
