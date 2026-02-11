# ark-agentic

轻量级 ReAct Agent 框架，支持工具调用、技能系统、会话管理、流式输出和向量记忆。

## 特性

- **ReAct 模式**: 推理-行动循环，支持并行工具调用
- **多 LLM 支持**: DeepSeek, PA 内部 API, Mock（OpenAI 兼容协议）
- **技能系统**: Markdown 格式可复用指令集
- **会话管理**: JSONL 持久化 + 智能上下文压缩
- **向量记忆**: FAISS + Sentence-Transformers 语义搜索
- **流式输出**: SSE 实时响应
- **FastAPI 服务**: 生产就绪的 HTTP API

## 安装

```bash
uv add git+https://github.com/your-org/ark-agentic.git

# 或本地开发
uv pip install -e .
```

## 快速开始

```python
from ark_agentic.core.runner import AgentRunner
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools.registry import ToolRegistry
from ark_agentic.core.llm import create_llm_client
from ark_agentic.agents.insurance.tools import create_insurance_tools

llm_client = create_llm_client("deepseek", api_key="sk-xxx")
tool_registry = ToolRegistry()
tool_registry.register_all(create_insurance_tools())

agent = AgentRunner(
    llm_client=llm_client,
    tool_registry=tool_registry,
    session_manager=SessionManager(),
)

session_id = await agent.create_session()
result = await agent.run(session_id, "我想取点钱")
```

## API 服务

```bash
export DEEPSEEK_API_KEY=sk-xxx
ark-agentic-api
```

### 端点

```http
POST /chat
Content-Type: application/json

{
  "message": "用户消息",
  "session_id": "可选会话ID",
  "stream": true,
  "context": {"user_id": "U001"}
}
```

**SSE 事件格式**:
```json
{
  "run_id": "uuid",
  "session_id": "uuid",
  "state": "delta|final|error",
  "content": "流式片段",
  "usage": {"input_tokens": 100, "output_tokens": 50}
}
```

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
  -e DEEPSEEK_API_KEY=sk-xxx \
  -v ark-sessions:/data/sessions \
  -v ark-memory:/data/memory \
  ark-agentic
```

## CLI 示例

```bash
# Mock 模式演示（无需 API Key）
python -m ark_agentic.agents.insurance.agent --mock --demo

# 交互模式
export DEEPSEEK_API_KEY=sk-xxx
python -m ark_agentic.agents.insurance.agent -i

# 持久化 + Memory
python -m ark_agentic.agents.insurance.agent -i \
  --persistence --sessions-dir ./data/sessions \
  --memory --memory-dir ./data/memory
```

## 核心概念

### 工具定义

```python
from ark_agentic.core.tools.base import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult

class PolicyQuery(AgentTool):
    name = "policy_query"
    description = "查询用户保单信息"
    parameters = [
        ToolParameter(name="user_id", type="string", required=True),
        ToolParameter(name="query_type", type="string", required=True),
    ]

    async def execute(self, tool_call, context=None):
        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data={"policies": [...]}
        )
```

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

### 会话压缩

```python
from ark_agentic.core.compaction import CompactionConfig, LLMSummarizer

session_manager = SessionManager(
    compaction_config=CompactionConfig(
        context_window=32000,
        preserve_recent=4,  # 保留最近4轮对话
    ),
    summarizer=LLMSummarizer(llm_client),
)
```

### 向量记忆

```python
from ark_agentic.core.memory import MemoryManager, MemoryConfig

memory_manager = MemoryManager(
    MemoryConfig(
        workspace_dir="./data/memory",
        index_dir="./data/memory/.index",
    )
)

# 自动注册 memory_search 和 memory_get 工具
agent = AgentRunner(
    llm_client=llm_client,
    tool_registry=tool_registry,
    session_manager=session_manager,
    memory_manager=memory_manager,
)
```

### LLM 客户端

```python
from ark_agentic.core.llm import create_llm_client, DynamicValues

# DeepSeek (从环境变量读取)
client = create_llm_client("deepseek")

# PA 内部 API
client = create_llm_client("pa", pa_model="PA-SX-80B")

# Mock (演示/测试)
client = create_llm_client("mock")

# 自定义 headers/body
client = create_llm_client(
    "deepseek",
    api_key="sk-xxx",
    extra_headers={"x-trace-id": DynamicValues.uuid()},
    extra_body={"reqId": DynamicValues.uuid()},
)
```

## 项目结构

```
src/ark_agentic/
├── core/
│   ├── runner.py          # AgentRunner (ReAct 主循环)
│   ├── session.py         # SessionManager (会话管理)
│   ├── compaction.py      # 上下文压缩
│   ├── llm/               # LLM 客户端
│   │   ├── factory.py     # create_llm_client()
│   │   ├── openai_compat.py
│   │   ├── pa_internal_llm.py
│   │   └── mock.py
│   ├── tools/             # 工具系统
│   │   ├── base.py        # AgentTool 基类
│   │   ├── registry.py    # ToolRegistry
│   │   └── memory.py      # Memory 工具
│   ├── skills/            # 技能系统
│   │   ├── base.py
│   │   ├── loader.py
│   │   └── matcher.py
│   ├── memory/            # 向量记忆
│   │   ├── manager.py
│   │   ├── embeddings.py
│   │   ├── vector_store.py
│   │   └── hybrid.py      # 混合检索
│   ├── stream/            # 流式输出
│   │   └── assembler.py
│   └── prompt/            # 提示词构建
│       └── builder.py
├── agents/
│   └── insurance/         # 保险智能体示例
│       ├── agent.py
│       ├── api.py
│       ├── tools/
│       └── skills/
├── app.py                 # FastAPI 应用
└── static/                # Web UI
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `DEFAULT_TEMPERATURE` | LLM 温度 | `0.7` |
| `API_HOST` | API 监听地址 | `0.0.0.0` |
| `API_PORT` | API 端口 | `8080` |
| `SESSIONS_DIR` | 会话存储目录 | `/data/sessions` |
| `MEMORY_DIR` | Memory 数据目录 | `/data/memory` |

## 测试

```bash
uv run pytest -v

# 特定测试
uv run pytest tests/core/test_runner_concurrency.py -v
uv run pytest tests/core/test_memory_tools.py -v
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
- **流式响应**: SSE 实时推送 LLM 输出，降低首字延迟
- **FAISS 索引**: 向量检索支持百万级文档
- **会话压缩**: 自动总结历史消息，保持上下文窗口稳定

## 许可

MIT
