# Memory 架构横向评审与整改方案

> 对比项目: ark-agentic / claude-code / openclaw / adk-python
> 评审日期: 2026-04-07

---

## 一、四项目 Memory 架构速览

### 1. ark-agentic (本项目)

| 维度 | 实现 |
|------|------|
| 记忆分类 | `profile` (用户画像) + `agent_memory` (业务记忆) |
| 存储 | 文件 (MEMORY.md) → SQLite (chunks + FTS5/jieba + sqlite-vec) |
| 检索 | Hybrid = BGE embedding vector + BM25 keyword，加权融合 |
| 多用户 | `user_id` 列分区，单 DB，单 MemoryManager 实例 |
| 写入 | `memory_write` tool + `MemoryFlusher` pre-compaction extract |
| Profile | heading-based markdown, upsert 语义 |

### 2. claude-code

| 维度 | 实现 |
|------|------|
| 记忆分类 | 4 类型 (`user`/`feedback`/`project`/`reference`) + session memory + CLAUDE.md instructions |
| 存储 | **纯文件系统** — 无嵌入数据库；每个 topic 一个 .md 文件 + MEMORY.md 索引 |
| 检索 | **Sonnet side-query** — 扫描 manifest headers → LLM JSON 选取 top-5 文件 |
| 多用户 | 不适用（单用户 CLI 工具），按 git-root 隔离 project memory |
| 写入 | 双路径：主 agent 直接写 + 后台 forked extractMemories 补漏 |
| 特色 | KAIROS 每日日志 + `/dream` 蒸馏；team memory cloud sync |

### 3. openclaw

| 维度 | 实现 |
|------|------|
| 记忆分类 | `memory` (长期) + `sessions` (转录) |
| 存储 | SQLite (chunks + FTS5 + sqlite-vec) + 可选 QMD 后端 + LanceDB 插件 |
| 检索 | Hybrid = vector + BM25 + **MMR 去冗** + **temporal decay**；QMD 支持 CJK BM25 整形 |
| 多用户 | `agentId` 粒度隔离 (per-agent SQLite)；`sessionKey` 做 scope 控制 |
| 写入 | memory-flush 在 compaction 前提取；文件系统 watch + interval sync |
| 特色 | 多 embedding 后端热切换；graceful degradation 链；维度变化自动重建 vec 表 |

### 4. adk-python (Google ADK)

| 维度 | 实现 |
|------|------|
| 记忆分类 | **Session** (事件源 state) ≠ **Memory** (语义召回)；state 有 `app:`/`user:`/`temp:` 前缀分区 |
| 存储 | Session: InMemory / SQLAlchemy / SQLite / Vertex AI；Memory: InMemory / Vertex Memory Bank / Vertex RAG |
| 检索 | InMemory 用词重叠；Vertex 用 embedding similarity；`PreloadMemoryTool` 自动注入 |
| 多用户 | `(app_name, user_id, session_id)` 三元组天然多租户 |
| 写入 | 显式 `add_session_to_memory` / `add_events_to_memory`；非自动 |
| 特色 | `temp:` 临时状态在 persist 前剥离；乐观并发控制；可插拔 ServiceRegistry |

---

## 二、关键差异对比矩阵

| 能力 | ark-agentic | claude-code | openclaw | adk-python |
|------|-------------|-------------|----------|------------|
| **记忆层次** | 2层 (profile + agent) | 4层 (user/feedback/project/ref + session + instructions) | 2层 (memory + sessions) | 2层 (session state + memory service) |
| **存储后端抽象** | ❌ 硬编码 SQLite | N/A (纯文件) | ✅ Strategy (builtin/QMD/LanceDB) | ✅ Abstract Service + Registry |
| **多用户隔离** | ⚠️ 有 user_id 列，但调用链断裂 | N/A | ✅ per-agentId DB | ✅ (app, user, session) 三维 |
| **召回去冗** | content_hash 去重 | LLM 选取 (隐式去冗) | **MMR** | 无显式去冗 |
| **时间衰减** | ❌ | 有 freshness helpers | ✅ temporal-decay | ❌ |
| **冲突 / 矛盾检测** | ❌ 仅 append | 主 agent + extract 互斥写 | ❌ 仅 append | ❌ |
| **记忆蒸馏 / 去噪** | flush 做粗粒度提取 | KAIROS `/dream` 蒸馏 | flush 但无蒸馏 | 无 |
| **Session ↔ Memory 边界** | 模糊（flush 从 messages 提取） | 明确 (session-memory vs auto-memory) | 明确 (sessions source vs memory source) | 最明确 (Session service ≠ Memory service) |
| **Pydantic 模型** | ❌ dataclass | N/A (TS) | N/A (TS) | ✅ 全 Pydantic |
| **乐观并发** | ❌ | 文件锁 | ❌ | ✅ storage_update_marker |

