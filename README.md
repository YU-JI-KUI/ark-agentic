# ark-agentic

轻量级 ReAct Agent 框架，支持工具调用、技能系统、会话管理、流式输出和用户记忆。

## 特性

- **ReAct 模式**: 推理-行动循环，支持并行工具调用
- **多 LLM 支持**: PA 内部模型（JT/SX 系列）、任意 OpenAI 兼容 Chat 端点（自建推理服务或第三方 API）
- **技能系统**: Markdown 格式可复用指令集，支持 full/dynamic/semantic 三种加载模式
- **会话管理**: JSONL 持久化 + 智能上下文压缩（LLM 摘要）+ Session State 状态管理
- **用户记忆**: 文件级 MEMORY.md + heading-based upsert + Dream 周期蒸馏 + system prompt 全量注入
- **AG-UI 流式协议**: 完整的 20 种事件类型，支持 4 种输出格式（agui/internal/enterprise/alone）
- **A2UI 组件**: 支持富交互前端组件渲染（卡片、按钮、表单等）
- **输出验证**: 自动检测 LLM 输出与工具结果的数值一致性，防止幻觉
- **FastAPI 服务**: 生产就绪的 HTTP API，支持多协议 SSE 流式输出

## 安装

```bash
uv add git+https://github.com/your-org/ark-agentic.git

# 或本地开发
uv pip install -e .
```

### 可选依赖

```bash
# PA-JT 系列模型（需要 RSA 签名）
uv add 'ark-agentic[pa-jt]'

# 开发环境（包含测试工具）
uv add 'ark-agentic[dev]'

# 全部依赖（含 PA-JT + dev）
uv add 'ark-agentic[all]'
```

**注意**: Memory 系统使用纯文件存储（MEMORY.md），无需额外依赖；PA-SX 与标准 OpenAI 兼容 Chat 接口无需额外依赖；仅 PA-JT 系列需要 `pycryptodome` 做 RSA 签名。

## 快速开始

```python
from ark_agentic.core.runner import AgentRunner
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.llm import create_chat_model
from ark_agentic.agents.insurance.tools import create_insurance_tools

llm = create_chat_model(
    "Qwen3-next-80B-A3B-instruct",
    api_key="sk-xxx",
    base_url="https://your-llm-gateway/v1",
)
tool_registry = ToolRegistry()
tool_registry.register_all(create_insurance_tools())

agent = AgentRunner(
    llm=llm,
    tool_registry=tool_registry,
    session_manager=SessionManager(),
)

session_id = await agent.create_session()
result = await agent.run(session_id, "我想取点钱")
```

## API 服务

```bash
export API_KEY=sk-xxx
ark-agentic-api
```

### Phoenix 可观测性

项目支持把 LangChain/Agent 链路发送到 Arize Phoenix。

```bash
export ENABLE_PHOENIX=true
export PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317
export PHOENIX_PROJECT_NAME=ark-agentic

# 可选
export PHOENIX_AUTO_INSTRUMENT=true
export PHOENIX_BATCH=true
```

服务启动后会在 FastAPI lifespan 中自动初始化 Phoenix，并在退出时执行 shutdown 以 flush traces。

### 端点

```http
POST /chat
Content-Type: application/json

{
  "agent_id": "insurance",
  "message": "用户消息",
  "session_id": "可选会话ID",
  "stream": true,
  "user_id": "U001",
  "context": {"custom_key": "value"},
  "idempotency_key": "req-12345",
  "history": [{"role": "user", "content": "历史消息"}],
  "use_history": true,
  "run_options": {"model": "gpt-4o", "temperature": 0.5}
}
```

**SSE 事件格式** (支持多协议):

```bash
# 协议选择（通过 protocol 参数）
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "insurance",
    "message": "查询保单",
    "stream": true,
    "protocol": "internal"
  }'
```

**协议类型**:
- `internal` (默认): 旧版 response.* 格式，向后兼容现有前端
- `agui`: AG-UI 原生事件（20 种事件类型）
- `enterprise`: 企业 AGUI 信封格式（带 source_bu_type/app_type）
- `alone`: ALONE 协议（sa_* 事件）

