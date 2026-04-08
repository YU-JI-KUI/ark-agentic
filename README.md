# ark-agentic

轻量级 ReAct Agent 框架，支持工具调用、技能系统、会话管理、流式输出和用户记忆。

## 特性

- **ReAct 模式**: 推理-行动循环，支持并行工具调用
- **多 LLM 支持**: DeepSeek, PA 内部模型 (JT/SX 系列), OpenAI 兼容端点
- **技能系统**: Markdown 格式可复用指令集，支持 full/dynamic/semantic 三种加载模式
- **会话管理**: JSONL 持久化 + 智能上下文压缩（LLM 摘要）+ Session State 状态管理
- **用户记忆**: 文件级 MEMORY.md + heading-based upsert + Dream 周期蒸馏 + system prompt 全量注入
- **AG-UI 流式协议**: 完整的 17 种事件类型，支持 4 种输出格式（agui/internal/enterprise/alone）
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

**注意**: Memory 系统使用纯文件存储（MEMORY.md），无需额外依赖；PA-SX 系列和 DeepSeek 模型无需额外依赖，只有 PA-JT 系列模型需要 `pycryptodome` 进行 RSA 签名。

## 快速开始

```python
from ark_agentic.core.runner import AgentRunner
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.llm import create_chat_model
from ark_agentic.agents.insurance.tools import create_insurance_tools

llm = create_chat_model("deepseek-chat", api_key="sk-xxx")
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
  "idempotency_key": "req-12345"
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
- `agui`: AG-UI 原生事件（17 种事件类型）
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

*完整事件类型: `run_started`, `run_finished`, `run_error`, `step_started`, `step_finished`, `text_message_start`, `text_message_content`, `text_message_end`, `tool_call_start`, `tool_call_args`, `tool_call_end`, `tool_call_result`, `state_snapshot`, `state_delta`, `messages_snapshot`, `custom`, `raw`*

**自定义 Headers**:
```
x-ark-session-key: 会话ID前缀
x-ark-user-id: 用户ID
x-ark-trace-id: 追踪ID
```

## Docker

```bash
docker build -t ark-agentic .

docker run -d \
  -p 8080:8080 \
  -e API_KEY=sk-xxx \
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

# 初始化新项目（默认 deepseek）
uv run ark-agentic init my-agent

# 指定 LLM 提供商
uv run ark-agentic init my-openai-agent --llm-provider deepseek
# 添加FastAPI，chat API支持流式和非流式
uv run ark-agentic init my-pa-agent --llm-provider deepseek --api

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

- 当 `--llm-provider=deepseek`（默认）:

  ```bash
  LLM_PROVIDER=deepseek
  API_KEY=sk-xxx
  # LLM_BASE_URL=https://api.deepseek.com/v1
  ```

- 当 `--llm-provider=openai`:

  ```bash
  LLM_PROVIDER=openai
  API_KEY=sk-xxx
  # LLM_BASE_URL=https://api.openai.com/v1
  ```

