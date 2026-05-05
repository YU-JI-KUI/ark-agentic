# ark-agentic

`ark-agentic` 是一个面向业务落地的 Agentic 基础框架，同时提供 `ark-agentic` CLI 用来生成业务项目脚手架。

本文分两条路径：

- **业务应用开发者**：用 CLI 生成项目，专注写 agent、tools、skills、prompt 和业务逻辑。
- **框架开发者**：维护 `ark-agentic` 本身，包括核心运行时、CLI、内置插件（HTTP / Studio / Jobs / Notifications）和发布流程。

如果你是新人，判断自己属于哪一类后，直接跳到对应章节即可。

## 路径一：业务应用开发者

### 1. 你会得到什么

`ark-agentic` CLI 会生成一个开箱可改的业务项目骨架，默认包含：

- 一个可运行的 `default` agent
- 一个终端交互入口
- 默认包含 FastAPI 服务入口（用 `ark-agentic init --no-api` 可仅生成 CLI 项目）
- Studio 接入位（通过环境变量按需启用）
- 业务工具、技能目录和基础测试目录

业务团队的职责应该集中在这些事情上：

- 定义业务工具
- 编排 agent prompt 和能力边界
- 接入业务系统
- 按需扩展 API、UI 和多 agent 协作

而不是从零搭框架运行时。

### 2. 先安装 CLI

前提是你已经能从团队内部源或发布源安装 `ark-agentic` 包，常见方式如下：

```bash
uv tool install ark-agentic
# 或
pip install ark-agentic
```

### 3. 创建脚手架项目

如果你已经安装并发布了 `ark-agentic` 包，直接使用命令：

```bash
ark-agentic init my-agent
```

如果你当前就在这个框架仓库里验证 CLI，可以直接运行：

```bash
uv run ark-agentic init my-agent
```

可选参数：

- `--no-api`：生成纯 CLI 项目（不含 `app.py` / Bootstrap 装配）；**默认**生成含 API 的完整项目。

### 4. 初始化后的第一步

```bash
cd my-agent
uv pip install -e .
cp .env-sample .env
```

然后按你的模型供应商填写 `.env`。默认会生成类似下面的配置：

```bash
LLM_PROVIDER=openai
MODEL_NAME=gpt-4o
API_KEY=sk-xxx
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_BASE_URL_IS_FULL_URL=false
# 完整请求 URL 示例:
# LLM_BASE_URL=https://service-host/chat/dialog
# LLM_BASE_URL_IS_FULL_URL=true
```

### 5. 脚手架目录怎么理解

执行 `ark-agentic init my-agent` 后，核心目录大致如下：

```text
my-agent/
├── .env-sample
├── pyproject.toml
├── pip.conf
├── src/
│   └── my_agent/
│       ├── main.py
│       ├── app.py
│       ├── static/
│       └── agents/
│           ├── __init__.py
│           └── default/
│               ├── __init__.py
│               ├── agent.py
│               ├── agent.json
│               ├── skills/
│               └── tools/
└── tests/
```

重点文件说明：

- `src/<package>/agents/default/agent.py`
  你的主入口。这里创建 `AgentRunner`、注册工具、配置会话和 prompt。
- `src/<package>/agents/default/tools/`
  放业务工具实现。通常业务开发最常改这里。
- `src/<package>/main.py`
  终端交互入口，适合快速验证 agent 行为。
- `src/<package>/app.py`
  HTTP 服务入口。使用 `init --no-api` 时不会生成该文件。
- `src/<package>/agents/default/agent.json`
  agent 元信息，给 Studio 和管理侧使用。
- `src/<package>/agents/default/skills/`
  预留技能目录，按需添加 Markdown 技能文件。

### 6. 第一次应该改哪几个地方

建议按这个顺序：

1. 改 `src/<package>/agents/default/agent.py`
2. 在 `tools/` 下增加你的业务工具
3. 填写 `.env`
4. 跑通终端模式
5. 再决定是否接 API / Studio / 多 agent

`agent.py` 里通常最先改这几处：

- `_DEF = AgentDef(...)`：改 `agent_name` / `agent_description` 描述 agent 职责
- `create_<agent>_tools()`（在 `tools/__init__.py`）：返回业务工具列表
- `AgentDef.system_protocol` / `custom_instructions`：补充提示词约束（可选）
- `AgentDef.max_turns`：根据场景调整推理轮次（默认 10）
- `enable_memory=True`：需要长期记忆时打开

### 7. 如何启动业务项目

终端交互模式：

```bash
uv run python -m my_agent.main
```

API 模式：

```bash
uv run python -m my_agent.app
```

启动后通常可用：

- `GET /health`
- `POST /chat`
- `GET /docs`

如果要启用 Studio：

```bash
export ENABLE_STUDIO=true
uv run python -m my_agent.app
```