---

## 三、已发现问题 (按严重性排序)

### P0 — 多用户链路断裂

**问题**: `MemorySearchTool.execute` 调用 `memory.search(query=..., max_results=..., min_score=...)` 时 **未传 `user_id`**，导致默认搜索 `user_id=""` 的空分区。

```python
# core/tools/memory.py L99-103
results = await memory.search(
    query=query,
    max_results=int(max_results),
    min_score=float(min_score),
    # ← 缺少 user_id=_get_user_id(context)
)
```

**影响**: 多用户场景下 `memory_search` 无法返回任何已索引的用户记忆。

**对照**: 同一文件中 `MemoryGetTool` 正确传递了 `user_id`，`MemoryWriteTool` 也正确获取了 `user_id`，唯独 `MemorySearchTool` 遗漏。

### P0 — `memory_write(agent_memory)` 写入路径与 flush 不一致

**问题**:
- `MemoryWriteTool` 追加到 `{workspace_dir}/MEMORY.md` (根目录，不含 user_id)
- `MemoryFlusher.make_pre_compact_callback` 追加到 `{workspace_dir}/{user_id}/MEMORY.md`

```python
# tools/memory.py L303 — 写入根
agent_memory_path = Path(memory.config.workspace_dir) / "MEMORY.md"

# extractor.py L191-192 — 写入用户子目录
ws = Path(memory_manager.config.workspace_dir) / user_id
agent_memory_path = ws / "MEMORY.md"
```

**影响**: Tool 写入的记忆不在 flush 写入的同一文件，且 sync(user_id) 只扫描用户子目录，Tool 写入的根 MEMORY.md 不会被用户粒度索引。

### P1 — `safe_reindex` 多用户数据丢失风险

**问题**: `safe_reindex` 创建临时 DB，只写入当前 sync 传入的 chunks，然后 **swap 替换整个 DB 文件**。如果以 `user_id="alice"` 触发 full reindex，`user_id="bob"` 的所有 chunks 会被丢弃。

```python
# sqlite_store.py L700-719
def safe_reindex(self, chunks: list[MemoryChunk], meta: IndexMeta, user_id: str = "") -> None:
    temp_store = SQLiteMemoryStore(temp_path, ...)
    temp_store.add(chunks)     # ← 只有当前用户的 chunks
    temp_store.write_meta(meta)
    temp_store.close()
    self.close()
    _swap_db_files(self._db_path, temp_path)  # ← 替换整个 DB
```

### P1 — Protocol 缺少 user_id 参数

**问题**: `types.py` 中的 `VectorStore`, `KeywordSearcher`, `MemorySearchManager` Protocol 的 `search` 方法 **没有 user_id 参数**，但实际 SQLiteMemoryStore 的所有搜索方法都需要 user_id。Protocol 与实现不匹配，无法作为真正的多租户抽象。

### P1 — 核心模型使用 dataclass 而非 Pydantic

项目规范要求「所有组件间的数据交换必须使用 pydantic.BaseModel」，但 memory 子系统全部使用 `@dataclass`。这导致：
- 缺乏运行时校验（user_id 为空串不会报错）
- 序列化/反序列化需手写
- 与 Studio API 层的 Pydantic 模型不一致

### P2 — 无 MMR / 时间衰减

openclaw 的混合搜索在融合后应用了 **MMR (Maximal Marginal Relevance)** 去冗和 **temporal decay** 时间衰减，我们只有 content_hash 去重。这意味着：
- 相似但不同的 chunks 可能占满 top-K 结果
- 最近的记忆和很久以前的记忆权重相同

### P2 — 无记忆矛盾检测 / UPSERT 语义

当前 `agent_memory` 是纯 append，不检查新记忆是否与已有记忆矛盾。例如用户先说"我喜欢简洁回复"，后来说"给我详细的分析"，两条记忆共存不会被合并或标记为冲突。

**行业实践**: mem0 使用 UPSERT 模式——写入前先做语义检索，高相似度时更新而非追加。Neo4j Agent Memory 使用 embedding 相似度阈值自动合并实体。

### P2 — 缺少 Organization 级别的记忆作用域

mem0 2026 年引入了四维作用域: `user_id` / `agent_id` / `app_id` / `run_id`，以及 `org_id` 跨用户搜索。我们目前只有 `user_id` 一个维度，无法支持：
- 组织级共享知识（如公司政策、产品知识）
- Agent 级记忆（不同 agent 对同一用户的独立记忆）
- 跨用户搜索（管理员视角）

