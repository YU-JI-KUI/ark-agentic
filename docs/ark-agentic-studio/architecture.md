# Ark-Agentic Studio — 架构设计文档

> 本文档基于 **C4 Model** 和 **Mermaid 图表** 描述 `ark-agentic-studio` 的系统架构，涵盖上下文、容器化视图、组件依赖以及核心数据流向。
> 遵循 Pragmatic Design 哲学：清晰定义边界、显式注入依赖、分离关注点。

---

## 1. System Context Diagram (系统上下文视图)

描述 Ark-Agentic 框架是如何与开发者（用户）、目标应用（Agent 模型）进行相互作用的。

```mermaid
graph TD
    classDef person fill:#08427b,stroke:#052e56,color:#ffffff,stroke-width:2px;
    classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff,stroke-width:2px;
    classDef ext_sys fill:#999999,stroke:#6b6b6b,color:#ffffff,stroke-width:2px;
    classDef database fill:#1168bd,stroke:#0b4884,color:#ffffff,stroke-width:2px,shape:cylinder;

    User(("开发者 / 运营人员")):::person
    Studio["Ark-Agentic Studio\n[Software System]\n提供可视化管理、调试与资产治理"]:::system
    App["Ark-Agentic Engine API\n[Software System]\n智能体执行引擎"]:::system
    LLM["LLM Provider (如 OpenAI/通义千问)\n[External System]\n大语言模型服务"]:::ext_sys
    FileSys[("本地文件系统\n[Storage]\nagents.json, SKILL.md, Tools")]:::database

    User -->|查看/调试/管理 Agent| Studio
    Studio -->|读取配置 & 触发会话| App
    App -->|请求推理流| LLM
    App -->|持久化状态 / 读取配置| FileSys
    Studio -->|解析 AST & Markdown| FileSys
```

---

## 2. Container Diagram (容器视图)

展示前端应用、FastAPI 后端、核心业务逻辑以及存储层之间的关系。

```mermaid
graph TD
    classDef container fill:#438dd5,stroke:#2e6295,color:#ffffff,stroke-width:2px;
    classDef db fill:#438dd5,stroke:#2e6295,color:#ffffff,stroke-width:2px,shape:cylinder;

    User(("开发者"))
    
    subgraph FastAPI Application ["Ark-Agentic FastAPI 应用 (localhost:8080)"]
        SPA["Studio Frontend (React SPA)\n[Container: Vite/React/TS]\n提供 Master-Detail 界面，与后端交互"]:::container
        API["REST API Layer\n[Container: FastAPI APIRouter]\n处理前台请求 (Chat, Sessions, Studio API)"]:::container
        Core["Core Engine\n[Container: Python]\nAgentRunner, SessionManager, 核心逻辑实现"]:::container
    end
    
    AgentsDir[("Agents Metadata & Scripts\n[Container: File System]\nagent.json, SKILL.md, tools/*.py")]:::db

    User -->|浏览器访问 /studio| SPA
    SPA -->|JSON via HTTP| API
    API -->|基于 Registry 触发业务调用| Core
    API -->|直接扫描目录、解析 AST| AgentsDir
    Core -->|加载模型、注册工具| AgentsDir
```

---

## 3. Component Diagram: Backend Architecture (后端组件视图)

展示 FastAPI 应用内部的模块划分、SRP (单一职责) 边界以及依赖方向 (DIP 原则)。

```mermaid
graph TD
    classDef entrypoint fill:#f1c40f,stroke:#f39c12,color:#333333,stroke-width:2px;
    classDef module fill:#2ecc71,stroke:#27ae60,color:#ffffff,stroke-width:2px;
    classDef deps fill:#e74c3c,stroke:#c0392b,color:#ffffff,stroke-width:2px;
    classDef core module;

    App["app.py\n[Entrypoint]\n组装中间件、注册 Agent、按需挂载 Studio"]:::entrypoint
    
    subgraph API Layer
        Deps["api.deps\n[Dependency Injector]\n单例注册中心入口，提供 get_registry / get_agent 函数"]:::deps
        ChatAPI["api.chat\n[Router]\n处理端点：/chat，支持 SSE 流"]:::module
        SessionsAPI["api.sessions\n[Router]\n处理端点：/sessions (Core 端)"]:::module
    end
    
    subgraph Studio API Module
        StudioInit["studio.__init__\n[Router Mounter]\n统筹 Studio 的 API 与 SPA (React) 挂载"]:::module
        StudioAgents["studio.api.agents\n[Router]\n处理 Agent CRUD，环境变量 AGENTS_ROOT 兜底发现"]:::module
        StudioSkills["studio.api.skills\n[Router]\n解析 SKILL.md YAML 前言内容"]:::module
        StudioTools["studio.api.tools\n[Router]\n通过 Python AST 工具静态解析类属性与 Schema"]:::module
        StudioSessions["studio.api.sessions\n[Router]\n通过 Deps 查找到 Registry，列出会话信息"]:::module
    end

    subgraph Core Engine
        Registry["core.registry\n[Repository]\n代理实例管理器 (AgentRegistry)"]:::core
        Runner["core.runner\n[Domain Service]\n实现具体的智能体推理管线"]:::core
        SessionMgr["core.session\n[Domain Service]\n管理短期历史会话树/追踪"]:::core
    end

    App -.->|注入 init_registry| Deps
    Deps -->|封装| Registry

    ChatAPI -.->|Depends| Deps
    ChatAPI -->|调用 run| Runner

    SessionsAPI -.->|Depends| Deps
    SessionsAPI -->|调用| SessionMgr

    App -.->|if ENABLE_STUDIO=true| StudioInit
    StudioInit -.->|Include Routings| StudioAgents
    StudioInit -.->|Include Routings| StudioSkills
    StudioInit -.->|Include Routings| StudioTools
    StudioInit -.->|Include Routings| StudioSessions

    StudioSessions -.->|Depends| Deps
    StudioSessions -->|调用| SessionMgr

    Runner --> SessionMgr
```

