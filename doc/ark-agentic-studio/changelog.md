# Ark-Agentic Studio — 变更日志 (Changelog)

> 按时间倒序记录所有已实施的变更。

---

## 2026-03-01 — Phase 2.5 代码评审整改

### 🔧 Architecture (P0)

- **[NEW api/deps.py]** 共享依赖注入模块
  - `init_registry()` 唯一入口，由 `app.py` 在 `lifespan` 中调用一次
  - `get_agent()` / `get_registry()` 供所有路由模块共享
  - 消除了 `chat.py`, `sessions.py`, `studio/agents.py`, `studio/sessions.py` 中 4× 重复的 `global _registry` + `init()` 模式

- **[MODIFY studio/api/agents.py]** `_agents_root()` 路径发现重构
  - 替换脆弱的 `Path(__file__).parents[N]` 硬编码
  - 新增 `AGENTS_ROOT` 环境变量支持 → `pyproject.toml` 探测 → 最终回退

- **[MODIFY studio/__init__.py]** 简化 `setup_studio()` 签名
  - `setup_studio(app, registry)` → `setup_studio(app)`
  - `FileResponse` 从函数内 3× 重复导入提升至文件顶部

- **[MODIFY app.py]** 单一入口依赖注入
  - `chat_api.init() + sessions_api.init()` → `api_deps.init_registry(_registry)`

### 🎨 Frontend (P1)

- **[MODIFY index.css]** 新增 7 个共享 CSS 类
  - `.master-detail-container`, `.list-header`, `.list-scroll`
  - `.detail-header-inner`, `.detail-icon`, `.section-heading`, `.placeholder-box`

- **[MODIFY SkillsView/ToolsView/SessionsView/MemoryView]** 内联样式迁移
  - 消除 20+ 处重复的 `style={{...}}` 内联定义
  - 统一使用 CSS 类实现布局和排版

### 🐛 Minor Fixes (P2)

- **[tools.py]** `ToolMeta.parameters: dict = {}` → `Field(default_factory=dict)`

---

## 2026-03-01 — UI 细节打磨与数据过滤

### 🐛 Bug Fixes

- **[tools.py]** 修复 AST 解析器未提取 `parameters` 字段的问题
  - 之前的解析器只读取 `name`, `description`, `group` 三个标量属性
  - 现在能递归解析 `ToolParameter(...)` 实例化调用的全部关键字参数
  - 支持提取 `enum` 等列表类型的值

- **[tools.py]** 增加 `AgentTool` 继承检查
  - 之前遍历文件中所有 `class`，导致辅助类（如 `DataServiceClient`）被错误展示
  - 现在严格检查 `ast.ClassDef.bases` 是否包含 `AgentTool`

- **[skills.py]** 修复 YAML Frontmatter 多行块标量解析
  - `description: |` 后跟缩进多行文本时，之前只能解析到 `|` 字面值
  - 现在正确收集后续缩进行，拼合为完整描述

- **[ToolsView.tsx / SessionsView.tsx]** 修复代码块对比度问题
  - 移除了内联 `style={{ background: 'var(--color-bg-subtle)', color: 'var(--color-text)' }}`
  - 恢复 `.code-block` 全局深色主题 (`#1E1E2E` 背景 + `#CDD6F4` 文字)

- **[index.css]** 修复 Flexbox 布局溢出
  - `.layout-pane-left` 因子级 `white-space: nowrap` 导致长文本撑破容器
  - 增加 `width: 280px; min-width: 0` 约束

### 🔧 Architecture

- **[studio/__init__.py]** SPA Catch-All 路由
  - 替换 `StaticFiles(html=True)` 为自定义 catch-all 路由
  - 支持 React Router 深层链接 (如 `/studio/agents/insurance/skills`)

- **[.env]** 修复环境变量拼写错误
  - `ENABLE_STUDI=true` → `ENABLE_STUDIO=true`

---

## 2026-02-28 — Phase 2 Core UI 页面实现

### ✨ Features

- **[SkillsView.tsx]** 技能管理页面
  - Master-Detail 布局：左侧技能列表 + 右侧 SKILL.md 全文预览
  - 支持联合渲染 YAML frontmatter 元数据

- **[ToolsView.tsx]** 工具管理页面
  - Master-Detail 布局：左侧工具列表 + 右侧 Metadata + Parameters Schema
  - JSON Schema 使用深色代码块展示

- **[SessionsView.tsx]** 会话追踪页面
  - Master-Detail 布局：左侧会话列表 + 右侧会话详情
  - 展示会话 ID、消息数量、创建时间、内部状态

- **[MemoryView.tsx]** 记忆管理页面
  - Master-Detail 布局占位 (Coming Soon)
  - 预留「短期上下文」和「长期画像」两个分区

### 🔧 Backend APIs

- **[studio/api/skills.py]** `GET /api/studio/agents/{id}/skills`
- **[studio/api/tools.py]** `GET /api/studio/agents/{id}/tools`
- **[studio/api/sessions.py]** `GET /api/studio/agents/{id}/sessions`
- **[studio/api/memory.py]** `GET /api/studio/agents/{id}/memory` (501)

---

## 2026-02-28 — Phase 1 Studio 骨架搭建

### ✨ Features

- **[studio/__init__.py]** Studio 模块入口
  - `setup_studio(app)` 函数，条件挂载 API 路由和前端静态资源

- **[studio/api/agents.py]** Agent Dashboard API
  - 文件系统扫描 `agents/` 目录，读取 `agent.json` 元数据

- **[studio/frontend/]** Vite + React + TypeScript 前端项目
  - 平安橙设计系统 (`index.css`)
  - Agent 卡片网格 Dashboard
  - React Router SPA 路由

- **[agent.json]** 为 insurance 和 securities 代理创建元数据文件

---

## 2026-02-28 — Phase 0 架构整理

### 🔧 Refactoring

- **[core/registry.py]** 从 `app.py` 提取 `AgentRegistry`
- **[api/models.py]** 提取 7 个 Pydantic 请求/响应模型
- **[api/chat.py]** 提取 `/chat` 路由为 APIRouter
- **[api/sessions.py]** 提取 `/sessions` 路由为 APIRouter
- **[app.py]** 瘦身：413 行 → ~110 行组装器

### ✅ Tests

- `test_registry.py`: 5 tests ✅
- `test_api_models.py`: 11 tests ✅
- `test_studio_agents.py`: 12 tests ✅
- `test_app_integration.py`: 4 tests ✅
- **Total: 32/32 ✅**