### P3 — flush 对话截断过早

```python
# extractor.py L98
conversation=conversation_text[:8000],
```

硬编码 8000 字符截断，对长对话会丢失后半段的重要信息。应根据 LLM 上下文窗口动态计算。

### P3 — 缺少 Session Memory 独立概念

claude-code 明确区分了 session memory (单会话内的滚动摘要) 和 auto-memory (跨会话持久化)。我们的 flush 机制在 compaction 时一次性提取，没有会话级的持续总结能力。

---

## 四、Memory 生命周期分析

```
┌─────────────────────────────────────────────────────────────────┐
│                    Memory Lifecycle                              │
├─────────────┬───────────────────────────────────────────────────┤
│  阶段       │  当前实现                                          │
├─────────────┼───────────────────────────────────────────────────┤
│  1.采集     │  memory_write tool (Agent 主动)                    │
│  (Capture)  │  MemoryFlusher (compaction 前 LLM 提取)            │
│             │                                                   │
│  2.存储     │  Markdown 文件 → MarkdownChunker → BGE embedding   │
│  (Store)    │  → SQLite (chunks + FTS5 + vec)                    │
│             │                                                   │
│  3.索引     │  sync() 增量/全量: 文件 hash diff → re-chunk/embed │
│  (Index)    │  mark_dirty() 延迟触发                             │
│             │                                                   │
│  4.检索     │  memory_search → hybrid_search (vec 0.7 + kw 0.3) │
│  (Retrieve) │  memory_get → 按 path+line 定位                    │
│             │                                                   │
│  5.注入     │  profile → system prompt                           │
│  (Inject)   │  search results → tool response → context          │
│             │                                                   │
│  6.演化     │  ❌ 无蒸馏/合并/过期                                │
│  (Evolve)   │  Profile upsert 是唯一的"演化"机制                  │
└─────────────┴───────────────────────────────────────────────────┘
```

### 存储准确性问题

| 问题 | 影响 | 严重性 |
|------|------|--------|
| flush 截断 8000 字符 | 长对话后半段信息丢失 | 中 |
| agent_memory 纯 append 无去重 | 同一事实多次记录，噪声累积 | 高 |
| flush 全量覆写 profile vs tool upsert 语义不同 | flush 可能丢失 tool 写入的 heading | 中 |
| 无矛盾检测 | 互相矛盾的记忆共存 | 高 |
| MarkdownChunker 按段落切分 | 跨段落的信息可能被拆散 | 低 |

### 召回准确性问题

| 问题 | 影响 | 严重性 |
|------|------|--------|
| memory_search 未传 user_id | 多用户下搜不到任何结果 | **致命** |
| 无 MMR | top-K 被相似 chunks 占满，多样性差 | 中 |
| 无 temporal decay | 过期信息与最新信息权重相同 | 中 |
| FTS5 jieba 分词精度 | 专业术语可能切分错误，导致关键词匹配失败 | 低 |
| min_score 硬编码 0.35 | 对不同 query 类型不一定合适 | 低 |
| 无 query expansion / rewrite | 用户的口语化查询可能无法匹配 markdown 中的正式表达 | 中 |

---

## 五、整改方案

### Phase 1: 修复致命 Bug (1-2 天)

#### 1.1 修复 memory_search 的 user_id 传递

```python
# core/tools/memory.py — MemorySearchTool.execute
user_id = _get_user_id(context)
results = await memory.search(
    query=query,
    max_results=int(max_results),
    min_score=float(min_score),
    user_id=user_id,
)
```

#### 1.2 统一 memory_write 的文件路径

```python
# core/tools/memory.py — MemoryWriteTool.execute
# 改为与 flush 一致：写入 {workspace_dir}/{user_id}/MEMORY.md
agent_memory_path = Path(memory.config.workspace_dir) / user_id / "MEMORY.md"
```

#### 1.3 修复 safe_reindex 多用户安全

方案 A (推荐): `safe_reindex` 只替换目标 user_id 的 chunks，不 swap 整个 DB
```python
def safe_reindex(self, chunks, meta, user_id=""):
    self._conn.execute("BEGIN")
    self._conn.execute("DELETE FROM chunks WHERE user_id = ?", (user_id,))
    # ... re-insert chunks for this user_id only
    self._conn.execute("COMMIT")
```

方案 B: 改为 per-user DB 文件 (openclaw 的做法)

### Phase 2: 架构升级 (1-2 周)

#### 2.1 引入多维度作用域 (参考 mem0 + ADK)

```python
class MemoryScope(BaseModel):
    """记忆作用域 — 四维隔离"""
    user_id: str = ""      # 用户维度
    agent_id: str = ""     # Agent 维度 (不同 agent 独立记忆)
    org_id: str = ""       # 组织维度 (共享知识)
    session_id: str = ""   # 会话维度 (temp state)
```

