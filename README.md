# Agent Framework

基于 ReAct 模式的智能体框架，支持工具调用、技能系统、会话管理和流式输出。

## 快速开始

```python
from ark_nav.core.agent import (
    AgentRunner, RunnerConfig, SessionManager,
    create_llm_client, ToolRegistry
)
from ark_nav.core.agent.tools.insurance import create_insurance_tools

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

## 核心概念

### ReAct 循环

Agent 采用 ReAct（Reason-Act）模式，每次用户输入会触发循环：

```
用户输入 → LLM推理 → 工具调用 → LLM推理 → 工具调用 → ... → 最终回复
```

**一次用户请求可能触发多轮 LLM 调用**

### 并行工具调用

LLM 可以在一次响应中返回多个工具调用，框架会**并行执行**：

```python
# LLM 返回的 tool_calls 示例
tool_calls = [
    {"name": "user_profile", "arguments": {"user_id": "U001"}},
    {"name": "policy_query", "arguments": {"user_id": "U001", "query_type": "list"}},
]
# 这两个工具会并行执行，而不是串行
```

**如何让 LLM 一次调用多个工具？** 通过 System Prompt 指导：

```python
PROMPT = """
## 工作流程

当用户提出需求时，**同时调用**以下工具获取信息：
1. `user_profile` - 获取用户画像
2. `policy_query` - 查询保单信息

注意：这两个工具可以并行调用，不要分开调用。
"""
```

## 工具系统

### 定义工具

```python
from ark_nav.core.agent.tools.base import AgentTool, ToolParameter

class MyTool(AgentTool):
    name = "my_tool"
    description = "工具描述，LLM 根据此决定是否调用"
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
        # 执行逻辑
        return AgentToolResult(tool_call_id=tool_call.id, output={"result": "..."})
```

### 工具依赖

工具之间的依赖通过 **System Prompt** 定义执行顺序：

```python
PROMPT = """
## 工具调用顺序

1. **信息收集阶段**（可并行）：
   - `user_profile`: 获取用户画像
   - `policy_query`: 查询保单

2. **计算阶段**（依赖第1阶段结果）：
   - `rule_engine`: 根据用户信息和保单计算方案
   
注意：`rule_engine` 需要在获取用户和保单信息后再调用。
"""
```

**框架不强制工具顺序**，而是通过 Prompt 引导 LLM 按正确顺序调用。这更灵活，LLM 可以根据实际情况判断。

### 工具分组示例

```python
# 定义工具分组
class PolicyQueryTool(AgentTool):
    name = "policy_query"
    group = "data_retrieval"  # 数据获取组

class RuleEngineTool(AgentTool):
    name = "rule_engine"
    group = "computation"  # 计算组
```

Prompt 中引用分组：

```python
PROMPT = """
工具分为两类：
- 数据获取类（data_retrieval）：可并行调用
- 计算类（computation）：需要数据获取完成后调用
"""
```

## 减少 LLM 调用次数

### 方法一：优化 Prompt

```python
PROMPT = """
重要：收到用户请求后，请一次性调用所有需要的工具：

✅ 正确做法：
同时调用 user_profile 和 policy_query

❌ 错误做法：
先调用 user_profile，等结果后再调用 policy_query
"""
```

### 方法二：合并工具

将多个小工具合并为一个大工具：

```python
class CustomerDataTool(AgentTool):
    """合并用户画像和保单查询"""
    name = "get_customer_data"
    
    async def execute(self, tool_call, context=None):
        user_id = tool_call.arguments["user_id"]
        # 内部并行获取所有数据
        profile, policies = await asyncio.gather(
            self._get_profile(user_id),
            self._get_policies(user_id),
        )
        return AgentToolResult(
            tool_call_id=tool_call.id,
            output={"profile": profile, "policies": policies}
        )
