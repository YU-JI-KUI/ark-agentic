# mem0 Memory Integration Design

> Date: 2026-03-10
> Status: Approved

## 1. Problem

当前 Memory 系统是单用户、文件优先的设计：所有用户共享一个 `MEMORY.md`，FAISS 索引全局无隔离，无 LLM 驱动的记忆生命周期管理。需要支持多用户隔离、智能记忆管理，同时保留 markdown 的可读性。

## 2. Solution

单一 `MemoryManager` 类，mem0 作为可选引擎。环境变量 `MEM0_ENABLED=true` 开启。

- **File mode (dev/default)**: Markdown 文件是 source of truth，FAISS + BM25 搜索，`user_id` 通过子目录隔离。
- **mem0 mode (production)**: mem0 处理存储/检索/生命周期，Markdown 文件作为 auto-generated 的人类可读视图。

## 3. Architecture

```
Agent Tools (memory_search / memory_get / memory_set)
        │
        ▼
  MemoryManager (single class)
        │
        ├── mem0_enabled = false ──► File Engine
        │                            ├── FAISS + BM25 hybrid search
        │                            └── memory/{user_id}/MEMORY.md (source of truth)
        │
        └── mem0_enabled = true ───► mem0.Memory
                                     ├── Vector Store (FAISS/Milvus/Qdrant/PGVector/...)
                                     ├── LLM fact extraction + lifecycle
                                     └── MarkdownProjector → memory/{user_id}/MEMORY.md (view)
```

## 4. Usage Flows

### 4.1 Pre-compact Callback (自动记忆写入)

当对话历史超过上下文窗口触发压缩时，被丢弃的消息会被保存到长期记忆。

**File mode:**
```
Session 消息即将被压缩
  → pre_compact_callback(session_id, old_messages)
  → 格式化消息为文本摘要
  → append 到 memory/{user_id}/MEMORY.md
  → sync() 重建 FAISS/BM25 索引
```

**mem0 mode:**
```
Session 消息即将被压缩
  → pre_compact_callback(session_id, old_messages)
  → 格式化消息为 [{role, content}, ...]
  → mem0.add(messages, user_id=user_id)
    └── LLM 提取事实 → 搜索已有记忆 → 决定 ADD/UPDATE/DELETE
  → project_to_markdown(user_id) (async side-effect)
```

### 4.2 Agent 主动记忆操作

**memory_search (检索):**
- File mode: FAISS + BM25 hybrid search，按 `memory/{user_id}/` 路径过滤
- mem0 mode: `mem0.search(query, user_id=user_id)`

**memory_get (读取全部记忆):**
- File mode: 读取 `memory/{user_id}/MEMORY.md` 指定行
- mem0 mode: `mem0.get_all(user_id=user_id)` 返回格式化列表

**memory_set (写入):**
- File mode: append 到 `memory/{user_id}/MEMORY.md` + re-index
- mem0 mode: `mem0.add(content, user_id=user_id)` + project to markdown

### 4.3 mem0 内部流程

```
mem0.add(messages, user_id="U001")
  ├── 1. LLM 提取事实: "用户偏好暗色主题" → ["偏好暗色主题"]
  ├── 2. 对每个事实:
  │     ├── Embed 向量化
  │     ├── 搜索该用户已有记忆 (相似度匹配)
  │     └── LLM 决策:
  │         ├── ADD: 新事实 → 插入向量库
  │         ├── UPDATE: 已有类似 → 合并更新
  │         ├── DELETE: 被新信息否定 → 删除旧记忆
  │         └── NONE: 已知信息 → 跳过
  └── 3. 记录变更历史到 SQLite
```

## 5. Infrastructure Requirements

### 5.1 必需组件

| 组件 | 用途 | 基础设施需求 |
|---|---|---|
| LLM | 事实提取 + 生命周期决策 | 复用现有 `API_KEY` + `LLM_BASE_URL` |
| Embedding | 向量化 | 默认 OpenAI `text-embedding-3-small`，或本地模型 |
| Vector Store | 存储向量化记忆 | 见下表 |

### 5.2 Vector Store 选型