#### 2.2 引入 UPSERT 语义替代纯 Append

```
写入流程:
1. 新记忆 content → embedding
2. 向已有 chunks 做 vector search (threshold=0.9)
3. 如果命中高相似 chunk → UPDATE (UPSERT)
4. 如果无命中 → INSERT (APPEND)
5. 如果命中但内容矛盾 → 标记旧记忆为 superseded，插入新记忆
```

#### 2.3 添加 MMR + Temporal Decay

```python
class SearchConfig(BaseModel):
    vector_weight: float = 0.7
    keyword_weight: float = 0.3
    mmr_lambda: float = 0.7        # MMR 多样性参数
    temporal_decay_rate: float = 0.01  # 时间衰减速率
    candidate_multiplier: int = 3   # 候选池倍数
```

#### 2.4 迁移 dataclass → Pydantic

将 `MemoryChunk`, `MemorySearchResult`, `MemoryConfig` 等迁移到 Pydantic BaseModel，统一项目规范。

### Phase 3: 能力增强 (2-4 周)

#### 3.1 记忆蒸馏 (Memory Distillation)

参考 claude-code 的 KAIROS 模式和 mem0 的 Memory Curation:
- 定期将 append-only 的 `MEMORY.md` 蒸馏为结构化索引
- 合并重复条目
- 标记过期信息
- 生成摘要

#### 3.2 Session Memory 独立层

参考 claude-code 的 SessionMemory 和 ADK 的 `temp:` 前缀:
- 会话内滚动摘要 (非持久化)
- 会话结束时选择性提升为长期记忆
- `temp:` 前缀 state 在 persist 前自动剥离

#### 3.3 存储后端抽象 (Protocol 补全)

```python
class MemoryStore(Protocol):
    """统一存储后端协议"""
    async def add(self, chunks: list[MemoryChunk], scope: MemoryScope) -> None: ...
    async def search(self, query_embedding: list[float], top_k: int, scope: MemoryScope) -> list[tuple[MemoryChunk, float]]: ...
    async def upsert(self, chunk: MemoryChunk, scope: MemoryScope, similarity_threshold: float = 0.9) -> UpsertResult: ...
    async def delete(self, ids: list[str], scope: MemoryScope) -> None: ...
```

#### 3.4 mem0 集成评估

| 方面 | 自建 (当前) | mem0 集成 |
|------|------------|-----------|
| 多租户 | 需大幅改造 | 原生支持 |
| UPSERT | 需自建 | 内置 |
| 向量存储 | SQLite-vec | Qdrant/PGVector 等 |
| 部署复杂度 | 低 (嵌入式) | 中 (需额外服务) |
| 可定制性 | 高 | 中 |
| 中文支持 | jieba FTS5 | 需验证 |

**建议**: 对于多用户 SaaS 场景，mem0 的 Entity-Scoped Memory 和 org-scoped search 能力是显著优势。建议采用 **渐进式集成** 策略：
1. 先修复当前 Bug (Phase 1)
2. 引入 MemoryStore Protocol 抽象 (Phase 2)
3. 实现 mem0 后端作为可选 strategy (Phase 3)
4. 保留 SQLite 后端用于离线/开发场景

---

## 六、总结: 从参考项目学到的关键理念

| 来源 | 理念 | 启发 |
|------|------|------|
| **claude-code** | 双路写入 + 后台 extract 补漏 | 主动写入 + 被动提取双保险，降低信息丢失率 |
| **claude-code** | KAIROS 蒸馏 | append-only 日志需要定期整理，否则噪声累积 |
| **claude-code** | "什么不该记" 的显式策略 | 减少垃圾记忆比增加好记忆更重要 |
| **openclaw** | MMR + temporal decay | 召回多样性和时效性是准确性的两个被忽视维度 |
| **openclaw** | 多后端 Strategy + graceful degradation | 永远有 fallback，不因一个组件失败而完全丢失能力 |
| **adk-python** | Session ≠ Memory 明确分离 | 短期状态和长期记忆不应混在一起管理 |
| **adk-python** | `temp:` state + persist 前剥离 | 显式的临时 vs 持久语义，避免垃圾入库 |
| **adk-python** | `(app, user, session)` 三维隔离 | 多租户从 Day 1 设计进数据模型 |
| **mem0** | UPSERT 语义 + 矛盾检测 | append-only 是记忆系统的最大敌人 |
| **mem0** | Entity-Scoped Memory 四维作用域 | 灵活的作用域比单一 user_id 更适应复杂场景 |