**AG-UI 原生事件示例** (protocol=agui):
```json
{
  "type": "text_message_content",
  "seq": 5,
  "run_id": "uuid",
  "session_id": "uuid",
  "message_id": "msg-uuid",
  "delta": "流式片段",
  "turn": 1,
  "content_kind": "text"
}
```

*完整事件类型: `run_started`, `run_finished`, `run_error`, `step_started`, `step_finished`, `text_message_start`, `text_message_content`, `text_message_end`, `tool_call_start`, `tool_call_args`, `tool_call_end`, `tool_call_result`, `state_snapshot`, `state_delta`, `messages_snapshot`, `thinking_message_start`, `thinking_message_content`, `thinking_message_end`, `custom`, `raw`*

**自定义 Headers**:
```
x-ark-session-key: 会话ID前缀
x-ark-user-id: 用户ID
x-ark-trace-id: 追踪ID
x-ark-message-id: 消息ID
```

## Docker

```bash
docker build -t ark-agentic .

docker run -d \
  -p 8080:8080 \
  -e API_KEY=sk-xxx \
  -e SESSIONS_DIR=/data/sessions \
  -e MEMORY_DIR=/data/memory \
  -v ark-sessions:/data/sessions \
  -v ark-memory:/data/memory \
  ark-agentic
```

## CLI 示例

```bash
# Mock 模式演示（无需 API Key）
python -m ark_agentic.agents.insurance.agent --mock --demo

# 交互模式
export API_KEY=sk-xxx
python -m ark_agentic.agents.insurance.agent -i

# 持久化 + Memory
python -m ark_agentic.agents.insurance.agent -i \
  --persistence --sessions-dir ./data/sessions \
  --memory --memory-dir ./data/memory
```

## 框架 CLI (ark-agentic)

在本仓库根目录，使用 `uv run` 直接调用 CLI（无需单独安装）：

```bash
cd /home/willis/codebase/ark-agentic-space/ark-agentic

# 查看帮助
uv run ark-agentic --help

# 初始化新项目（默认 openai）
uv run ark-agentic init my-agent

# 指定 LLM 提供商
uv run ark-agentic init my-openai-agent --llm-provider openai
# 添加FastAPI，chat API支持流式和非流式
uv run ark-agentic init my-pa-agent --llm-provider pa-sx --api

# 在已生成项目中添加新的业务智能体
cd my-agent
uv run ark-agentic add-agent risk-engine
```

`ark-agentic init` 会生成：

- `pyproject.toml`（依赖 `ark-agentic`）
- `src/<package>/main.py`（交互式入口）
- `src/<package>/agents/default/`（默认智能体骨架）
- `.env-sample`（根据 `--llm-provider` 写入对应的环境变量占位符）

其中 `.env-sample` 的 LLM 部分示例：

- 当 `--llm-provider=openai`（默认）:

  ```bash
  LLM_PROVIDER=openai
  MODEL_NAME=gpt-4o
  API_KEY=sk-xxx
  # LLM_BASE_URL=https://api.openai.com/v1
  ```

- 当 `--llm-provider=pa-sx`:

  ```bash
  LLM_PROVIDER=pa
  MODEL_NAME=PA-SX-80B
  API_KEY=your-sx-api-key
  LLM_BASE_URL=https://pa-sx.example.com
  ```

- 当 `--llm-provider=pa-jt`:

  ```bash
  LLM_PROVIDER=pa
  MODEL_NAME=PA-JT-80B
  API_KEY=
  LLM_BASE_URL=https://pa-jt.example.com
  # PA-JT 签名必填
  ```

## 核心概念

### 工具定义