- 当 `--llm-provider=pa`:

  ```bash
  LLM_PROVIDER=pa
  MODEL_NAME=PA-SX-80B
  # PA_SX_BASE_URL=https://pa-sx.example.com
  # PA_JT_BASE_URL=https://pa-jt.example.com
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

llm = create_chat_model("deepseek-chat", api_key="sk-xxx")

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

# DeepSeek (从环境变量读取 API_KEY)
llm = create_chat_model("deepseek-chat")

# 显式指定 API key
llm = create_chat_model("deepseek-chat", api_key="sk-xxx")

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
│   ├── runner.py          # AgentRunner (ReAct 主循环, 877 行)
│   ├── session.py         # SessionManager (会话管理, 452 行)
│   ├── compaction.py      # 上下文压缩 (714 行, LLM 摘要)
│   ├── persistence.py     # JSONL 持久化 (711 行)
│   ├── validation.py      # 输出验证（幻觉检测）
│   ├── types.py           # 核心类型定义 (358 行)
│   ├── llm/               # LLM 客户端 (LangChain-based)
│   │   ├── factory.py     # create_chat_model()
│   │   ├── pa_jt_llm.py   # PA-JT 系列支持
│   │   ├── pa_sx_llm.py   # PA-SX 系列支持
│   │   └── errors.py      # 错误分类
│   ├── tools/             # 工具系统
│   │   ├── base.py        # AgentTool 基类 (282 行)
│   │   ├── registry.py    # ToolRegistry
│   │   ├── memory.py      # Memory 工具 (377 行)
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
│   │   ├── events.py      # 17 种 AG-UI 事件类型
│   │   ├── event_bus.py   # StreamEventBus (208 行)
│   │   ├── output_formatter.py  # 4 种输出协议 (300 行)
│   │   ├── agui_models.py # 企业 AGUI 信封
│   │   └── assembler.py   # 流式组装器 (397 行)
│   └── prompt/            # 提示词构建
│       └── builder.py     # SystemPromptBuilder (300 行)
├── agents/
│   └── insurance/         # 保险智能体示例
│       ├── agent.py       # 入口 (428 行)
│       ├── api.py         # 工厂函数
│       ├── tools/         # 业务工具
│       │   ├── policy_query.py
│       │   ├── customer_info.py
│       │   ├── data_service.py  # 模拟数据服务 (617 行)
│       │   └── rule_engine.py   # 规则引擎 (399 行)
│       └── skills/        # 业务技能
│           ├── withdraw_money/
│           ├── clarify_need/
│           └── rewrite_plan/
├── app.py                 # FastAPI 应用 (372 行)
└── static/                # Web UI

总计: ~24K 行代码（53 个 Python 文件）
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `API_KEY` | OpenAI 兼容端点 API Key | - |
| `MODEL_NAME` | 模型 id（PA 时为 PA-SX-80B 等，兼容时为 deepseek-chat / gpt-4o 等） | - |
| `DEFAULT_TEMPERATURE` | LLM 温度 | `0.7` |
| `API_HOST` | API 监听地址 | `0.0.0.0` |
| `API_PORT` | API 端口 | `8080` |
| `SESSIONS_DIR` | 会话存储目录 | `/data/sessions` |
| `MEMORY_DIR` | Memory 数据目录 | `/data/memory` |

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
- **AG-UI 流式协议**: 事件驱动架构，支持细粒度流式推送（17 种事件类型）
- **多协议适配**: 单一内部实现，输出层适配 4 种协议格式
- **零 DB 记忆**: 纯文件 MEMORY.md，无 SQLite/向量库依赖，启动即用
- **会话压缩**: 自动总结历史消息，保持上下文窗口稳定
- **输出验证**: 自动检测数值幻觉，提升输出可靠性

## 架构亮点

### AG-UI 流式协议
完整实现 AG-UI 标准的 17 种事件类型，支持：
- **生命周期事件**: run_started, run_finished, run_error
- **步骤事件**: step_started, step_finished
- **文本流**: text_message_start, text_message_content, text_message_end
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

### 输出验证
自动检测 LLM 输出与工具结果的数值一致性：
- 提取 LLM 输出中的数字
- 对比工具返回的数值
- 检测幻觉并记录警告

### 用户记忆系统
三层生命周期模型，详见 [docs/core/memory.md](docs/core/memory.md)：
- **Session JSONL = raw layer**：原始对话记录，append-only
- **MEMORY.md = distilled truth**：每用户一个文件，heading-based upsert
- **System Prompt = consumption**：每轮全量注入，Agent 无需手动检索
- **Dream 蒸馏**：后台周期性读取 session + memory → LLM 合并去重 → optimistic merge 回写
- **零 DB 依赖**：纯文件存储，无 SQLite/向量库/embedding 模型

## TODOs
- [P0] **存储层解耦**: 实现基于 Redis/Database 的 Session 和 Memory 存储，支持 Cloud-Native 分布式部署
- [P1] **SubAgent 支持**: 参考 openclaw-main 实现子智能体注册、生命周期管理、结果公告机制
- [P1] **CLI 工具 (ark-cli)**: 开发命令行工具，支持一键生成 Agent 骨架，降低上手门槛
- [P2] **Auth Profile / Failover**: 多 API Key 轮换、自动模型降级
- [P2] **会话写锁**: 防止并发写入冲突
- [P2] **远程嵌入支持**: OpenAI/Gemini Batch API 批量处理

