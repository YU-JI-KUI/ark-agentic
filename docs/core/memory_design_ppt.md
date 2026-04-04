# ArkAgentic Memory：实用主义的 Agent 记忆系统架构

### 构建简单、优雅且高效的长期记忆层

**核心定位**
专为 Python Agent 打造的轻量级、重人机协同记忆中枢。

**设计哲学**
坚持实用主义，追求简单优雅，零外部重型数据库依赖。

**核心价值**
单 SQLite 文件 + 本地 BGE 向量，最少依赖实现高召回率与完整用户隔离。

---

# ArkAgentic Memory 架构总览

### 极简、优雅的模块化分层设计

**统一的门面调度 (Facade Pattern)**
MemoryManager 作为唯一入口，对外只暴露 search、get、set 三个工具。

**SQLite 统一存储层**
向量索引（sqlite-vec）、关键词索引（FTS5 + jieba）、embedding 缓存、文件追踪——全部收纳在单个 `.db` 文件，无外部进程依赖。

**异步优先的懒初始化**
资源仅在首次调用时分配，embedding cache 命中时跳过重新向量化。

**原生用户隔离**
所有表含 `user_id` 列，文件目录按 `{workspace_dir}/{user_id}/` 分区，天然多用户。

---

# SQLite 统一存储与结构感知

### 精准检索与高召回率的基石

**结构感知分块 (MarkdownChunker)**
优先按 Markdown 标题边界切割，最大程度保留文档知识层级。

**双引擎混合打分**
- sqlite-vec 向量余弦检索（权重 0.7），sqlite-vec 不可用时自动降级为 numpy cosine
- FTS5 + jieba BM25 关键词检索（权重 0.3），得分归一化后融合

**Embedding Cache**
按 `content_hash` 缓存向量至 `embedding_cache` 表，内容未变化时零计算开销。

**增量同步**
MD5 文件 hash 比对，仅对变化文件重新切块和向量化；`safe_reindex()` 写临时 `.db` 再 swap，防止中断损坏。

---

# 记忆生命周期闭环

### 从"工作记忆"到"长期记忆"的结构化沉淀

**无状态的安全交互边界**
LLM 对记忆的操作严格收口于三个受控工具，沙盒隔离度高。

**LLM 驱动的记忆提取（MemoryFlusher）**
上下文压缩前，由 LLM 结构化提取对话中的关键信息：
- **User Profile** → `_profiles/{user_id}/MEMORY.md`，全局跨 Agent 共享，heading-based upsert
- **Agent Memory** → `{workspace_dir}/{user_id}/`，Agent 专属，增量追加

**自动触发索引重建**
写入后立即调用 `sync()`，形成"产生对话 → LLM 提取 → 分流写入 → 增量重建"闭环。

---

# 业界记忆机制横向对比

### 核心能力差异化分析

| 核心维度 | ArkAgentic Memory | OpenClaw | Mem0 |
| --- | --- | --- | --- |
| **设计思路** | 轻量级、重人机协同，单 SQLite 文件，无外部数据库。 | 高权限个人助理，依托本地 SQLite 及系统命令级操作。 | 复杂记忆中间件，需部署图数据库与外部向量集群。 |
| **检索机制** | sqlite-vec 向量 + FTS5/jieba BM25 混合检索，embedding cache 加速。 | 轻量级本地 RAG，SQLite 扩展向量检索。 | 向量 + 图谱双重召回，支持多跳推理。 |
| **生命周期** | LLM 驱动结构化提取，分流写入 user profile + agent memory。 | 跨会话持久化，Agent 直接读写本地文件。 | 全自动化，内置冲突过滤与衰减机制。 |
| **用户边界** | `user_id` 列级隔离 + 文件目录分区，天然多用户安全。 | 无隔离，单用户本地文件。 | 统一 API 端点，支持多租户企业级权限隔离。 |

---

# 向重型记忆中枢的平滑过渡路径

### 警惕冗余设计，稳妥把控架构演进

**阶段 1：接口防腐层固化**
固化三个工具的 Protocol 入参出参，确保核心 Agent 业务逻辑不依赖底层存储实现。

**阶段 2：适配器开发与测试先行**
新增外部数据库（如 Mem0）适配层，TDD 先行，新接口与现有接口并存。

**阶段 3：异步双写与灰度读取**
特性开关控制：写入时主流程落盘 SQLite，异步同步至外部集群；读取时静默对比两路召回结果。

**阶段 4：历史清洗与全量切流**
一次性脚本清洗历史记忆，监控平稳后切换开关，安全下线本地 SQLite 索引。**底线：未触及并发与体积物理瓶颈前，不进入此阶段。**
