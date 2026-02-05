# ark-agentic

基于 ReAct 模式的 Python 智能体框架，支持工具调用、技能系统、会话管理、流式输出和记忆系统。

## 安装

```bash
# 使用 uv (推荐)
uv pip install -e .

# 或使用 pip
pip install -e .
```

## 快速开始

```python
from ark_agentic.core.runner import AgentRunner, RunnerConfig
from ark_agentic.core.session import SessionManager
from ark_agentic.core.tools import ToolRegistry
from ark_agentic.core.llm import create_llm_client
from ark_agentic.agents.insurance.tools import create_insurance_tools

# 1. 创建 LLM 客户端
llm_client = create_llm_client("deepseek", api_key="sk-xxx")

# 2. 注册工具
tool_registry = ToolRegistry()
tool_registry.register_all(create_insurance_tools())

# 3. 创建 Agent
agent = AgentRunner(
    llm_client=llm_client,
    tool_registry=tool_registry,
    session_manager=SessionManager(),
)

# 4. 运行
session_id = await agent.create_session()
result = await agent.run(session_id, "我想取点钱")
print(result.response.content)
```

## API 服务

### 启动服务

```bash
# 设置环境变量
export DEEPSEEK_API_KEY=sk-xxx

# 启动 API (端口 8080)
ark-agentic-api

# 或指定端口
API_HOST=0.0.0.0 API_PORT=8080 ark-agentic-api
```

### API 端点

```bash
# 健康检查
GET /health

# 非流式对话
POST /chat
Content-Type: application/json

{
  "message": "我想取点钱",
  "session_id": "optional-session-id",
  "stream": false,
  "user_id": "U001",
  "context": {"channel": "app"}
}

# 流式对话 (SSE)
POST /chat
Content-Type: application/json

{
  "message": "我想取点钱",
  "stream": true
}
```

### SSE 事件格式

```json
{
  "run_id": "uuid",
  "session_id": "uuid",
  "seq": 1,
  "state": "delta|final|error",
  "content": "流式内容片段",
  "message": "完整响应 (state=final)",
  "tool_calls": [...],
  "usage": {"input_tokens": 100, "output_tokens": 50}
}
```

### 自定义 Headers

```
x-ark-session-key: 自定义会话ID前缀
x-ark-user-id: 用户ID
x-ark-trace-id: 链路追踪ID
```

## Docker 部署

```bash
# 构建镜像
docker build -t ark-agentic .

# 运行容器
docker run -d \
  -p 8080:8080 \
  -e DEEPSEEK_API_KEY=sk-xxx \
  -v ark-sessions:/data/sessions \
  -v ark-memory:/data/memory \
  ark-agentic
```

## CLI 使用

```bash
# 交互模式 (默认使用 DeepSeek)
export DEEPSEEK_API_KEY=sk-xxx
python -m ark_agentic.agents.insurance.agent -i

# Mock 模式演示 (无需 API Key)
python -m ark_agentic.agents.insurance.agent --mock --demo

# 使用 Gemini
python -m ark_agentic.agents.insurance.agent --provider gemini

# 启用 Memory 系统
python -m ark_agentic.agents.insurance.agent --mock --demo --memory

# 启用会话持久化
python -m ark_agentic.agents.insurance.agent --persistence --sessions-dir ./sessions
```

## 核心概念

### ReAct 循环

Agent 采用 ReAct（Reason-Act）模式：

```
用户输入 → LLM推理 → 工具调用 → LLM推理 → 工具调用 → ... → 最终回复
```

### 并行工具调用

LLM 可以在一次响应中返回多个工具调用，框架会并行执行。

## 工具系统

### 定义工具

```python
from ark_agentic.core.tools import AgentTool, ToolParameter
from ark_agentic.core.types import AgentToolResult

class MyTool(AgentTool):
    name = "my_tool"
    description = "工具描述"
    parameters = [
        ToolParameter(
            name="param1",
            type="string",
            description="参数说明",
            required=True,
        ),
    ]

    async def execute(self, tool_call, context=None):
        args = tool_call.arguments
        return AgentToolResult.json_result(
            tool_call_id=tool_call.id,
            data={"result": "..."},
        )
```

## 技能系统

技能是可复用的指令集，以 Markdown 文件存储：

```markdown
<!-- skills/withdrawal.md -->
---
name: insurance_withdrawal
description: 保险取款业务处理
invocation_policy: auto
---

# 取款业务技能

## 业务规则
- 部分领取：最高可领取账户价值的 80%
- 保单贷款：最高可贷现金价值的 80%
```

## Memory 系统

Memory 系统提供语义搜索能力，自动注册为 Agent 工具：

```python
from ark_agentic.core.memory import MemoryManager, MemoryConfig
from ark_agentic.core.runner import AgentRunner

# 配置 Memory
memory_config = MemoryConfig(
    workspace_dir="./",
    index_dir="./memory_index",
)
memory_manager = MemoryManager(memory_config)

# 创建 Agent 时传入
agent = AgentRunner(
    llm_client=llm_client,
    tool_registry=tool_registry,
    session_manager=session_manager,
    memory_manager=memory_manager,  # 自动注册 memory_search/memory_get 工具
)
```

### Memory 工具

- `memory_search`: 语义搜索 MEMORY.md 和 memory/*.md
- `memory_get`: 读取指定文件的行范围

## 会话管理

### 持久化

```python
session_manager = SessionManager(
    sessions_dir="./sessions",
    enable_persistence=True,
)
```

会话数据存储为 JSONL 格式：
```
sessions/
  sessions.json           # 会话元数据索引
  {session_id}.jsonl      # 消息记录
```

### 上下文压缩

```python
from ark_agentic.core.compaction import CompactionConfig

session_manager = SessionManager(
    compaction_config=CompactionConfig(
        context_window=32000,
        preserve_recent=4,
    ),
)
```

## LLM 客户端

```python
from ark_agentic.core.llm import create_llm_client

# DeepSeek
client = create_llm_client("deepseek", api_key="sk-xxx")

# Gemini
client = create_llm_client("gemini", api_key="xxx")

# 内部 API
client = create_llm_client(
    "internal",
    base_url="http://api.internal.com/chat",
    authorization="Bearer xxx",
)
```

## 项目结构

```
ark-agentic/
├── src/ark_agentic/
│   ├── core/               # 核心框架
│   │   ├── runner.py       # AgentRunner
│   │   ├── session.py      # 会话管理
│   │   ├── compaction.py   # 上下文压缩
│   │   ├── tools/          # 工具系统
│   │   ├── skills/         # 技能系统
│   │   ├── prompt/         # 提示词构建
│   │   ├── llm/            # LLM 客户端
│   │   ├── memory/         # 记忆系统
│   │   └── stream/         # 流式输出
│   ├── agents/             # 业务 Agent
│   │   └── insurance/      # 保险智能体示例
│   └── api/                # FastAPI 服务
│       └── app.py
├── tests/                  # 单元测试
├── Dockerfile              # Docker 镜像
└── pyproject.toml          # 项目配置
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `GEMINI_API_KEY` | Gemini API Key | - |
| `API_HOST` | API 监听地址 | `0.0.0.0` |
| `API_PORT` | API 端口 | `8080` |
| `SESSIONS_DIR` | 会话存储目录 | `/data/sessions` |
| `MEMORY_DIR` | Memory 数据目录 | `/data/memory` |

## 测试

```bash
# 运行所有测试
uv run pytest -v

# 运行特定测试
uv run pytest tests/core/test_memory_tools.py -v
```
