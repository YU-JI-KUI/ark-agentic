# Agent 前端页面拆分设计（insurance / securities）

日期：2026-03-01
状态：已确认

## 1. 背景与问题
当前 [index.html](src/ark_agentic/static/index.html) 同时承载 insurance 与 securities 的 UI 与卡片渲染逻辑。随着两个 Agent 功能持续扩展，页面中存在以下风险：

- 业务卡片渲染分支相互干扰
- 页面状态与选择器逻辑耦合过高
- 新增功能时回归范围变大，维护成本上升

## 2. 目标
- 将 insurance 与 securities 的前端 demo 页面彻底拆分
- 用户从下拉选择 Agent 时进行整页跳转
- 使用独立路径：`/insurance`、`/securities`
- 保持后端 `/chat` 接口协议不变

## 3. 范围
### 包含
- 新增两个独立页面：`insurance.html`、`securities.html`
- 增加对应路由：`/insurance`、`/securities`
- 保留 Agent 下拉，但改为页面跳转行为
- 拆分卡片渲染逻辑：保险逻辑与证券逻辑各归各页

### 不包含
- 改造 `/chat` 接口协议
- 统一重构为复杂前端框架
- 大规模样式体系重做

## 4. 方案选择
已选方案 A：双页面 + 最小公共能力共享。

理由：
- 相比单页多分支，隔离最彻底，能直接解决互相干扰
- 相比完全不共享，维护成本更可控
- 复杂度明显低于“单壳加载模块”方案

## 5. 页面与路由设计
- `/insurance` -> `insurance.html`
- `/securities` -> `securities.html`
- `/` 暂时保留入口能力（可默认导向 `/insurance` 或作为简单选择页）

## 6. 职责拆分
### insurance 页面
- 固定 `agent_id = "insurance"`
- 只保留保险相关快捷入口、提示文案与卡片逻辑
- 不包含证券账户类型选择与证券模板卡渲染

### securities 页面
- 固定 `agent_id = "securities"`
- 保留账户类型选择器（普通户/两融）
- 只保留证券相关模板卡渲染（账户总览、持仓、现金资产、标的详情）

## 7. Agent 切换行为
两页均保留 Agent 下拉选择器：
- 选择 insurance -> `window.location.href = "/insurance"`
- 选择 securities -> `window.location.href = "/securities"`

不再在单页内通过条件分支切换业务逻辑。

## 8. 共享能力边界（最小共享）
可抽取稳定且与业务无关的公共函数（例如 `chat-common.js`）：
- 文本与展示工具函数：`md`、`escHtml`、`formatNumber`、`toNum`
- 通用消息 DOM 辅助：用户消息/错误消息
- 基础 SSE 读取循环骨架（不含业务卡片分支）

所有 agent-specific 的 UI 组件渲染仍放在对应页面内。

## 9. 兼容与状态
- `sessionStorage` 中的 `user_id`、`session_id`、`token_id` 继续沿用
- `agent` 的存储可保留，用于初始化下拉默认值
- API 继续请求 `/chat`，由页面固定 `agent_id`

## 10. 验收标准
- 在 `/insurance` 页面不会出现任何证券模板卡
- 在 `/securities` 页面不会出现保险专属快捷入口
- 切换下拉项后 URL 与页面内容一致
- 两页均可正常发起流式/非流式对话
- 原有会话与用户状态（sessionStorage）不被破坏

## 11. 风险与缓解
- 风险：复制页面带来重复代码
  - 缓解：只抽取最小公共能力，避免过度抽象
- 风险：路由配置遗漏导致 404
  - 缓解：新增路由后补充最小 smoke 验证
- 风险：拆分时误删事件处理
  - 缓解：按“发送消息、SSE 回包、卡片渲染、切页”四条主链路逐项测试