### 8. 如何继续加新的业务 Agent

在已生成的业务项目根目录执行：

```bash
ark-agentic add-agent risk-engine
```

如果你还在这个框架仓库里本地验证：

```bash
uv run ark-agentic add-agent risk-engine
```

它会新增：

- `src/<package>/agents/risk_engine/agent.py`
- `src/<package>/agents/risk_engine/tools/`
- `src/<package>/agents/risk_engine/skills/`
- `src/<package>/agents/risk_engine/agent.json`

新增后你还需要自己完成两件事：

- 在业务项目的入口中注册这个 agent
- 决定它是否暴露成独立 API 或和其他 agent 共用服务入口

### 9. 业务开发者最小工作流

最推荐的上手路径是：

1. `ark-agentic init` 创建项目
2. 先只改 `default/agent.py` 和 `tools/`
3. 用 `python -m <package>.main` 验证单 agent 行为
4. 确认业务逻辑后，再启动 `app.py` 提供的 HTTP 服务
5. 最后再考虑 Studio、记忆、可观测性和多 agent

这样能避免一开始就把精力浪费在框架细节上。

## 路径二：框架开发者

### 1. 这个仓库的职责

这个仓库维护的是 `ark-agentic` 底座本身，包括：

- Agent 运行时
- Tool / Skill / Session / Memory 等基础能力
- CLI 脚手架生成器
- 内置插件提供的 FastAPI、Studio、Jobs、Notifications 等能力
- 发布打包流程

业务团队最终应该更多地依赖这个仓库发布出的包和 CLI，而不是直接在本仓库里改业务逻辑。

### 2. 框架代码主要在哪些目录

```text
src/ark_agentic/
├── cli/             # 脚手架 CLI
├── core/            # 运行时骨架：runner、session、tools、skills、memory、llm、stream、observability...
├── plugins/         # 可选能力层（由 Bootstrap 统一管理生命周期）
│   ├── api/         # Chat HTTP 传输（ENABLE_API，默认开启）
│   ├── studio/      # 可视化管理控制台（ENABLE_STUDIO）
│   ├── jobs/        # 主动任务调度（ENABLE_JOB_MANAGER）
│   └── notifications/ # 通知与 SSE（ENABLE_NOTIFICATIONS，或与 Jobs 联动）
├── portal/          # 框架自身展示门户（开发期使用，不随 wheel 发布）
├── agents/          # 仓库内置示例 / 内部 agent
└── app.py           # 仓库内统一演示服务入口
```

建议这样理解：

- `core/`、`cli/`、`plugins/`（尤其是 `plugins/api/`、`plugins/studio/`）是框架主干
- `agents/` 更多是示例、内部场景或回归验证资产
- 发布给业务团队的重点是 CLI + 核心运行时，而不是仓库里的全部示例

### 3. 本地开发环境

安装 Python 依赖：

```bash
uv sync
```

如果你需要 Studio 前端资源，先构建前端：

```bash
npm install --prefix src/ark_agentic/studio/frontend
npm run build --prefix src/ark_agentic/studio/frontend
```

常用开发命令：

```bash
uv run ark-agentic --help
uv run python -m ark_agentic.app
uv run pytest
```

### 4. 建议的框架开发验证顺序

每次改动后，至少做这三类验证：

1. CLI 是否还能正常生成脚手架
2. API 演示服务是否还能启动
3. 单元测试 / 集成测试是否通过

如果你改的是这些模块，优先看对应目录：

- 改脚手架：`src/ark_agentic/cli/`
- 改运行时：`src/ark_agentic/core/`
- 改 HTTP 协议：`src/ark_agentic/plugins/api/`
- 改 Studio：`src/ark_agentic/plugins/studio/`

### 5. 发布方式

发布脚本在 `scripts/publish.sh`：

```bash
./scripts/publish.sh --dry-run
./scripts/publish.sh
```

这个脚本会做两件事：

1. 构建 Studio 前端
2. 构建并上传 Python 包

发布边界需要特别注意：

- wheel 主要面向框架能力和 CLI
- 仓库内的内部 agent、演示 app、部分静态资源不会作为业务脚手架依赖的一部分对外暴露

也就是说，发布产物是“框架底座”，不是“整个仓库原样打包”。

## 框架架构：Core + Plugin

**Core**（`src/ark_agentic/core/`）是框架骨架：`AgentRunner`、会话、工具与技能、Memory、LLM、流式事件、可观测性等都放在这里。Core **不** import 任何 Plugin。

**Plugin** 是可选能力层：通过 `Bootstrap` 统一注册、初始化、挂载路由、启停。业务项目模板里的 `app.py` 会装配一组内置 Plugin；是否生效由各 `ENABLE_*` 环境变量决定。

脚手架中的典型装配顺序如下（**顺序即依赖顺序**——`JobsPlugin` 依赖 `NotificationsPlugin` 先启动）：