| Provider | 基础设施需求 | 适用场景 | 额外依赖 |
|---|---|---|---|
| `faiss` | **零** — 纯文件存储 | 开发/单机/少量用户 | `faiss-cpu` (已有) |
| `qdrant` | Docker 容器 | 单机中等规模 | `qdrant-client` |
| `milvus` | Docker/集群 | 企业级大规模 | `pymilvus` |
| `pgvector` | PostgreSQL | 已有 PG 的团队 | `psycopg2` |
| `chroma` | 本地进程 | 轻量本地 | `chromadb` |
| `pinecone` | 云服务 | 全托管 | `pinecone-client` |

**推荐路径**: 开发用 FAISS (零基础设施) → 生产切 Milvus 或 Qdrant (通过环境变量)。

### 5.3 最简启动 (Zero Infrastructure)

```
mem0 + FAISS (本地文件)    →  零额外服务
mem0 + OpenAI embedding    →  复用现有 API_KEY
mem0 + OpenAI LLM          →  复用现有 API_KEY
唯一新依赖: mem0ai
```

## 6. Configuration

### 6.1 环境变量

```bash
# ---- Memory (mem0) ----
MEM0_ENABLED=false                    # true 开启 mem0 模式
MEM0_VECTOR_PROVIDER=faiss            # faiss / qdrant / milvus / pgvector
MEM0_VECTOR_PATH=data/mem0_vectors    # FAISS 本地存储路径
MEM0_LLM_MODEL=gpt-4.1-nano          # 事实提取模型 (建议用便宜模型)
# MEM0_QDRANT_HOST=localhost          # Qdrant
# MEM0_QDRANT_PORT=6333
# MEM0_MILVUS_URL=http://localhost:19530  # Milvus
```

### 6.2 MemoryConfig

```python
@dataclass
class MemoryConfig:
    # 现有字段不变
    workspace_dir: str = ""
    index_dir: str = ""
    memory_paths: list[str] = field(default_factory=lambda: ["MEMORY.md", "memory/"])
    embedding: BGEConfig = field(default_factory=BGEConfig)
    vector: FAISSConfig = field(default_factory=FAISSConfig)
    keyword: BM25Config = field(default_factory=BM25Config)
    hybrid: HybridConfig = field(default_factory=HybridConfig)
    chunk: ChunkConfig = field(default_factory=ChunkConfig)
    auto_sync: bool = True
    sync_on_init: bool = True
    watch_files: bool = False

    # 新增: 多用户
    user_scoping: bool = True
    default_user_id: str = "default"

    # 新增: mem0
    mem0_enabled: bool = False
    mem0_config: dict | None = None        # → mem0.Memory.from_config()
    markdown_projection: bool = True       # mem0 模式下生成 markdown 视图
```

## 7. File Changes

### 修改

- `src/ark_agentic/core/memory/manager.py` — MemoryConfig 新增字段，MemoryManager 新增 mem0 分支
- `src/ark_agentic/core/memory/types.py` — 新增 MemoryItem pydantic model
- `src/ark_agentic/core/tools/memory.py` — 工具从 context 提取 user_id，路由到 MemoryManager
- `src/ark_agentic/core/runner.py` — pre_compact_callback 传入 user_id，mem0 模式走 add()
- `pyproject.toml` — 新增 `mem0 = ["mem0ai>=1.0.0"]` optional dependency
- `.env-sample` — 新增 MEM0_* 环境变量

### 新增

- `src/ark_agentic/core/memory/projection.py` — MarkdownProjector 类

## 8. File Structure

```
data/ark_memory/
├── memory/
│   ├── default/
│   │   └── MEMORY.md          # 向后兼容
│   ├── U001/
│   │   └── MEMORY.md          # user-scoped
│   └── U002/
│       └── MEMORY.md
├── .memory/                   # file engine 索引 (mem0 模式下不使用)
│   ├── memory_index.faiss
│   └── memory_index.meta
└── .mem0/                     # mem0 本地数据 (FAISS provider)
    └── history.db
```

## 9. Testing

- Unit: MemoryManager 两种模式 (mock mem0.Memory)
- Integration: 真实 mem0 + 本地 FAISS (标记 slow)
- 验证: markdown projection 输出合法可读内容
- 验证: 用户隔离 (U001 的记忆不返回给 U002)
- 验证: pre_compact_callback 在两种模式下正确路由