```python
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult, ToolResultType

class PolicyQuery(AgentTool):
    name = "policy_query"
    description = "查询用户保单信息"
    parameters = [
        ToolParameter(name="user_id", type="string", required=True),
        ToolParameter(name="query_type", type="string", required=True),
    ]

    async def execute(self, tool_call, context=None):
        # 返回 JSON 结果
        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data={"policies": [...]}
        )

        # 或返回 A2UI 组件（富交互界面）
        return AgentToolResult.a2ui_result(
            tool_call_id=tool_call.id,
            data={
                "sessionId": context.get("session_id"),
                "answerDict": {
                    "result": {
                        "answerList": [{
                            "styleId": "0",
                            "dataList": [
                                {"component": "text", "text": "保单详情"},
                                {"component": "button", "text": "查看", "action": "view"}
                            ]
                        }]
                    }
                }
            }
        )
```

**工具结果类型**:
- `JSON`: 结构化数据
- `TEXT`: 纯文本
- `IMAGE`: Base64 图片
- `A2UI`: 前端组件描述（卡片、按钮、表单等）
- `ERROR`: 错误信息

### 技能系统

`skills/withdraw_money/SKILL.md`:
```markdown
---
name: withdraw_money
description: 保险取款业务处理
invocation_policy: auto
---

# 取款业务

## 规则
- 部分领取: 最高 80% 账户价值
- 保单贷款: 最高 80% 现金价值
```

**技能加载模式**（full / dynamic / semantic）为 Agent 级别配置：在创建 agent 时通过 `SkillConfig(default_load_mode=SkillLoadMode.full)` 等传入 `RunnerConfig(skill_config=...)`，使用 `ark_agentic.core.types.SkillLoadMode` 枚举。

### 会话压缩

```python
from ark_agentic.core.compaction import CompactionConfig, LLMSummarizer
from ark_agentic.core.llm import create_chat_model

llm = create_chat_model(
    "Qwen3-next-80B-A3B-instruct",
    api_key="sk-xxx",
    base_url="https://your-llm-gateway/v1",
)

session_manager = SessionManager(
    compaction_config=CompactionConfig(
        context_window=32000,
        preserve_recent=4,  # 保留最近4轮对话
    ),
    summarizer=LLMSummarizer(llm),
)
```

### Session State 管理

```python
# 工具可以写入 session state
class SetPreferenceTool(AgentTool):
    async def execute(self, tool_call, context=None):
        return AgentToolResult.json_result(
            tool_call.id,
            {"ok": True},
            metadata={"state_delta": {"user_preference": "option_a"}}
        )

# 其他工具可以读取 session state
class GetPreferenceTool(AgentTool):
    async def execute(self, tool_call, context=None):
        preference = context.get("user_preference", "default")
        return AgentToolResult.json_result(
            tool_call.id,
            {"preference": preference}
        )
```

### 并行子任务系统

`SpawnSubtasksTool` 支持在单次对话中并行执行多个独立子任务，适用于用户一句话包含多个独立意图的场景。

```python
from ark_agentic.core.subtask.tool import SpawnSubtasksTool, SubtaskConfig

# 配置子任务参数
subtask_config = SubtaskConfig(
    max_concurrent=4,        # 最大并发数
    timeout_seconds=300.0,   # 单任务超时
    tools_deny={"memory_write"},  # 禁用的工具
    keep_session=False,      # 完成后删除子会话
    max_turns=5,             # 子任务最大轮次
)

# 注册到 runner
runner.register_tool(SpawnSubtasksTool(runner, session_manager, subtask_config))
```

**使用示例**：用户说 "我要理赔，同时查查能领多少钱"

工具会自动：
1. 创建隔离的子会话
2. 并行执行两个子任务
3. 汇总结果并回传 state_delta
4. 清理临时会话

### 用户记忆系统

三层记忆生命周期：**Session JSONL (raw) → MEMORY.md (distilled) → System Prompt (consumption)**。

#### 启用

```python
from ark_agentic.core.memory.manager import build_memory_manager

memory_manager = build_memory_manager("./data/memory")

# 自动注册 memory_write 工具
agent = AgentRunner(
    llm=llm,
    tool_registry=tool_registry,
    session_manager=session_manager,
    memory_manager=memory_manager,
)
```

### Runner 生命周期回调