```python
Bootstrap(
    plugins=[
        APIPlugin(),
        NotificationsPlugin(),
        JobsPlugin(),
        StudioPlugin(),
    ],
)
```

### Core 子包（节选）

| 子包 | 职责 |
|------|------|
| `runtime/` | `AgentRunner`、ReAct 循环、回调与工厂 |
| `protocol/` | `Bootstrap`、`BasePlugin`、`AppContext`、生命周期协议 |
| `session/` | 会话管理、持久化、上下文压缩 |
| `tools/` / `skills/` | 工具注册与执行、技能加载与路由 |
| `memory/` | Memory、抽取、用户画像 |
| `stream/` | 流式事件、AG-UI 相关模型 |
| `llm/` | 多厂商模型封装、重试、采样 |
| `observability/` | OTel / Phoenix / Langfuse 等追踪 |
| `a2ui/` | A2UI 富交互组件 |
| `storage/` | 存储抽象（文件 / SQLite 等） |

### 内置 Plugin 一览

| Plugin | 环境变量（默认） | 核心职责 | 对外 HTTP（节选） |
|--------|------------------|----------|-------------------|
| **APIPlugin** | `ENABLE_API=true` | Chat HTTP 传输、CORS、健康检查、静态 demo；绑定 `AgentRegistry` | `POST /chat`，`GET /health`，`GET /`，`/api/static/*` |
| **StudioPlugin** | `ENABLE_STUDIO=false` | 管理控制台；独立 SQLite 鉴权；React SPA | `/api/studio/*`，`/studio` |
| **NotificationsPlugin** | `ENABLE_NOTIFICATIONS=false`（或与 Jobs 联动开启） | 通知仓储、SSE；为 Jobs 提供投递通道 | `/api/notifications/...`，`/api/notifications/.../stream` |
| **JobsPlugin** | `ENABLE_JOB_MANAGER=false` | APScheduler 主动调度、用户分片扫描；经 Notifications 投递 | `/api/jobs`，`/api/jobs/{id}/dispatch`（路由由 notifications 侧注册） |

Plugin 之间通过 `AppContext` 交换数据（例如 `ctx.notifications.service.delivery` 供 Jobs 使用），而不是在 Core 里硬编码依赖。

## CLI 参考

### `ark-agentic init`

```bash
ark-agentic init <project_name> [--no-api]
```

用途：

- 初始化一个新的业务 Agent 项目（默认生成含 API / Bootstrap 装配的完整结构）
- `--no-api`：仅生成 CLI 项目，不含 `app.py`

### `ark-agentic add-agent`

```bash
ark-agentic add-agent <agent_name>
```

用途：

- 在已有业务项目里新增一个 agent 模块骨架

### `ark-agentic version`

```bash
ark-agentic version
```

用途：

- 查看当前 CLI / 框架版本

## 框架核心模型

无论是仓库内示例，还是 CLI 生成的业务项目，本质上都围绕同一个运行模型：

```text
AgentDef                     ← 描述这是哪个 agent、能做什么
 + skills/ 目录              ← 行为脚本
 + tools 列表                ← 业务能力
 + build_standard_agent()    ← 框架按约定补齐 session / memory / compaction / prompt
 => AgentRunner
```

对业务开发者来说，最重要的是这条边界：

- 你负责定义 agent 能做什么
- 框架负责把推理、工具调用、会话、流式输出和 API 协议跑起来

这也是为什么脚手架的核心入口是 `create_<agent>_agent()`。

## 常用环境变量

最常见的是以下几组：

### LLM 配置

```bash
LLM_PROVIDER=openai
MODEL_NAME=gpt-4o
API_KEY=sk-xxx
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_BASE_URL_IS_FULL_URL=false
# 完整请求 URL 示例:
# LLM_BASE_URL=https://service-host/chat/dialog
# LLM_BASE_URL_IS_FULL_URL=true
```

### API / Studio

```bash
API_HOST=0.0.0.0
API_PORT=8080
ENABLE_STUDIO=true
AGENTS_ROOT=./src/<package>/agents
```

### 可观测性

tracing 与 Phoenix / Langfuse provider 已并入 `server` extras，安装服务端即开箱可用：

```bash
uv pip install "ark-agentic[server]"
```

```bash
ENABLE_OBSERVABILITY=true
OBSERVABILITY_PROVIDER=Phoenix  # Phoenix 或 Langfuse
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317
PHOENIX_PROJECT_NAME=ark-agentic

# Langfuse 示例
# OBSERVABILITY_PROVIDER=Langfuse
# LANGFUSE_SECRET_KEY=sk-lf-xxx
# LANGFUSE_PUBLIC_KEY=pk-lf-xxx
# LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

这份 README 的目标不是枚举所有内部机制，而是让读者先找到正确入口、在正确层次上开始工作。