### 【设计亮点】
- **依赖倒置 (DIP)**: `app.py` 作为顶层组装者，注入 `AgentRegistry` 到 `api.deps` 组件。各个业务路由 (如 `chat`, `sessions`, `studio.sessions`) 不再各自维护模块级全局状态，而是通过 `api.deps.get_agent` 取得运行时业务对象。
- **静态安全 (AST 解析)**: `studio.api.tools` 直接以 `ast` 抽象语法树解析 `tools/*.py` 代码提取 schema 格式，严格校验 `AgentTool` 继承类。无需将不可信工具代码导入 Python 内存中，提升了安全性和容错率。

---

## 4. Sequence Diagram: Data Flow Execution (会话数据流时序)

展示客户端是如何通过 API 触发一个 Agent 执行流并访问 Session 管理器的。

```mermaid
sequenceDiagram
    participant SPA as Studio SPA Frontend
    participant API as api.sessions (FastAPI)
    participant Deps as api.deps
    participant Reg as core.registry
    participant Runner as core.runner

    SPA->>API: GET /api/studio/agents/insurance/sessions
    activate API
    
    API->>Deps: get_registry()
    activate Deps
    Deps-->>API: AgentRegistry 单例
    deactivate Deps
    
    API->>Reg: get("insurance")
    activate Reg
    Reg-->>API: AgentRunner 实例
    deactivate Reg
    
    API->>Runner: 访问 runner.session_manager.list_sessions()
    activate Runner
    Runner-->>API: list[Session]
    deactivate Runner
    
    API-->>SPA: JSON: { sessions: [...] }
    deactivate API
```

---

## 5. Component Diagram: Frontend Architecture (前端组件视图)

展示 Studio React 前端项目的目录映射、样式封装与路由设计。

```mermaid
graph TD
    classDef router fill:#8e44ad,stroke:#732d91,color:#ffffff,stroke-width:2px;
    classDef view fill:#3498db,stroke:#2980b9,color:#ffffff,stroke-width:2px;
    classDef api fill:#e67e22,stroke:#d35400,color:#ffffff,stroke-width:2px;
    classDef styleDef fill:#1abc9c,stroke:#16a085,color:#ffffff,stroke-width:2px;

    AppTSX["App.tsx\n[Router Root]\n配置顶层路由与应用骨架"]:::router
    APIClient["api.ts\n[API Client]\n类型安全的 Fetch 封装\n(AgentMeta, SkillMeta, ToolMeta)"]:::api
    IndexCSS["index.css\n[Stylesheet]\n全局 CSS 变量 (平安橙风格) \n和高度复用的 Master-Detail 样式类\n(.master-detail-container, .list-scroll 等)"]:::styleDef

    Dashboard["Dashboard.tsx\n[View]\n路线：/ \n展示全量 Agent 网格卡片"]:::view
    AgentShell["AgentShell.tsx\n[Layout Router]\n路线：/agents/:agentId/*\n提供导航条与 Split-Pane 左右容器骨架"]:::view
    
    SkillsView["SkillsView.tsx\n[View]\n路线：/skills\n(应用 Master-Detail Shared Styles)"]:::view
    ToolsView["ToolsView.tsx\n[View]\n路线：/tools\n(应用 Master-Detail Shared Styles)"]:::view
    SessionsView["SessionsView.tsx\n[View]\n路线：/sessions\n(应用 Master-Detail Shared Styles)"]:::view
    MemoryView["MemoryView.tsx\n[View]\n路线：/memory\n(MVP 占位视图)"]:::view

    AppTSX --> Dashboard
    AppTSX --> AgentShell
    
    AgentShell --> SkillsView
    AgentShell --> ToolsView
    AgentShell --> SessionsView
    AgentShell --> MemoryView

    Dashboard -.-> APIClient
    AgentShell -.-> APIClient
    SkillsView -.-> APIClient
    ToolsView -.-> APIClient
    SessionsView -.-> APIClient

    AgentShell -.-> IndexCSS
    SkillsView -.-> IndexCSS
    ToolsView -.-> IndexCSS
    SessionsView -.-> IndexCSS
```

### 【设计亮点】
- **纯粹且解耦 (KISS + DRY)**: React 层面没有采用过重的 `Redux`/`Zustand` 集中管理。以 `AgentShell` 为 Router Controller 控制当前上下文，子页面根据 `agentId` 各自采用独立的 `useEffect` 数据请求并完成自身页面的渲染。
- **Master-Detail 视图一致性**: `SkillsView`、`ToolsView`、`SessionsView` 及 `MemoryView` 使用高度统一的 DOM 结构，通过 `index.css` 抽取的公共样式类（如 `.list-header`, `.detail-body`）避免了 `inline-style` 泛滥代码。
