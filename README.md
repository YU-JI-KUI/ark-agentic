# ark-agentic

`ark-agentic` 是一个面向业务落地的 Agentic 基础框架，同时提供 `ark-agentic` CLI 用来生成业务项目脚手架。

这份 README 不再把“框架开发”和“业务开发”混在一起，而是分成两条明确路径：

- 业务应用开发者：用 CLI 生成项目，专注写 agent、tools、skills、prompt 和业务逻辑。
- 框架开发者：维护 `ark-agentic` 本身，包括核心运行时、CLI、API、Studio 和发布流程。

如果你是新人，先判断自己属于哪一类，然后直接看对应章节。

## 你应该看哪一部分

### 业务应用开发者

你关心的是：

- 怎么创建一个新的业务 Agent 项目
- 生成后的目录分别该改哪里
- 怎么本地跑起来 CLI / API / Studio
- 怎么在现有业务项目里继续加 agent

直接看下方的“路径一：业务应用开发者”。

### 框架开发者

你关心的是：

- 如何在这个仓库里开发 `ark-agentic`
- 哪些目录属于框架代码，哪些只是示例或内部应用
- 如何运行测试、构建 Studio、发布包

直接看下方的“路径二：框架开发者”。

## 路径一：业务应用开发者

### 1. 你会得到什么

`ark-agentic` CLI 会生成一个开箱可改的业务项目骨架，默认包含：

- 一个可运行的 `default` agent
- 一个终端交互入口
- 可选的 FastAPI 服务入口
- Studio 接入位
- 业务工具、技能目录和基础测试目录

业务团队的职责应该集中在这些事情上：

- 定义业务工具
- 编排 agent prompt 和能力边界
- 接入业务系统
- 按需扩展 API、UI 和多 agent 协作

而不是从零搭框架运行时。

### 2. 先安装 CLI

当前提是你已经能从团队内部源或发布源安装 `ark-agentic` 包，常见方式如下：

```bash
uv tool install ark-agentic
# 或
pip install ark-agentic
```

### 3. 创建脚手架项目

如果你已经安装并发布了 `ark-agentic` 包，直接使用命令：

```bash
ark-agentic init my-agent --api --llm-provider openai
```

如果你当前就在这个框架仓库里验证 CLI，可以直接运行：

```bash
uv run ark-agentic init my-agent --api --llm-provider openai
```

常用参数：

- `--api`：生成 FastAPI 服务入口，并预留 Studio 接入
- `--llm-provider {openai,pa-sx,pa-jt}`：生成对应的 `.env-sample`
- `--memory`：当前仅保留记忆能力扩展入口；如果只是快速起项目，建议先不使用

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
```

### 5. 脚手架目录怎么理解

执行 `ark-agentic init my-agent --api` 后，核心目录大致如下：

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
  HTTP 服务入口。加了 `--api` 才会生成。
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

- `tool_registry.register(...)`：注册业务工具
- `agent_name` / `agent_description`：描述 agent 的职责
- `max_turns`：根据场景调整推理轮次
- `SessionManager(...)`：按需调整会话持久化策略

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
4. 确认业务逻辑后，再打开 `--api` 生成的 HTTP 服务
5. 最后再考虑 Studio、记忆、可观测性和多 agent

这样能避免一开始就把精力浪费在框架细节上。

## 路径二：框架开发者

### 1. 这个仓库的职责

这个仓库维护的是 `ark-agentic` 底座本身，包括：

- Agent 运行时
- Tool / Skill / Session / Memory 等基础能力
- CLI 脚手架生成器
- FastAPI API 层
- Studio 接入
- 发布打包流程

业务团队最终应该更多地依赖这个仓库发布出的包和 CLI，而不是直接在本仓库里改业务逻辑。

### 2. 框架代码主要在哪些目录

```text
src/ark_agentic/
├── cli/             # 脚手架 CLI
├── core/            # 运行时核心：runner、tools、skills、stream、session、memory...
├── api/             # FastAPI 路由与协议层
├── observability/   # Phoenix 等观测集成
├── studio/          # Studio 后端集成与前端资源
├── services/        # Job / Notification 等服务能力
├── agents/          # 仓库内置示例/内部 agent
├── static/          # 示例页面静态资源
└── app.py           # 仓库内统一演示服务入口
```

建议这样理解：

- `core/`、`cli/`、`api/`、`studio/` 是框架主干
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
- 改 HTTP 协议：`src/ark_agentic/api/`
- 改 Studio：`src/ark_agentic/studio/`

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

## CLI 参考

### `ark-agentic init`

```bash
ark-agentic init <project_name> [--api] [--memory] [--llm-provider openai|pa-sx|pa-jt]
```

用途：

- 初始化一个新的业务 Agent 项目

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
LLM
 + ToolRegistry
 + SessionManager
 + RunnerConfig
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
```

### API / Studio

```bash
API_HOST=0.0.0.0
API_PORT=8080
ENABLE_STUDIO=true
AGENTS_ROOT=./src/<package>/agents
```

### 可观测性

```bash
ENABLE_PHOENIX=true
PHOENIX_COLLECTOR_ENDPOINT=http://localhost:4317
PHOENIX_PROJECT_NAME=ark-agentic
```

## 新人建议阅读顺序

如果你是业务应用开发者：

1. 先执行 `ark-agentic init`
2. 只看生成项目里的 `agent.py`、`tools/`、`.env-sample`
3. 跑通终端模式后，再接 API

如果你是框架开发者：

1. 先看 `src/ark_agentic/cli/` 和 `src/ark_agentic/core/`
2. 再看 `src/ark_agentic/api/` 和 `src/ark_agentic/studio/`
3. 最后再去看仓库里的示例 agent

这份 README 的目标不是枚举所有内部机制，而是让新人先找到正确入口、在正确层次上开始工作。