`RunnerCallbacks` 提供 **7 个 hook**，覆盖 Agent 执行的完整生命周期。所有 hook 均为 `async`，返回 `CallbackResult | None`。

#### 生命周期时序

```
run()
 │
 ├─ [before_agent]          # Agent 级，仅触发一次（请求预处理/权限拦截）
 │
 └─ ReAct Loop ──────────────────────────────────────────────────────┐
     │                                                               │
     ├─ [before_model]       # 每轮 LLM 调用前（可注入消息/短路）        │
     ├─  LLM call                                                    │
     ├─ [after_model]        # 每轮 LLM 响应后，持久化前（可替换响应）    │
     │                                                               │
     ├─ 有 tool_calls?                                               │
     │   ├─ [before_tool]    # 每轮工具批执行前（可拦截/mock）           │
     │   ├─  tool execute                                            │
     │   └─ [after_tool]     # 每轮工具执行后（可替换工具结果）           │
     │                                                               │
     └─ 无 tool_calls（最终回答轮）                                    │
         ├─ [before_loop_end] # 最终回答落地前（可校验/拒绝并重入 loop）  │
         │   action=RETRY ──────────────────────────────────────────────┘
         └─ _finalize_response → 返回给调用方
 │
 └─ [after_agent]            # Agent 级，仅触发一次（后处理/日志）
```

#### Hook 速查

| Hook | 触发时机 | `action` 语义 | 常见用途 |
|------|---------|--------------|----------|
| `before_agent` | 进入 loop 前，一次 | `ABORT` → 拒绝请求，直接返回 response | 鉴权、输入过滤 |
| `after_agent` | loop 结束后，一次 | — | 日志、后处理 |
| `before_model` | 每轮 LLM 调用前 | `OVERRIDE` → 跳过 LLM，使用 `response` 作为输出 | mock、注入上下文 |
| `after_model` | 每轮 LLM 响应后 | — | 响应过滤、内容替换 |
| `before_tool` | 每轮工具批执行前 | `OVERRIDE` → 跳过真实工具，使用 `tool_results` | 工具 mock、权限检查 |
| `after_tool` | 每轮工具执行后 | — | 结果增强、审计 |
| `before_loop_end` | 最终回答（无工具调用）落地前 | `RETRY` → 注入纠正消息并 **continue loop**（触发模型自反思） | 输出校验、引用验证 |

#### HookAction 枚举

```python
class HookAction(str, Enum):
    PASS = "pass"      # 不干预，走默认流程
    ABORT = "abort"    # before_agent: 拒绝请求，退出 run
    OVERRIDE = "override"  # before_model / before_tool: 替换默认输出
    RETRY = "retry"    # before_loop_end: 注入反馈，让模型重试
```

#### CallbackResult 字段

```python
@dataclass
class CallbackResult:
    action: HookAction = HookAction.PASS    # 声明回调意图
    response: AgentMessage | None = None    # 替换或注入的消息
    tool_results: list[...] | None = None   # 替换工具结果（before/after_tool）
    context_updates: dict | None = None     # 合并到 input_context
    event: CallbackEvent | None = None      # 向前端推送自定义事件
```

#### 示例：上下文预处理（before_agent）

```python
from ark_agentic.core.callbacks import CallbackContext, CallbackResult, RunnerCallbacks

async def enrich_context(ctx: CallbackContext) -> CallbackResult | None:
    return CallbackResult(
        context_updates={"user:name": fetch_user_name(ctx.input_context.get("user:id"))}
    )

runner = AgentRunner(..., callbacks=RunnerCallbacks(before_agent=[enrich_context]))
```

#### 示例：输出引用校验（before_loop_end）

`before_loop_end` 是专为输出质量校验设计的 hook。`action=RETRY` 不是终止 run，而是将纠正消息注入 session 后重入 ReAct loop，让模型自我修正后再次输出。