```

### 方法三：工具结果缓存

对于相同参数的重复调用，工具内部实现缓存：

```python
class CachedTool(AgentTool):
    def __init__(self):
        self._cache = {}
    
    async def execute(self, tool_call, context=None):
        cache_key = json.dumps(tool_call.arguments, sort_keys=True)
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        result = await self._do_execute(tool_call)
        self._cache[cache_key] = result
        return result
```

## 技能系统

技能是可复用的指令集，以 Markdown 文件存储：

```markdown
<!-- skills/insurance/withdrawal.md -->
---
name: insurance_withdrawal
description: 保险取款业务处理
invocation_policy: auto
eligibility_rules:
  - type: context_match
    field: intent
    pattern: "取款|领取|贷款"
---

# 取款业务技能

## 业务规则
- 部分领取：最高可领取账户价值的 80%
- 保单贷款：最高可贷现金价值的 80%

## 处理流程
1. 确认用户身份
2. 查询可用额度
3. 生成推荐方案
```

加载技能：

```python
from ark_nav.core.agent.skills import SkillLoader, SkillConfig

skill_loader = SkillLoader(SkillConfig(
    skill_directories=["skills/insurance"],
))
skill_loader.load_from_directories()
```

## 会话管理

### 持久化

```python
session_manager = SessionManager(
    sessions_dir="./sessions",      # 会话存储目录
    enable_persistence=True,        # 启用持久化
)

# 会话数据存储为 JSONL 格式
# sessions/
#   sessions.json           # 会话元数据索引
#   {session_id}.jsonl      # 每个会话的消息记录
```

### 上下文压缩

当消息历史过长时，自动压缩：

```python
from ark_nav.core.agent.compaction import CompactionConfig

session_manager = SessionManager(
    compaction_config=CompactionConfig(
        context_window=32000,       # 上下文窗口大小
        preserve_recent=4,          # 保留最近 N 条消息
        safety_margin=0.1,          # 安全边际
    ),
)
```

## LLM 客户端

### 支持的提供商

```python
from ark_nav.core.agent.llm import create_llm_client

# DeepSeek
client = create_llm_client("deepseek", api_key="sk-xxx")

# Gemini (通过 OpenAI 兼容端点)
client = create_llm_client("gemini", api_key="xxx")

# OpenAI
client = create_llm_client("openai", api_key="sk-xxx")

# 内部 API
client = create_llm_client(
    "internal",
    base_url="http://api.internal.com/chat",
    authorization="Bearer xxx",
    trace_appid="my-app",
)
```

### 环境变量

```bash
export DEEPSEEK_API_KEY=sk-xxx
export GEMINI_API_KEY=xxx
export OPENAI_API_KEY=sk-xxx
```

## 目录结构

```
agent/
├── __init__.py          # 模块导出
├── runner.py            # AgentRunner 主执行器
├── session.py           # 会话管理
├── persistence.py       # 持久化（JSONL）
├── compaction.py        # 上下文压缩
├── types.py             # 类型定义
├── llm/                 # LLM 客户端
│   ├── base.py          # 协议定义
│   ├── openai_compat.py # OpenAI 兼容客户端
│   ├── internal.py      # 内部 API 客户端
│   └── factory.py       # 工厂函数
├── tools/               # 工具系统
│   ├── base.py          # AgentTool 基类
│   ├── registry.py      # 工具注册器
│   └── insurance/       # 保险业务工具
├── skills/              # 技能系统
│   ├── base.py          # 技能配置
│   ├── loader.py        # 技能加载
│   └── matcher.py       # 技能匹配
├── prompt/              # 提示词构建
│   └── builder.py       # SystemPromptBuilder
└── stream/              # 流式输出
    └── assembler.py     # 流式响应组装
```

## 完整示例

参见 `examples/insurance_withdrawal_agent.py`：

```bash
# 使用 DeepSeek
export DEEPSEEK_API_KEY=sk-xxx
python examples/insurance_withdrawal_agent.py

# 使用 Mock（无需 API Key）
python examples/insurance_withdrawal_agent.py --mock --demo
```
