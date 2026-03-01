# Ark-Agentic Studio — TODO 跟踪

> 统一跟踪所有待办事项、已完成事项和远期规划。
> 最后更新: 2026-03-01

---

## ✅ 已完成 (Done)

### Phase 0: 架构整理
- [x] 提取 `AgentRegistry` → `core/registry.py`
- [x] 提取 Pydantic Models → `api/models.py`
- [x] 提取 `/chat` 路由 → `api/chat.py` (APIRouter)
- [x] 提取 `/sessions` 路由 → `api/sessions.py` (APIRouter)
- [x] 瘦身 `app.py` (413 → ~125 行)
- [x] 跑通 `pytest` 确保无回归 (32/32 passed)

### Phase 1: Studio 骨架 + Agent Dashboard
- [x] 创建 `studio/__init__.py` (`setup_studio(app)`)
- [x] 初始化 `studio/frontend/` (Vite + React + TS)
- [x] 实现 `studio/api/agents.py` (Agent CRUD + 文件扫描)
- [x] 为现有 Agent 创建 `agent.json`
- [x] `app.py` 条件挂载 Studio (`ENABLE_STUDIO`)
- [x] 实现 Agent Dashboard React 页面

### Phase 2: Core UI 页面
- [x] 实现 Agent Context Shell (Split-Pane Layout)
- [x] 实现 Skills Configuration View (Master-Detail)
- [x] 实现 Tools Management View (Master-Detail + Parameters Schema)
- [x] 实现 Sessions Tracking View (Master-Detail)
- [x] 实现 Memory View (Coming Soon 占位)
- [x] 实现 `studio/api/skills.py` (读取 SKILL.md, 含多行 YAML 解析)
- [x] 实现 `studio/api/tools.py` (AST 安全解析, AgentTool 继承过滤)
- [x] 实现 `studio/api/sessions.py` (复用 core session)
- [x] 实现 `studio/api/memory.py` (返回 501 占位)

### Phase 2 Bug Fixes
- [x] 修复 SPA 路由 (catch-all → index.html)
- [x] 修复 `.env` 拼写错误 (`ENABLE_STUDI` → `ENABLE_STUDIO`)
- [x] 修复 Flexbox 布局溢出 (长文本撑破 `.layout-pane-left`)
- [x] 修复代码块对比度 (移除内联样式污染)
- [x] 修复 Tool 列表误包含辅助类 (增加 AgentTool 继承检查)
- [x] 修复 Skill 描述 `|` 解析 (支持 YAML block scalar)

### Phase 2.5: 代码评审整改
- [x] **[P0]** 创建 `api/deps.py` — 消除 4× `global _registry` + `init()` 重复
- [x] **[P0]** 修复 `_agents_root()` — 使用 `AGENTS_ROOT` 环境变量 + `pyproject.toml` 发现
- [x] **[P1]** 消除 `_get_agent()` 重复 — 统一到 `deps.get_agent()`
- [x] **[P1]** 前端: 新增 7 个共享 CSS 类 (`.master-detail-container`, `.list-header` 等)
- [x] **[P1]** 前端: 4 个 View 组件内联 `style={{}}` 迁移至 CSS 类
- [x] **[P2]** `ToolMeta.parameters` 改为 `Field(default_factory=dict)`
- [x] **[P2]** `studio/__init__.py` 去重 3× `FileResponse` 导入
- [x] **[P2]** `setup_studio(app)` 简化签名 (不再需要 `registry` 参数)

---

## 📋 待办 (TODO)

### Phase 3: CRUD + 前后端联调

#### 后端 API
- [ ] `POST /api/studio/agents/{id}/skills` — 创建新 Skill (生成目录 + SKILL.md)
- [ ] `PUT /api/studio/agents/{id}/skills/{skill_id}` — 更新 SKILL.md 内容
- [ ] `DELETE /api/studio/agents/{id}/skills/{skill_id}` — 删除技能目录
- [ ] `POST /api/studio/agents/{id}/tools` — 生成 Python 工具代码模板

#### 前端页面
- [ ] SkillsView: 增加「新建技能」按钮和表单
- [ ] SkillsView: 增加「编辑」和「删除」操作按钮
- [ ] ToolsView: 增加「生成工具模板」按钮和参数配置表单
- [ ] 所有表单: 增加操作反馈 (Toast/成功提示)

#### CLI 部署支持
- [ ] `cli/templates.py` 增加 `STUDIO_INIT_TEMPLATE`
- [ ] `cli/main.py` `_cmd_init` 生成 `studio/` 目录和 `__init__.py`
- [ ] 将 `frontend/dist/` 预构建产物打包进 Python 包 (`package_data`)
- [ ] `.env-sample` 模板增加 `ENABLE_STUDIO=true` 和 `AGENTS_ROOT` 配置项

#### 联调验证
- [ ] E2E: 通过 UI 创建 Skill → 检查文件系统中 SKILL.md 已生成
- [ ] E2E: 通过 UI 删除 Skill → 检查文件系统中目录已移除
- [ ] E2E: 通过 UI 生成 Tool 模板 → 检查文件系统中 `.py` 已生成

---

## 🔮 远期规划 (Backlog)

### Phase 4: Meta-Agent (Chat to Create)
- [ ] 创建 `MetaBuilderAgent` + 内置工具
- [ ] 实现 `/api/studio/meta-chat` 流式端点
- [ ] 右侧对话面板对接 AG-UI 事件流
- [ ] 左侧工作区实时渲染 Meta-Agent 产出的表单

### 功能增强
- [ ] Skills: Markdown 实时预览 (Split Editor)
- [ ] Tools: 内联 Sandbox Mock 测试
- [ ] Sessions: 搜索过滤 + Trace 链路可视化
- [ ] Memory: 向量库可视面板 + PDF 入库

### 基础设施
- [ ] 前端: Loading Skeleton / 骨架屏
- [ ] 前端: Error Boundary 统一错误处理
- [ ] 前端: 响应式布局适配
- [ ] 后端: 变更历史 (History Diff)
- [ ] 测试: Studio API 集成测试
- [ ] CI/CD: 前端自动构建流水线