```python
from ark_agentic.core.validation import create_citation_validation_hook, EntityTrie

trie = EntityTrie()
trie.load_from_csv(csv_path)
citation_hook = create_citation_validation_hook(
    entity_trie=trie,
)

runner = AgentRunner(
    ...,
    callbacks=RunnerCallbacks(
        before_agent=[enrich_context],
        before_loop_end=[citation_hook],   # 通过 → 落地；retry → 注入反馈 + 重入 loop
    ),
)
```

校验失败时的自反思流程（无需 `record_citations`）：

```
LLM → 输出回答（无 tool_calls）
before_loop_end：从 response.content 提取 claim，与 ``session.messages`` 中本轮 TOOL 消息 + 近期用户消息做 grounding
  → 失败：注入 user 消息（含 UNGROUNDED 明细）→ continue ReAct loop
  → 通过：_finalize_response → 前端收到纯自然语言
```
#### 存储结构

```
data/memory/
└── {user_id}/
    ├── MEMORY.md      # 蒸馏后的用户记忆（heading-based markdown）
    └── .last_dream    # Dream 最后执行时间戳
```

每个用户的记忆是一个 Markdown 文件，使用 `## heading` 结构化，同名标题自动覆盖（upsert 语义）。

#### 记忆生命周期

| 阶段 | 触发时机 | 机制 |
|------|----------|------|
| **Write** | 对话中 | Agent 主动调用 `memory_write`（用户表达偏好/身份/决策时） |
| **Flush** | 上下文压缩前 | `MemoryFlusher` 用 LLM 从完整对话提取新增记忆 → heading upsert |
| **Read** | 每轮对话开始 | System prompt 自动注入用户 `MEMORY.md` 全文 |
| **Dream** | 后台周期触发 | 读取近期 session + 当前记忆 → LLM 蒸馏 → optimistic merge 回写 |

```
# Agent 写记忆示例
memory_write(content="## 风险偏好\n保守型，不接受本金亏损")
```

#### Dream 记忆蒸馏

Dream 在每轮对话结束后自动检查触发条件（距上次 dream ≥ 24h 且新增 ≥ 3 个 session），满足则在后台异步执行：

- 读取近期 session JSONL（user + assistant 消息，skip tool noise）
- 结合当前 MEMORY.md + 当前日期 + 容量约束
- LLM 单次调用蒸馏：合并语义相近标题、删除过期信息、提取潜在需求
- **Optimistic merge** 回写：保留 dream 期间 memory_write 新增的标题，不丢失并发写入
- `.bak` 备份保护

Dream 是**保守操作**：有疑问时保留信息，不会删除可能仍然有效的内容。多用户并发时各 user 的 dream 独立运行，同一 user 不会重复触发。

### PA Knowledge API（可选）

```python
from ark_agentic.core.tools import PAKnowledgeAPIConfig, create_pa_knowledge_api_tool

# 创建 agent 后按需注册
runner = create_insurance_agent(llm=llm)
runner.register_tool(create_pa_knowledge_api_tool(PAKnowledgeAPIConfig(
    tool_name="search_product_faq",
    faq_url="https://xxx",
    tenant_id="xxx",
    kn_ids=["23"],
    app_secret="xxx",
    token_auth_url="https://pa-api.example/auth/token",
)))
```

### LLM 客户端

```python
from ark_agentic.core.llm import create_chat_model

# OpenAI 兼容（API_KEY 可走环境变量）
llm = create_chat_model("gpt-4o")

# 显式 key / base_url（与 PA-SX 并列的典型生产路径）
llm = create_chat_model(
    "Qwen3-next-80B-A3B-instruct",
    api_key="sk-xxx",
    base_url="https://your-llm-gateway/v1",
)

# PA 内部模型 (SX 系列)
llm = create_chat_model("PA-SX-80B")

# PA 内部模型 (JT 系列)
llm = create_chat_model("PA-JT-80B")

# 自定义 OpenAI 兼容端点
llm = create_chat_model(
    "custom-model",
    api_key="sk-xxx",
    base_url="https://api.example.com/v1",
)
```

## 项目结构

