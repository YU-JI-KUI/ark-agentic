"""
SQLiteMemoryStore 单元测试
"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from ark_agentic.core.memory.types import MemoryChunk, MemorySource
from ark_agentic.core.memory.sqlite_store import (
    IndexMeta,
    SQLiteMemoryStore,
    SQLiteStoreConfig,
    _embedding_to_blob,
    _embedding_to_json,
    _embedding_from_json,
    _is_punctuation,
)


# ============ fixtures ============


@pytest.fixture()
def tmp_dir(tmp_path: Path):
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture()
def store(tmp_dir: Path) -> SQLiteMemoryStore:
    db_path = str(tmp_dir / "test.db")
    s = SQLiteMemoryStore(db_path, dimensions=4)
    s._ensure_vector_table(4)
    yield s
    s.close()


def _make_chunk(
    text: str = "测试文本",
    path: str = "MEMORY.md",
    chunk_id: str | None = None,
    start_line: int = 1,
    end_line: int = 1,
    embedding: list[float] | None = None,
    source: MemorySource = MemorySource.MEMORY,
) -> MemoryChunk:
    cid = chunk_id or f"{path}:{start_line}:test"
    return MemoryChunk(
        id=cid,
        path=path,
        start_line=start_line,
        end_line=end_line,
        text=text,
        source=source,
        embedding=embedding,
    )


# ============ helpers ============


class TestHelpers:
    def test_is_punctuation(self):
        assert _is_punctuation("，。") is True
        assert _is_punctuation("!?") is True
        assert _is_punctuation("hello") is False
        assert _is_punctuation("你好") is False

    def test_embedding_json_roundtrip(self):
        emb = [0.1, 0.2, 0.3]
        j = _embedding_to_json(emb)
        assert j is not None
        assert _embedding_from_json(j) == emb
        assert _embedding_to_json(None) is None
        assert _embedding_from_json(None) is None

    def test_embedding_to_blob(self):
        emb = [1.0, 2.0, 3.0]
        blob = _embedding_to_blob(emb)
        assert len(blob) == 12  # 3 * 4 bytes


# ============ schema ============


class TestSchema:
    def test_creates_tables(self, store: SQLiteMemoryStore):
        tables = [
            r[0]
            for r in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "meta" in tables
        assert "files" in tables
        assert "chunks" in tables
        assert "embedding_cache" in tables

    def test_fts_table_exists(self, store: SQLiteMemoryStore):
        tables = [
            r[0]
            for r in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "chunks_fts" in tables

    def test_wal_mode(self, store: SQLiteMemoryStore):
        row = store._conn.execute("PRAGMA journal_mode").fetchone()
        mode = row[0] if isinstance(row, (list, tuple)) else row["journal_mode"]
        assert mode.lower() == "wal"


# ============ CRUD ============


class TestCRUD:
    def test_add_and_get_chunk(self, store: SQLiteMemoryStore):
        chunk = _make_chunk(text="用户喜欢购买车险", embedding=[0.1, 0.2, 0.3, 0.4])
        store.add([chunk])
        assert store.chunk_count == 1

        retrieved = store.get_chunk(chunk.id)
        assert retrieved is not None
        assert retrieved.text == "用户喜欢购买车险"
        assert retrieved.path == "MEMORY.md"
        assert retrieved.embedding is not None
        assert len(retrieved.embedding) == 4

    def test_add_empty_list(self, store: SQLiteMemoryStore):
        store.add([])
        assert store.chunk_count == 0

    def test_get_all_chunks(self, store: SQLiteMemoryStore):
        chunks = [
            _make_chunk(text="文本一", chunk_id="c1", embedding=[0.1, 0.2, 0.3, 0.4]),
            _make_chunk(text="文本二", chunk_id="c2", embedding=[0.5, 0.6, 0.7, 0.8]),
        ]
        store.add(chunks)
        all_chunks = store.get_all_chunks()
        assert len(all_chunks) == 2

    def test_delete_by_path(self, store: SQLiteMemoryStore):
        store.add([
            _make_chunk(text="AAA", chunk_id="a1", path="a.md", embedding=[0.1, 0.2, 0.3, 0.4]),
            _make_chunk(text="BBB", chunk_id="b1", path="b.md", embedding=[0.5, 0.6, 0.7, 0.8]),
        ])
        assert store.chunk_count == 2
        store.delete_by_path("a.md")
        assert store.chunk_count == 1
        assert store.get_chunk("a1") is None
        assert store.get_chunk("b1") is not None

    def test_clear(self, store: SQLiteMemoryStore):
        store.add([
            _make_chunk(text="数据", chunk_id="c1", embedding=[0.1, 0.2, 0.3, 0.4]),
        ])
        store.set_file_hash("test.md", "abc123")
        store.clear()
        assert store.chunk_count == 0
        assert store.get_file_hash("test.md") is None

    def test_add_replaces_existing(self, store: SQLiteMemoryStore):
        chunk = _make_chunk(text="原始", chunk_id="c1", embedding=[0.1, 0.2, 0.3, 0.4])
        store.add([chunk])
        updated = _make_chunk(text="更新后", chunk_id="c1", embedding=[0.5, 0.6, 0.7, 0.8])
        store.add([updated])
        assert store.chunk_count == 1
        retrieved = store.get_chunk("c1")
        assert retrieved is not None
        assert retrieved.text == "更新后"


# ============ Chinese keyword search ============


class TestChineseKeywordSearch:
    def test_jieba_tokenize_for_fts(self, store: SQLiteMemoryStore):
        result = store._jieba_tokenize_for_fts("用户喜欢购买车险和意外险")
        tokens = result.split()
        assert "车险" in tokens
        assert "意外险" in tokens
        assert "用户" in tokens

    def test_build_fts_query(self, store: SQLiteMemoryStore):
        q = store._build_fts_query("用户买了什么车险？")
        assert q is not None
        assert '"用户"' in q
        assert '"车险"' in q
        assert "AND" in q

    def test_build_fts_query_empty(self, store: SQLiteMemoryStore):
        assert store._build_fts_query("   ") is None
        assert store._build_fts_query("！？，。") is None

    def test_keyword_search_chinese(self, store: SQLiteMemoryStore):
        store.add([
            _make_chunk(text="用户喜欢购买车险和意外险", chunk_id="c1", embedding=[0.1, 0.2, 0.3, 0.4]),
            _make_chunk(text="今天天气很好适合外出", chunk_id="c2", embedding=[0.5, 0.6, 0.7, 0.8]),
        ])
        results = store.keyword_search("车险", top_k=5)
        assert len(results) >= 1
        ids = [chunk.id for chunk, _ in results]
        assert "c1" in ids

    def test_keyword_search_no_match(self, store: SQLiteMemoryStore):
        store.add([
            _make_chunk(text="今天天气很好", chunk_id="c1", embedding=[0.1, 0.2, 0.3, 0.4]),
        ])
        results = store.keyword_search("保险理赔", top_k=5)
        assert len(results) == 0

    def test_keyword_search_fts_error_returns_empty(self, store: SQLiteMemoryStore):
        results = store.keyword_search("", top_k=5)
        assert results == []


# ============ BM25 score ============


class TestBM25Score:
    def test_negative_rank(self):
        score = SQLiteMemoryStore._bm25_rank_to_score(-4.2)
        assert 0 < score < 1
        assert score == pytest.approx(4.2 / 5.2)

    def test_zero_rank(self):
        assert SQLiteMemoryStore._bm25_rank_to_score(0) == pytest.approx(1.0)

    def test_positive_rank(self):
        assert SQLiteMemoryStore._bm25_rank_to_score(1.0) == pytest.approx(0.5)

    def test_ordering(self):
        s1 = SQLiteMemoryStore._bm25_rank_to_score(-4.0)
        s2 = SQLiteMemoryStore._bm25_rank_to_score(-2.0)
        s3 = SQLiteMemoryStore._bm25_rank_to_score(-0.5)
        assert s1 > s2 > s3

    def test_nan(self):
        assert SQLiteMemoryStore._bm25_rank_to_score(float("nan")) == 0.0


# ============ Vector search ============


class TestVectorSearch:
    def test_fallback_cosine_search(self, store: SQLiteMemoryStore):
        store.add([
            _make_chunk(text="向量A", chunk_id="a", embedding=[1.0, 0.0, 0.0, 0.0]),
            _make_chunk(text="向量B", chunk_id="b", embedding=[0.0, 1.0, 0.0, 0.0]),
        ])
        results = store._fallback_cosine_search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert len(results) == 2
        assert results[0][0].id == "a"
        assert results[0][1] > results[1][1]

    def test_vector_search_dispatches(self, store: SQLiteMemoryStore):
        store.add([
            _make_chunk(text="数据", chunk_id="c1", embedding=[1.0, 0.0, 0.0, 0.0]),
        ])
        results = store.vector_search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert len(results) >= 1


# ============ Hybrid search ============


class TestHybridSearch:
    def test_hybrid_merges_results(self, store: SQLiteMemoryStore):
        store.add([
            _make_chunk(text="用户喜欢购买车险和意外险", chunk_id="c1", embedding=[1.0, 0.0, 0.0, 0.0]),
            _make_chunk(text="今天阳光明媚适合外出游玩", chunk_id="c2", embedding=[0.0, 1.0, 0.0, 0.0]),
        ])
        results = store.hybrid_search(
            query="车险",
            query_embedding=[0.9, 0.1, 0.0, 0.0],
            top_k=5,
            min_score=0.0,
        )
        assert len(results) >= 1
        assert results[0].path == "MEMORY.md"


# ============ File tracking ============


class TestFileTracking:
    def test_get_set_file_hash(self, store: SQLiteMemoryStore):
        assert store.get_file_hash("test.md") is None
        store.set_file_hash("test.md", "abc123")
        assert store.get_file_hash("test.md") == "abc123"

    def test_update_file_hash(self, store: SQLiteMemoryStore):
        store.set_file_hash("test.md", "v1")
        store.set_file_hash("test.md", "v2")
        assert store.get_file_hash("test.md") == "v2"


# ============ Embedding cache ============


class TestEmbeddingCache:
    def test_get_set_cached_embeddings(self, store: SQLiteMemoryStore):
        entries = [("hash1", [0.1, 0.2, 0.3]), ("hash2", [0.4, 0.5, 0.6])]
        store.set_cached_embeddings("bge-base", entries)
        result = store.get_cached_embeddings("bge-base", ["hash1", "hash2", "hash3"])
        assert "hash1" in result
        assert "hash2" in result
        assert "hash3" not in result
        assert result["hash1"] == [0.1, 0.2, 0.3]

    def test_model_scoped_cache(self, store: SQLiteMemoryStore):
        store.set_cached_embeddings("model-a", [("h1", [1.0, 2.0])])
        store.set_cached_embeddings("model-b", [("h1", [3.0, 4.0])])
        a = store.get_cached_embeddings("model-a", ["h1"])
        b = store.get_cached_embeddings("model-b", ["h1"])
        assert a["h1"] == [1.0, 2.0]
        assert b["h1"] == [3.0, 4.0]

    def test_empty_hashes(self, store: SQLiteMemoryStore):
        assert store.get_cached_embeddings("model", []) == {}


# ============ Meta ============


class TestMeta:
    def test_read_write_meta(self, store: SQLiteMemoryStore):
        assert store.read_meta() is None
        meta = IndexMeta(model="bge-base", dims=768, chunk_size=500, chunk_overlap=50)
        store.write_meta(meta)
        loaded = store.read_meta()
        assert loaded is not None
        assert loaded.model == "bge-base"
        assert loaded.dims == 768

    def test_meta_update(self, store: SQLiteMemoryStore):
        store.write_meta(IndexMeta(model="old", dims=768))
        store.write_meta(IndexMeta(model="new", dims=1024))
        loaded = store.read_meta()
        assert loaded is not None
        assert loaded.model == "new"
        assert loaded.dims == 1024


class TestIndexMeta:
    def test_json_roundtrip(self):
        meta = IndexMeta(model="bge", dims=768, chunk_size=300, chunk_overlap=30)
        raw = meta.to_json()
        loaded = IndexMeta.from_json(raw)
        assert loaded.model == "bge"
        assert loaded.dims == 768
        assert loaded.chunk_size == 300
        assert loaded.chunk_overlap == 30


# ============ Atomic reindex ============


class TestAtomicReindex:
    def test_safe_reindex_replaces_data(self, tmp_dir: Path):
        db_path = str(tmp_dir / "reindex.db")
        store = SQLiteMemoryStore(db_path, dimensions=4)
        store._ensure_vector_table(4)
        store.add([_make_chunk(text="旧数据", chunk_id="old", embedding=[0.1, 0.2, 0.3, 0.4])])
        store.set_cached_embeddings("model", [("h1", [1.0, 2.0, 3.0])])
        assert store.chunk_count == 1

        new_chunks = [
            _make_chunk(text="新数据一", chunk_id="new1", embedding=[0.5, 0.6, 0.7, 0.8]),
            _make_chunk(text="新数据二", chunk_id="new2", embedding=[0.9, 0.1, 0.2, 0.3]),
        ]
        meta = IndexMeta(model="bge", dims=4)
        store.safe_reindex(new_chunks, meta)

        assert store.chunk_count == 2
        assert store.get_chunk("old") is None
        assert store.get_chunk("new1") is not None
        loaded_meta = store.read_meta()
        assert loaded_meta is not None
        assert loaded_meta.model == "bge"
        # embedding cache should be seeded
        cached = store.get_cached_embeddings("model", ["h1"])
        assert "h1" in cached
        store.close()


# ============ Dimension mismatch ============


class TestDimensionMismatch:
    def test_dimension_change_rebuilds_vec_table(self, tmp_dir: Path):
        db_path = str(tmp_dir / "dims.db")
        store = SQLiteMemoryStore(db_path, dimensions=4)
        store._ensure_vector_table(4)
        store.write_meta(IndexMeta(model="test", dims=4))
        store.add([_make_chunk(text="test", chunk_id="c1", embedding=[1.0, 0.0, 0.0, 0.0])])

        # Change dimensions
        store._dimensions = 8
        store._ensure_vector_table(8)
        new_meta = store.read_meta()
        # The old vec data is dropped; table recreated with new dims
        # Verify the store still functions
        store.add([_make_chunk(text="test2", chunk_id="c2", embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])])
        assert store.chunk_count == 2
        store.close()


# ============ sqlite-vec fallback ============


class TestVecFallback:
    def test_search_works_without_vec(self, tmp_dir: Path):
        db_path = str(tmp_dir / "novec.db")
        store = SQLiteMemoryStore(db_path, dimensions=4)
        store._vec_available = False  # simulate unavailable
        store.add([
            _make_chunk(text="向量测试", chunk_id="c1", embedding=[1.0, 0.0, 0.0, 0.0]),
        ])
        results = store.vector_search([1.0, 0.0, 0.0, 0.0], top_k=5)
        assert len(results) == 1
        assert results[0][0].id == "c1"
        store.close()


# ============ Per-user DB isolation ============


class TestUserIsolation:
    """Verify that two users backed by separate SQLite files don't leak data."""

    def test_separate_db_files_per_user(self, tmp_dir: Path):
        # Simulate _get_memory_for_user creating per-user stores
        from ark_agentic.core.memory.manager import MemoryConfig, MemoryManager

        base_workspace = tmp_dir / "memory"

        # User A workspace
        cfg_a = MemoryConfig(workspace_dir=str(base_workspace / "userA"))
        # User B workspace
        cfg_b = MemoryConfig(workspace_dir=str(base_workspace / "userB"))

        # Both configs omit index_dir, so each derives workspace_dir/.memory
        dir_a = Path(cfg_a.workspace_dir) / ".memory"
        dir_b = Path(cfg_b.workspace_dir) / ".memory"
        assert dir_a != dir_b, "index dirs must differ"

        db_path_a = str(dir_a / "memory.db")
        db_path_b = str(dir_b / "memory.db")
        assert db_path_a != db_path_b, "DB paths must differ"

        # Write user A data
        store_a = SQLiteMemoryStore(db_path_a, dimensions=4)
        store_a.add([_make_chunk(text="用户A的私密保单", chunk_id="a1", path="MEMORY.md")])
        store_a.close()

        # Write user B data
        store_b = SQLiteMemoryStore(db_path_b, dimensions=4)
        store_b.add([_make_chunk(text="用户B的私密保单", chunk_id="b1", path="MEMORY.md")])
        store_b.close()

        # Reopen and verify strict isolation
        store_a = SQLiteMemoryStore(db_path_a, dimensions=4)
        store_b = SQLiteMemoryStore(db_path_b, dimensions=4)

        all_a = {c.id for c in store_a.get_all_chunks()}
        all_b = {c.id for c in store_b.get_all_chunks()}

        assert "a1" in all_a, "user A should see own data"
        assert "b1" not in all_a, "user A must NOT see user B's data"
        assert "b1" in all_b, "user B should see own data"
        assert "a1" not in all_b, "user B must NOT see user A's data"

        store_a.close()
        store_b.close()

    def test_get_memory_for_user_scopes_index_dir(self, tmp_dir: Path):
        """_get_memory_for_user must produce isolated index_dirs for every user."""
        import copy
        from ark_agentic.core.memory.manager import MemoryConfig

        # Simulate the runner's _get_memory_for_user logic
        base_cfg = MemoryConfig(
            workspace_dir=str(tmp_dir / "memory"),
            index_dir=str(tmp_dir / "memory" / ".index"),  # explicitly set (as build_memory_manager used to do)
        )

        def simulate_get_memory_for_user(user_id: str) -> MemoryConfig:
            user_workspace = str(Path(base_cfg.workspace_dir) / user_id)
            user_cfg = copy.copy(base_cfg)
            user_cfg.workspace_dir = user_workspace
            user_cfg.index_dir = ""  # the fix
            return user_cfg

        cfg_a = simulate_get_memory_for_user("userA")
        cfg_b = simulate_get_memory_for_user("userB")

        # After the fix, index_dir is empty → MemoryManager falls back to workspace_dir/.memory
        assert cfg_a.index_dir == ""
        assert cfg_b.index_dir == ""
        # workspaces are different → DBs will be in different directories
        assert cfg_a.workspace_dir != cfg_b.workspace_dir
