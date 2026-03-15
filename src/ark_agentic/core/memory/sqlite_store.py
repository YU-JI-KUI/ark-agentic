"""
SQLite Memory Store

统一向量搜索 (sqlite-vec) + 关键词搜索 (FTS5 + jieba) + embedding cache
+ 文件追踪 + 元数据管理，单个 .db 文件 per user。

参考: openclaw-main/src/memory/manager.ts, memory-schema.ts
"""

from __future__ import annotations

import json
import logging
import os
import string
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .types import MemoryChunk, MemorySearchResult, MemorySource

logger = logging.getLogger(__name__)

SNIPPET_MAX_CHARS = 500
META_KEY = "memory_index_meta_v1"

_PUNCTUATION = string.punctuation + "，。！？、；：""''（）【】《》…—·"


# ============ Config ============


@dataclass
class SQLiteStoreConfig:
    db_name: str = "memory.db"
    vector_weight: float = 0.7
    keyword_weight: float = 0.3
    vector_top_k: int = 20
    keyword_top_k: int = 20
    min_score: float = 0.1


@dataclass
class IndexMeta:
    model: str = ""
    dims: int = 0
    chunk_size: int = 500
    chunk_overlap: int = 50

    def to_json(self) -> str:
        return json.dumps(
            {
                "model": self.model,
                "dims": self.dims,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> IndexMeta:
        d = json.loads(raw)
        return cls(
            model=d.get("model", ""),
            dims=d.get("dims", 0),
            chunk_size=d.get("chunk_size", 500),
            chunk_overlap=d.get("chunk_overlap", 50),
        )


# ============ Helpers ============


def _is_punctuation(text: str) -> bool:
    return all(c in _PUNCTUATION for c in text)


def _embedding_to_json(embedding: list[float] | None) -> str | None:
    if embedding is None:
        return None
    return json.dumps(embedding)


def _embedding_from_json(raw: str | None) -> list[float] | None:
    if raw is None:
        return None
    return json.loads(raw)


def _embedding_to_blob(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


def _get_sqlite_module():
    """stdlib sqlite3 first (if load_extension works), then sqlean, then stdlib without extensions."""
    import sqlite3 as stdlib

    try:
        conn = stdlib.connect(":memory:")
        conn.enable_load_extension(True)
        conn.close()
        return stdlib
    except Exception:
        pass
    try:
        import sqlean  # type: ignore[import-untyped]

        return sqlean
    except ImportError:
        logger.info(
            "sqlite3 extension loading unavailable and sqlean not installed; "
            "sqlite-vec will be disabled (cosine fallback active)"
        )
        return stdlib


def _swap_db_files(main_path: str, temp_path: str) -> None:
    suffixes = ["", "-wal", "-shm"]
    backup = f"{main_path}.bak-{uuid4().hex[:8]}"
    for s in suffixes:
        src = Path(f"{main_path}{s}")
        if src.exists():
            src.rename(Path(f"{backup}{s}"))
    for s in suffixes:
        src = Path(f"{temp_path}{s}")
        if src.exists():
            src.rename(Path(f"{main_path}{s}"))
    for s in suffixes:
        bak = Path(f"{backup}{s}")
        if bak.exists():
            bak.unlink()


def _remove_db_files(path: str) -> None:
    for s in ("", "-wal", "-shm"):
        p = Path(f"{path}{s}")
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


# ============ SQLiteMemoryStore ============


class SQLiteMemoryStore:
    """Unified SQLite store: vec search + FTS5 keyword + embedding cache."""

    def __init__(
        self,
        db_path: str,
        config: SQLiteStoreConfig | None = None,
        dimensions: int = 768,
    ) -> None:
        self._db_path = db_path
        self._config = config or SQLiteStoreConfig()
        self._dimensions = dimensions
        self._conn: Any = None
        self._vec_available: bool = False
        self._jieba: Any = None
        self._open(db_path)

    # ---- Connection ----

    def _open(self, db_path: str) -> None:
        sqlite3 = _get_sqlite_module()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row if hasattr(sqlite3, "Row") else None
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._load_vec_extension()
        self._ensure_schema()

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ---- sqlite-vec ----

    def _load_vec_extension(self) -> None:
        try:
            import sqlite_vec  # type: ignore[import-untyped]

            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._vec_available = True
        except Exception as e:
            logger.warning("sqlite-vec unavailable, falling back to cosine: %s", e)
            self._vec_available = False

    # ---- Schema ----

    def _ensure_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'memory',
                hash TEXT NOT NULL,
                mtime_ms REAL,
                size INTEGER
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'memory',
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                hash TEXT NOT NULL,
                text TEXT NOT NULL,
                embedding TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS embedding_cache (
                model TEXT NOT NULL,
                hash TEXT NOT NULL,
                embedding TEXT NOT NULL,
                dims INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (model, hash)
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
            """
        )
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                "text, id UNINDEXED, path UNINDEXED, source UNINDEXED)"
            )
        except Exception as e:
            logger.warning("FTS5 unavailable: %s", e)

        self._ensure_column("files", "source", "TEXT NOT NULL DEFAULT 'memory'")
        self._ensure_column("chunks", "source", "TEXT NOT NULL DEFAULT 'memory'")

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = [r[1] if isinstance(r, (list, tuple)) else r["name"] for r in rows]
        if column in names:
            return
        self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _ensure_vector_table(self, dims: int) -> None:
        if not self._vec_available:
            return
        stored_meta = self.read_meta()
        stored_dims = stored_meta.dims if stored_meta else None
        if stored_dims and stored_dims != dims:
            try:
                self._conn.execute("DROP TABLE IF EXISTS chunks_vec")
            except Exception:
                pass
            logger.warning("Vector dims changed %s->%s, rebuilding vec table", stored_dims, dims)
        try:
            self._conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec "
                f"USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[{dims}])"
            )
        except Exception as e:
            logger.warning("Failed to create vec table: %s", e)
            self._vec_available = False

    # ---- jieba ----

    def _ensure_jieba(self) -> Any:
        if self._jieba is None:
            try:
                import jieba

                jieba.setLogLevel(logging.WARNING)
                self._jieba = jieba
            except ImportError:
                raise ImportError("jieba is required. Install with: uv add jieba")
        return self._jieba

    def _jieba_tokenize_for_fts(self, text: str) -> str:
        jb = self._ensure_jieba()
        tokens = jb.lcut(text)
        return " ".join(
            t.lower() for t in tokens if len(t) > 1 and not t.isdigit() and not _is_punctuation(t)
        )

    def _build_fts_query(self, raw: str) -> str | None:
        jb = self._ensure_jieba()
        tokens = jb.lcut(raw)
        meaningful = [
            t.lower()
            for t in tokens
            if len(t) > 1 and not t.isdigit() and not _is_punctuation(t)
        ]
        if not meaningful:
            return None
        return " AND ".join(f'"{t.replace(chr(34), "")}"' for t in meaningful)

    # ---- BM25 score ----

    @staticmethod
    def _bm25_rank_to_score(rank: float) -> float:
        """FTS5 bm25() returns negative values; more negative = more relevant."""
        if rank != rank:  # NaN
            return 0.0
        if rank < 0:
            relevance = -rank
            return relevance / (1 + relevance)
        return 1.0 / (1 + rank)

    # ---- CRUD ----

    def add(self, chunks: list[MemoryChunk]) -> None:
        if not chunks:
            return
        self._conn.execute("BEGIN")
        try:
            for chunk in chunks:
                self._conn.execute(
                    "INSERT OR REPLACE INTO chunks "
                    "(id, path, source, start_line, end_line, hash, text, embedding, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
                    (
                        chunk.id,
                        chunk.path,
                        chunk.source.value,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.content_hash,
                        chunk.text,
                        _embedding_to_json(chunk.embedding),
                    ),
                )
                # Delete existing FTS row before insert (FTS5 doesn't support OR REPLACE)
                self._conn.execute(
                    "DELETE FROM chunks_fts WHERE id = ?", (chunk.id,)
                )
                fts_text = self._jieba_tokenize_for_fts(chunk.text)
                self._conn.execute(
                    "INSERT INTO chunks_fts (text, id, path, source) VALUES (?,?,?,?)",
                    (fts_text, chunk.id, chunk.path, chunk.source.value),
                )
                if self._vec_available and chunk.embedding:
                    blob = _embedding_to_blob(chunk.embedding)
                    self._conn.execute(
                        "DELETE FROM chunks_vec WHERE id = ?", (chunk.id,)
                    )
                    self._conn.execute(
                        "INSERT INTO chunks_vec (id, embedding) VALUES (?,?)",
                        (chunk.id, blob),
                    )
            self._conn.execute("COMMIT")
        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

    def delete_by_path(self, path: str) -> None:
        ids = [
            r[0] if isinstance(r, (list, tuple)) else r["id"]
            for r in self._conn.execute(
                "SELECT id FROM chunks WHERE path = ?", (path,)
            ).fetchall()
        ]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", ids)
            self._conn.execute(f"DELETE FROM chunks_fts WHERE id IN ({placeholders})", ids)
            if self._vec_available:
                try:
                    self._conn.execute(
                        f"DELETE FROM chunks_vec WHERE id IN ({placeholders})", ids
                    )
                except Exception:
                    pass
            self._conn.execute("COMMIT")
        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

    def clear(self) -> None:
        self._conn.execute("DELETE FROM chunks")
        try:
            self._conn.execute("DELETE FROM chunks_fts")
        except Exception:
            pass
        if self._vec_available:
            try:
                self._conn.execute("DROP TABLE IF EXISTS chunks_vec")
            except Exception:
                pass
        self._conn.execute("DELETE FROM files")

    def get_chunk(self, chunk_id: str) -> MemoryChunk | None:
        row = self._conn.execute(
            "SELECT id, path, source, start_line, end_line, hash, text, embedding "
            "FROM chunks WHERE id = ?",
            (chunk_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_chunk(row)

    def get_all_chunks(self) -> list[MemoryChunk]:
        rows = self._conn.execute(
            "SELECT id, path, source, start_line, end_line, hash, text, embedding FROM chunks"
        ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def _row_to_chunk(self, row: Any) -> MemoryChunk:
        if isinstance(row, (list, tuple)):
            return MemoryChunk(
                id=row[0],
                path=row[1],
                source=MemorySource(row[2]) if row[2] else MemorySource.MEMORY,
                start_line=row[3],
                end_line=row[4],
                text=row[6],
                embedding=_embedding_from_json(row[7]),
            )
        return MemoryChunk(
            id=row["id"],
            path=row["path"],
            source=MemorySource(row["source"]) if row["source"] else MemorySource.MEMORY,
            start_line=row["start_line"],
            end_line=row["end_line"],
            text=row["text"],
            embedding=_embedding_from_json(row["embedding"]),
        )

    # ---- Vector search ----

    def vector_search(
        self, query_embedding: list[float], top_k: int = 10
    ) -> list[tuple[MemoryChunk, float]]:
        if self._vec_available:
            return self._vec_table_search(query_embedding, top_k)
        return self._fallback_cosine_search(query_embedding, top_k)

    def _vec_table_search(
        self, query_embedding: list[float], top_k: int
    ) -> list[tuple[MemoryChunk, float]]:
        blob = _embedding_to_blob(query_embedding)
        try:
            rows = self._conn.execute(
                "SELECT c.id, c.path, c.source, c.start_line, c.end_line, "
                "c.hash, c.text, c.embedding, "
                "vec_distance_cosine(v.embedding, ?) AS dist "
                "FROM chunks_vec v JOIN chunks c ON c.id = v.id "
                "ORDER BY dist ASC LIMIT ?",
                (blob, top_k),
            ).fetchall()
        except Exception as e:
            logger.warning("vec search failed, falling back to cosine: %s", e)
            return self._fallback_cosine_search(query_embedding, top_k)

        results: list[tuple[MemoryChunk, float]] = []
        for r in rows:
            chunk = self._row_to_chunk(r)
            dist = r[8] if isinstance(r, (list, tuple)) else r["dist"]
            score = 1.0 - float(dist)
            results.append((chunk, score))
        return results

    def _fallback_cosine_search(
        self, query_embedding: list[float], top_k: int
    ) -> list[tuple[MemoryChunk, float]]:
        import numpy as np

        rows = self._conn.execute(
            "SELECT id, path, source, start_line, end_line, hash, text, embedding "
            "FROM chunks WHERE embedding IS NOT NULL"
        ).fetchall()
        if not rows:
            return []

        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm < 1e-10:
            return []
        q = q / q_norm

        scored: list[tuple[MemoryChunk, float]] = []
        for r in rows:
            emb_json = r[7] if isinstance(r, (list, tuple)) else r["embedding"]
            emb = _embedding_from_json(emb_json)
            if emb is None:
                continue
            v = np.array(emb, dtype=np.float32)
            v_norm = np.linalg.norm(v)
            if v_norm < 1e-10:
                continue
            cos = float(np.dot(q, v / v_norm))
            scored.append((self._row_to_chunk(r), cos))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # ---- Keyword search ----

    def keyword_search(
        self, query: str, top_k: int = 10
    ) -> list[tuple[MemoryChunk, float]]:
        fts_query = self._build_fts_query(query)
        if fts_query is None:
            return []
        try:
            rows = self._conn.execute(
                "SELECT f.id, c.path, c.source, c.start_line, c.end_line, "
                "c.hash, c.text, c.embedding, bm25(chunks_fts) AS rank "
                "FROM chunks_fts f JOIN chunks c ON c.id = f.id "
                "WHERE chunks_fts MATCH ? ORDER BY rank ASC LIMIT ?",
                (fts_query, top_k),
            ).fetchall()
        except Exception:
            logger.warning("FTS5 query failed for: %r", query, exc_info=True)
            return []

        results: list[tuple[MemoryChunk, float]] = []
        for r in rows:
            chunk = self._row_to_chunk(r)
            rank = r[8] if isinstance(r, (list, tuple)) else r["rank"]
            score = self._bm25_rank_to_score(float(rank))
            results.append((chunk, score))
        return results

    # ---- Hybrid search ----

    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int = 10,
        min_score: float | None = None,
    ) -> list[MemorySearchResult]:
        cfg = self._config
        min_s = min_score if min_score is not None else cfg.min_score

        vector_results = self.vector_search(query_embedding, cfg.vector_top_k)
        keyword_results = self.keyword_search(query, cfg.keyword_top_k)

        merged: dict[str, dict[str, Any]] = {}
        for chunk, score in vector_results:
            merged[chunk.id] = {"chunk": chunk, "vector_score": score, "keyword_score": 0.0}
        for chunk, score in keyword_results:
            if chunk.id in merged:
                merged[chunk.id]["keyword_score"] = score
            else:
                merged[chunk.id] = {"chunk": chunk, "vector_score": 0.0, "keyword_score": score}

        results: list[MemorySearchResult] = []
        seen: set[str] = set()
        for entry in merged.values():
            chunk: MemoryChunk = entry["chunk"]
            vs: float = entry["vector_score"]
            ks: float = entry["keyword_score"]
            final = cfg.vector_weight * vs + cfg.keyword_weight * ks
            if final < min_s:
                continue
            content_hash = chunk.content_hash
            if content_hash in seen:
                continue
            seen.add(content_hash)
            results.append(
                MemorySearchResult.from_chunk(chunk, final, vector_score=vs, keyword_score=ks)
            )

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    # ---- File tracking ----

    def get_file_hash(self, path: str) -> str | None:
        row = self._conn.execute(
            "SELECT hash FROM files WHERE path = ?", (path,)
        ).fetchone()
        if row is None:
            return None
        return row[0] if isinstance(row, (list, tuple)) else row["hash"]

    def set_file_hash(
        self, path: str, hash_val: str, source: str = "memory",
        mtime_ms: float = 0.0, size: int = 0,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO files (path, source, hash, mtime_ms, size) "
            "VALUES (?,?,?,?,?)",
            (path, source, hash_val, mtime_ms, size),
        )
        self._conn.commit()

    # ---- Embedding cache ----

    def get_cached_embeddings(
        self, model: str, hashes: list[str]
    ) -> dict[str, list[float]]:
        if not hashes:
            return {}
        result: dict[str, list[float]] = {}
        batch_size = 400
        for start in range(0, len(hashes), batch_size):
            batch = hashes[start : start + batch_size]
            placeholders = ",".join("?" for _ in batch)
            rows = self._conn.execute(
                f"SELECT hash, embedding FROM embedding_cache "
                f"WHERE model = ? AND hash IN ({placeholders})",
                [model] + batch,
            ).fetchall()
            for r in rows:
                h = r[0] if isinstance(r, (list, tuple)) else r["hash"]
                emb_raw = r[1] if isinstance(r, (list, tuple)) else r["embedding"]
                result[h] = json.loads(emb_raw)
        return result

    def set_cached_embeddings(
        self, model: str, entries: list[tuple[str, list[float]]]
    ) -> None:
        if not entries:
            return
        self._conn.execute("BEGIN")
        try:
            for content_hash, embedding in entries:
                self._conn.execute(
                    "INSERT OR REPLACE INTO embedding_cache "
                    "(model, hash, embedding, dims, updated_at) "
                    "VALUES (?,?,?,?,datetime('now'))",
                    (model, content_hash, json.dumps(embedding), len(embedding)),
                )
            self._conn.execute("COMMIT")
        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

    # ---- Meta ----

    def read_meta(self) -> IndexMeta | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (META_KEY,)
        ).fetchone()
        if row is None:
            return None
        raw = row[0] if isinstance(row, (list, tuple)) else row["value"]
        try:
            return IndexMeta.from_json(raw)
        except Exception:
            return None

    def write_meta(self, meta: IndexMeta) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
            (META_KEY, meta.to_json()),
        )
        self._conn.commit()

    # ---- Atomic reindex ----

    def safe_reindex(self, chunks: list[MemoryChunk], meta: IndexMeta) -> None:
        temp_path = f"{self._db_path}.tmp-{uuid4().hex[:8]}"
        temp_store = SQLiteMemoryStore(temp_path, self._config, self._dimensions)
        try:
            if self._dimensions > 0:
                temp_store._ensure_vector_table(self._dimensions)
            temp_store._seed_embedding_cache_from(self._conn)
            temp_store.add(chunks)
            temp_store.write_meta(meta)
            temp_store.close()
            self.close()
            _swap_db_files(self._db_path, temp_path)
            self._open(self._db_path)
            if self._dimensions > 0:
                self._ensure_vector_table(self._dimensions)
        except Exception:
            _remove_db_files(temp_path)
            if self._conn is None:
                self._open(self._db_path)
            raise

    def _seed_embedding_cache_from(self, source_conn: Any) -> None:
        try:
            rows = source_conn.execute(
                "SELECT model, hash, embedding, dims, updated_at FROM embedding_cache"
            ).fetchall()
        except Exception:
            return
        if not rows:
            return
        self._conn.execute("BEGIN")
        try:
            for r in rows:
                if isinstance(r, (list, tuple)):
                    vals = (r[0], r[1], r[2], r[3], r[4])
                else:
                    vals = (r["model"], r["hash"], r["embedding"], r["dims"], r["updated_at"])
                self._conn.execute(
                    "INSERT OR REPLACE INTO embedding_cache "
                    "(model, hash, embedding, dims, updated_at) VALUES (?,?,?,?,?)",
                    vals,
                )
            self._conn.execute("COMMIT")
        except Exception:
            try:
                self._conn.execute("ROLLBACK")
            except Exception:
                pass

    # ---- Properties ----

    @property
    def chunk_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return row[0] if row else 0

    @property
    def size(self) -> int:
        return self.chunk_count

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def vec_available(self) -> bool:
        return self._vec_available