```
src/ark_agentic/
├── core/
│   ├── runner.py          # AgentRunner (ReAct 主循环, ~912 行)
│   ├── session.py         # SessionManager (会话管理, ~405 行)
│   ├── compaction.py      # 上下文压缩 (~547 行, LLM 摘要)
│   ├── persistence.py     # JSONL 持久化 (~645 行)
│   ├── callbacks.py       # 7 个生命周期 hook 协议 + RunnerCallbacks
│   ├── validation.py      # 输出验证（幻觉检测）+ create_citation_validation_hook
│   ├── types.py           # 核心类型定义 (~315 行)
│   ├── llm/               # LLM 客户端 (LangChain-based)
│   │   ├── factory.py     # create_chat_model()
│   │   ├── pa_jt_llm.py   # PA-JT 系列支持
│   │   ├── pa_sx_llm.py   # PA-SX 系列支持
│   │   └── errors.py      # 错误分类
│   ├── tools/             # 工具系统
│   │   ├── base.py        # AgentTool 基类 (~227 行)
│   │   ├── registry.py    # ToolRegistry
│   │   ├── executor.py    # 工具执行器
│   │   ├── render_a2ui.py # A2UI 渲染工具
│   │   ├── memory.py      # Memory 工具 (~88 行)
│   │   ├── read_skill.py  # ReadSkill 工具
│   │   ├── demo_a2ui.py   # A2UI 演示工具
│   │   ├── demo_state.py  # State 演示工具
│   │   └── pa_knowledge_api.py  # PA 知识库 API (230 行)
│   ├── skills/            # 技能系统
│   │   ├── base.py
│   │   ├── loader.py
│   │   ├── matcher.py
│   │   └── semantic_matcher.py
│   ├── memory/            # 用户记忆系统 (文件级, 无 DB 依赖)
│   │   ├── manager.py     # MemoryManager (路径管理 + read/write)
│   │   ├── user_profile.py  # heading-based upsert / preamble 保护
│   │   ├── extractor.py   # MemoryFlusher (压缩前 LLM 提取)
│   │   ├── dream.py       # MemoryDreamer (session reader + 周期蒸馏 + optimistic merge)
│   │   └── types.py       # 类型定义
│   ├── stream/            # AG-UI 流式协议
│   │   ├── events.py      # 20 种 AG-UI 事件类型
│   │   ├── event_bus.py   # StreamEventBus
│   │   ├── output_formatter.py  # 4 种输出协议
│   │   ├── agui_models.py # 企业 AGUI 信封
│   │   └── assembler.py   # 流式组装器
│   ├── subtask/           # 并行子任务系统
│   │   └── tool.py        # SpawnSubtasksTool
│   ├── utils/             # 工具函数
│   │   ├── dates.py       # 日期处理
│   │   ├── entities.py    # 实体识别
│   │   ├── numbers.py     # 数值处理
│   │   ├── grounding_cache.py  # Grounding 缓存
│   │   └── env.py         # 环境变量
│   ├── a2ui/              # A2UI 组件系统
│   │   ├── blocks.py      # 区块定义
│   │   ├── composer.py    # 组件组合器
│   │   ├── renderer.py    # 渲染器
│   │   ├── validator.py   # 验证器
│   │   ├── flattener.py   # 扁平化处理
│   │   ├── transforms.py  # 变换逻辑
│   │   ├── contract_models.py  # 契约模型
│   │   ├── guard.py       # 守卫逻辑
│   │   ├── theme.py       # 主题配置
│   │   └── preset_registry.py  # 预设注册表
│   └── prompt/            # 提示词构建
│       └── builder.py     # SystemPromptBuilder
├── agents/
│   ├── insurance/         # 保险智能体示例
│   │   ├── agent.py       # 入口
│   │   ├── api.py         # 工厂函数
│   │   ├── tools/         # 业务工具
│   │   │   ├── policy_query.py
│   │   │   ├── customer_info.py
│   │   │   ├── data_service.py
│   │   │   └── rule_engine.py
│   │   └── skills/        # 业务技能
│   │       ├── withdraw_money/
│   │       ├── clarify_need/
│   │       └── rewrite_plan/
│   ├── securities/        # 证券智能体
│   │   ├── agent.py
│   │   ├── tools/
│   │   └── skills/
│   └── meta_builder/      # Meta 构建器智能体
│       ├── agent.py
│       └── tools/
├── studio/                # 管理控制台（可选）
│   ├── api/               # REST API
│   │   ├── agents.py
│   │   ├── skills.py
│   │   ├── tools.py
│   │   ├── sessions.py
│   │   └── memory.py
│   ├── frontend/          # React 前端
│   └── services/          # 服务层
├── api/                   # FastAPI 路由
│   ├── chat.py
│   ├── deps.py
│   └── models.py
├── cli/                   # CLI 工具
│   ├── main.py
│   └── templates.py
├── app.py                 # FastAPI 应用
└── static/                # Web UI

总计: ~30K+ 行代码（70+ Python 文件）
```

## 环境变量

### 核心配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商 (openai/pa) | `pa` |
| `API_KEY` | OpenAI 兼容端点 API Key | - |
| `MODEL_NAME` | 模型 id（PA 时为 PA-SX-80B 等，兼容时为 gpt-4o 等） | - |
| `LLM_BASE_URL` | LLM API 基础 URL（非 OpenAI 时必填） | - |
| `DEFAULT_TEMPERATURE` | LLM 温度 | `0.7` |
| `API_HOST` | API 监听地址 | `0.0.0.0` |
| `API_PORT` | API 端口 | `8080` |

### 存储配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SESSIONS_DIR` | 会话存储目录 | `data/ark_sessions` |
| `MEMORY_DIR` | Memory 数据目录 | `data/ark_memory` |

### 功能开关

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ENABLE_STUDIO` | 启用 Studio 管理界面 | `false` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `EMBEDDING_MODEL_PATH` | Embedding 模型路径（记忆/检索） | - |
| `AGENTS_ROOT` | 自定义 Agent 根目录 | - |

### 保险数据服务配置

| 变量 | 说明 |
|------|------|
| `DATA_SERVICE_MOCK` | 是否使用 Mock 数据 |
| `DATA_SERVICE_URL` | 数据服务 URL |
| `DATA_SERVICE_AUTH_URL` | 认证 URL |
| `DATA_SERVICE_APP_ID` | 应用 ID |
| `DATA_SERVICE_CLIENT_ID` | 客户端 ID |
| `DATA_SERVICE_CLIENT_SECRET` | 客户端密钥 |

### 证券服务配置

| 变量 | 说明 |
|------|------|
| `SECURITIES_SERVICE_MOCK` | 是否使用 Mock 数据 |
| `SECURITIES_ACCOUNT_TYPE` | 账户类型 |
| `SECURITIES_ACCOUNT_OVERVIEW_URL` | 账户概览 API |
| `SECURITIES_ETF_HOLDINGS_URL` | ETF 持仓 API |
| `SECURITIES_HKSC_HOLDINGS_URL` | 港股通持仓 API |
| `SECURITIES_FUND_HOLDINGS_URL` | 基金持仓 API |

**注意**: PA 模型专用变量（PA_SX_80B_APP_ID、PA_JT_OPEN_API_CODE 等）详见 `.env-sample`。

## 测试

```bash
uv run pytest -v

# 特定测试
uv run pytest tests/unit/core/test_runner.py -v
uv run pytest tests/unit/core/test_compaction.py -v

# 运行真实 LLM compaction 集成测试（需要 API_KEY + RUN_LLM_INTEGRATION=1）
export API_KEY=sk-xxx
export RUN_LLM_INTEGRATION=1
uv run pytest tests/unit/core/test_compaction.py -v
```

## 依赖管理

使用 `uv` 管理依赖 (PEP 723):

```bash
# 添加依赖
uv add httpx

# 移除依赖
uv remove httpx

# 运行脚本
uv run python script.py
```

## 性能优化

- **并行工具调用**: LLM 返回多个工具调用时，使用 `asyncio.gather()` 并行执行
- **AG-UI 流式协议**: 事件驱动架构，支持细粒度流式推送（20 种事件类型）
- **多协议适配**: 单一内部实现，输出层适配 4 种协议格式
- **零 DB 记忆**: 纯文件 MEMORY.md，无 SQLite/向量库依赖，启动即用
- **会话压缩**: 自动总结历史消息，保持上下文窗口稳定
- **输出验证**: 自动检测数值幻觉，提升输出可靠性

## 架构亮点

### AG-UI 流式协议
完整实现 AG-UI 标准的 20 种事件类型，支持：
- **生命周期事件**: run_started, run_finished, run_error
- **步骤事件**: step_started, step_finished
- **文本流**: text_message_start, text_message_content, text_message_end
- **思考流**: thinking_message_start, thinking_message_content, thinking_message_end（Thinking 模型 `reasoning_content` 字段原生推送）
- **工具调用**: tool_call_start, tool_call_args, tool_call_end, tool_call_result
- **状态同步**: state_snapshot, state_delta, messages_snapshot
- **自定义扩展**: custom, raw

### 多协议输出
单一内部实现（AG-UI 原生事件），输出层适配 4 种协议：
- **agui**: 裸 AG-UI 事件（原生输出）
- **internal**: 旧版 response.* 格式（向后兼容）
- **enterprise**: 企业 AGUI 信封（AGUIEnvelope 包装）
- **alone**: ALONE 协议（sa_* 事件）

### A2UI 组件系统
工具可返回 `ToolResultType.A2UI`，支持富交互前端组件：
- 卡片、按钮、表单、图表等
- 通过 `on_ui_component()` 回调流式推送
- 前端实时渲染交互界面

### Session State
跨工具调用的状态管理：
- 工具通过 `metadata.state_delta` 写入状态
- Runner 自动合并到 `session.state`
- 后续工具通过 `context` 读取状态

### 输出验证（后置 grounding）
基于 `before_loop_end` hook 的确定性幻觉检测：
- 模型只输出自然语言；系统从 `response.content` 提取实体（EntityTrie）、日期、业务数值
- 工具事实从 `session.messages` 中最后一条 USER 之后的 TOOL 消息提取，与最近若干轮用户消息一起做子串命中校验
- `retry` 路由下注入纠正反馈并重入 ReAct loop；`warn`/`safe` 正常落地

### 用户记忆系统
三层生命周期模型，详见 [docs/core/memory.md](docs/core/memory.md)：
- **Session JSONL = raw layer**：原始对话记录，append-only
- **MEMORY.md = distilled truth**：每用户一个文件，heading-based upsert
- **System Prompt = consumption**：每轮全量注入，Agent 无需手动检索
- **Dream 蒸馏**：后台周期性读取 session + memory → LLM 合并去重 → optimistic merge 回写
- **零 DB 依赖**：纯文件存储，无 SQLite/向量库/embedding 模型

## Studio 管理控制台

通过 `ENABLE_STUDIO=true` 环境变量启用 Studio 管理界面。

### 功能
- **Agent 管理**: 查看、测试已注册的 Agent
- **Skill 管理**: 浏览、编辑技能模板
- **Tool 管理**: 查看可用工具列表
- **Session 管理**: 查看会话历史、调试对话
- **Memory 管理**: 查看、编辑用户记忆

### 访问
启用后访问 `/studio` 路径即可进入管理界面。

```bash
# 启用 Studio
export ENABLE_STUDIO=true
ark-agentic-api

# 访问 http://localhost:8080/studio
```

## TODOs
- [P0] **存储层解耦**: 实现基于 Redis/Database 的 Session 和 Memory 存储，支持 Cloud-Native 分布式部署
- [P1] **SubAgent 支持**: 参考 openclaw-main 实现子智能体注册、生命周期管理、结果公告机制
- [P2] **Auth Profile / Failover**: 多 API Key 轮换、自动模型降级
- [P2] **会话写锁**: 防止并发写入冲突
- [P2] **远程嵌入支持**: OpenAI/Gemini Batch API 批量处理
