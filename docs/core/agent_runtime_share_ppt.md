# ark-agentic 架构技术分享：PPT 核心内容

> 主题定位：一个轻量级 ReAct Agent 框架，如何把“上下文工程”做成可运行的 Agent Runtime
> 适用时长：约 10 分钟
> 使用方式：可直接按页拆分为 PPT，每页内容已按“标题 + 核心要点 + 可展示代码引用”组织

---

## 第 1 页：标题页

### 标题
ark-agentic 架构技术分享

### 副标题
一个轻量级 ReAct Agent 框架，如何把上下文工程落到运行时系统中

### 开场一句话
`ark-agentic` 不是一个单纯的 LLM 调用封装，而是一套围绕 ReAct 模式构建的 Agent Runtime。它把工具、技能、会话、记忆、流式输出和卡片化 UI 统一纳入了同一个运行时框架。

### 可引用位置
- `README.md:3`
- `.claude-summary.md:11`
- `src/ark_agentic/core/runner.py:115`

---

## 第 2 页：一句话理解项目

### 核心结论
可以用一个公式概括这个项目：

**Agent = LLM + Tools + Skills + Session/State + Memory + Streaming/UI**

### 核心说明
- LLM 负责推理与决策
- Tools 负责行动执行
- Skills 负责业务规则与操作流程注入
- Session/State 负责短期上下文
- Memory 负责长期记忆与用户画像
- Streaming/UI 负责把执行过程与结果稳定输出给前端

### 这一页要强调的点
这个项目的设计重心并不是“多模型接入”，而是“多源上下文编排”。

### 可引用位置
- `.claude-summary.md:11`
- `src/ark_agentic/core/runner.py:125`
- `src/ark_agentic/core/runner.py:146`
- `src/ark_agentic/core/runner.py:154`

---

## 第 3 页：整体架构总览

### 建议标题
五层架构：从接入到业务能力落地

### 架构分层
1. **接入层**：FastAPI / CLI / Studio
2. **Agent 装配层**：保险、证券等业务智能体工厂
3. **Core Runtime 层**：Runner、Prompt、Session、Skills、Tools、Memory、Stream
4. **领域适配层**：业务 API、参数映射、字段抽取、模板渲染
5. **资源层**：技能文档、模板、Mock 数据、静态资源

### 价值
这种分层让框架内核与业务智能体之间形成了较清晰的边界：
- Core 负责共性运行机制
- Agent 负责业务装配
- Tools/Skills 负责领域能力表达

### 可引用位置
- `.claude-summary.md:38`
- `src/ark_agentic/app.py:57`
- `src/ark_agentic/api/chat.py:27`
- `src/ark_agentic/agents/insurance/agent.py:36`
- `src/ark_agentic/agents/securities/agent.py:36`

---

## 第 4 页：主执行链路

### 建议标题
AgentRunner：整个系统的执行中枢

### 核心流程
1. 读取 session 与历史消息
2. 合并 `input_context` 与外部历史
3. 必要时触发上下文压缩
4. 构建 system prompt
5. 调用 LLM
6. 解析工具调用
7. 执行工具并写回结果
8. 驱动下一轮推理
9. 输出最终回答并进行校验

### 核心观点
`AgentRunner` 不是一次性的“模型调用器”，而是完整的 ReAct 循环执行器。

### 关键方法
- `run()`：入口
- `_run_loop()`：主循环
- `_build_system_prompt()`：提示词构建
- `_execute_tools()`：工具执行
- `_call_llm_streaming()`：流式输出

### 可引用位置
- `src/ark_agentic/core/runner.py:177`
- `src/ark_agentic/core/runner.py:342`
- `src/ark_agentic/core/runner.py:620`
- `src/ark_agentic/core/runner.py:744`
- `src/ark_agentic/core/runner.py:886`

---

## 第 5 页：为什么说它是“上下文工程系统”

### 核心结论
这个项目把上下文拆成多个来源，并在运行时统一编排。

### 上下文来源
- 当前用户输入
- Session 内短期上下文
- 外部历史消息
- 技能上下文
- 用户画像/长期记忆
- 当前可用工具集合
- 输出协议与 UI 上下文

### 核心价值
这意味着上下文不再只是 prompt 里的几段文字，而是可管理、可持久化、可压缩、可组合的一套运行时资源。

### 可引用位置
- `src/ark_agentic/core/runner.py:196`
- `src/ark_agentic/core/runner.py:229`
- `src/ark_agentic/core/runner.py:243`
- `src/ark_agentic/core/prompt/builder.py:69`
- `src/ark_agentic/core/prompt/builder.py:196`

---

## 第 6 页：短期上下文设计

### 建议标题
SessionManager：短期上下文与状态的基础设施

### 核心职责
- 创建和加载 session
- 维护消息历史
- 持久化 session state
- 支持状态回写
- 在需要时触发会话压缩

### 设计亮点
- Session 不只是“消息列表”，还包含可持续更新的 state
- 工具执行结果可通过 `state_delta` 写回 state，形成跨轮次可用的上下文

### 可引用位置
- `src/ark_agentic/core/session.py:24`
- `src/ark_agentic/core/types.py:321`
- `src/ark_agentic/core/types.py:356`
- `.claude-summary.md:261`

---

## 第 7 页：外部历史合并

### 建议标题
外部历史不是直接拼接，而是“成对去重 + 锚点插入”

### 核心设计
- 先把消息组织成 `(user, assistant)` 对
- 再做模糊去重，而不是简单字符串完全匹配
- 最后通过 anchor-based insertion 计算插入点

### 技术价值
- 降低外部历史与当前 session 冲突的概率
- 避免重复消息污染上下文
- 让跨端注入历史变得更稳定

### 适合分享时强调的点
这类设计说明项目已经在考虑真实业务接入时的上下文治理，而不是只做 demo 级对话链路。

### 可引用位置
- `src/ark_agentic/core/history_merge.py:49`
- `src/ark_agentic/core/history_merge.py:80`
- `src/ark_agentic/core/history_merge.py:155`
- `src/ark_agentic/core/history_merge.py:229`

---

## 第 8 页：Prompt 构建机制

### 建议标题
SystemPromptBuilder：多源上下文的统一拼装器

### 它负责拼什么
- 身份与角色描述
- 运行时说明
- 工具描述
- 技能描述
- 用户画像
- 当前上下文
- Memory 使用说明

### 设计意义
Prompt 在这里不是临时拼接字符串，而是一个明确的系统组件。框架把 prompt 构建从业务逻辑中抽离出来，使其具备可扩展性和一致性。

### 可引用位置
- `src/ark_agentic/core/prompt/builder.py:69`
- `src/ark_agentic/core/prompt/builder.py:95`
- `src/ark_agentic/core/prompt/builder.py:141`
- `src/ark_agentic/core/prompt/builder.py:196`
- `src/ark_agentic/core/prompt/builder.py:245`

---

## 第 9 页：技能系统

### 建议标题
技能系统：把业务 SOP 外置为可加载上下文

### 核心组件
- `SkillLoader`：加载技能文档
- `SkillMatcher`：根据 query/context 判断技能注入
- `ReadSkillTool`：在 dynamic 模式下按需加载完整技能

### 支持模式
- `full`：直接注入全文
- `dynamic`：先给技能元数据，再按需读取
- `semantic`：预留接口，当前更偏架构占位

### 核心价值
把业务流程、规范、注意事项从代码中抽离为 Markdown，使“业务知识”成为独立可维护资产。

### 可引用位置
- `src/ark_agentic/core/skills/loader.py:25`
- `src/ark_agentic/core/skills/matcher.py:43`
- `src/ark_agentic/core/tools/read_skill.py:16`
- `src/ark_agentic/core/skills/base.py:144`
- `src/ark_agentic/core/skills/semantic_matcher.py:18`

---

## 第 10 页：工具管理与集成

### 建议标题
工具系统：从“可调用函数”升级为运行时能力单元

### 核心结构
- `AgentTool`：统一工具接口与参数 schema
- `ToolRegistry`：统一注册、查找、导出 schema
- `Runner`：负责调度工具调用并回写结果

### 设计亮点
- 工具不只是执行动作，还能影响后续上下文
- 工具结果可作为后续工具的输入来源
- 工具 schema 统一后，模型调用行为更稳定

### 可引用位置
- `src/ark_agentic/core/tools/base.py:46`
- `src/ark_agentic/core/tools/registry.py:14`
- `src/ark_agentic/core/tools/registry.py:94`
- `src/ark_agentic/core/runner.py:893`
- `src/ark_agentic/core/runner.py:948`

---

## 第 11 页：记忆管理

### 建议标题
记忆管理：短期会话 + 长期记忆的双层体系

### 双层设计
- **短期记忆**：Session 中的历史消息与状态
- **长期记忆**：MemoryManager 管理的语义记忆与画像信息

### 长期记忆能力
- 向量检索
- 关键词检索
- 混合检索（RRF）
- 用户维度隔离
- 文档增量同步

### 设计价值
它避免把所有历史都塞进上下文窗口，而是通过“短期保连续性，长期保可召回性”的方式控制成本和稳定性。

### 可引用位置
- `src/ark_agentic/core/memory/manager.py:54`
- `src/ark_agentic/core/memory/manager.py:146`
- `src/ark_agentic/core/memory/manager.py:281`
- `.claude-summary.md:16`
- `.claude-summary.md:17`

---

## 第 12 页：上下文压缩

### 建议标题
长会话治理：在上下文窗口内维持稳定运行

### 核心机制
- token 估算
- oversized 判断
- 分块与摘要
- LLM Summarizer 压缩历史

### 作用
当会话过长时，系统不会简单截断，而是把历史整理为更紧凑的摘要，保留关键事实后继续运行。

### 价值
这是 Agent 走向真实业务场景的必要能力，因为长对话、多轮追问、复杂业务流程都需要上下文窗治理。

### 可引用位置
- `src/ark_agentic/core/compaction.py:33`
- `src/ark_agentic/core/compaction.py:103`
- `src/ark_agentic/core/compaction.py:163`
- `src/ark_agentic/core/compaction.py:256`

---

## 第 13 页：流式设计

### 建议标题
流式设计：不是简单 SSE，而是事件化输出协议

### 核心组件
- `StreamEventBus`：把运行时内部事件转成流式事件
- `OutputFormatter`：把事件适配到不同协议

### 支持协议
- `agui`
- `internal`
- `enterprise`
- `alone`

### 设计意义
这说明框架内部输出事件与对外协议已经解耦，便于适配多种前端或企业集成标准。

### 可引用位置
- `src/ark_agentic/core/stream/event_bus.py:63`
- `src/ark_agentic/core/stream/output_formatter.py:59`
- `src/ark_agentic/core/stream/output_formatter.py:93`
- `src/ark_agentic/core/stream/output_formatter.py:155`
- `.claude-summary.md:17`

---

## 第 14 页：thinking/final 流式解析

### 建议标题
思考流与最终答案分离：流式解析器的工程细节

### 核心能力
- 解析 `<think>` / `<final>` 标签
- 支持 chunk 跨边界断裂
- 维护 streaming 状态
- 严格控制最终展示内容

### 价值
- 可以在运行时保留模型思考过程处理能力
- 同时避免把内部思维链直接暴露给前端
- 让流式 UI 和最终落盘消息保持一致

### 可引用位置
- `src/ark_agentic/core/stream/thinking_tag_parser.py:63`
- `src/ark_agentic/core/stream/thinking_tag_parser.py:104`
- `src/ark_agentic/core/stream/thinking_tag_parser.py:138`
- `src/ark_agentic/core/stream/thinking_tag_parser.py:182`

---

## 第 15 页：卡片设计与 A2UI

### 建议标题
卡片设计：A2UI 是协议化输出，而不是任意 JSON

### 顶层事件
- `beginRendering`
- `surfaceUpdate`
- `dataModelUpdate`
- `deleteSurface`

### 关键设计
- 顶层事件有严格字段白名单
- `beginRendering` 强制要求 `surfaceId` 与 `rootComponentId`
- `components` 与 `catalogId` 二选一

### 核心意义
这说明卡片输出已经被纳入框架协议层，而不是业务代码自由拼装。它更适合做富交互前端集成。

### 可引用位置
- `src/ark_agentic/core/a2ui/contract_models.py:7`
- `src/ark_agentic/core/a2ui/contract_models.py:55`
- `src/ark_agentic/core/a2ui/contract_models.py:97`
- `.claude-summary.md:18`

---

## 第 16 页：业务案例——证券智能体

### 建议标题
业务侧如何落地：以 securities agent 为例

### 可以讲的链路
- `agent.py` 负责装配 LLM、tools、session、skills、memory
- `param_mapping.py` 负责上下文预处理
- `display_card.py` 负责把工具结果转成卡片输出
- `template_renderer.py` 负责模板渲染

### 适合强调的点
证券智能体展示了框架如何把“领域输入清洗 + 工具调用 + 卡片输出”串成完整链路。

### 可引用位置
- `src/ark_agentic/agents/securities/agent.py:36`
- `src/ark_agentic/agents/securities/agent.py:102`
- `src/ark_agentic/agents/securities/tools/service/param_mapping.py:210`
- `src/ark_agentic/agents/securities/tools/agent/display_card.py:44`

---

## 第 17 页：为什么这个项目值得分享

### 三个核心价值
1. **把上下文工程系统化**：从 prompt 技巧上升到运行时设计
2. **把业务 SOP 资产化**：技能、模板、工具形成独立资产层
3. **具备生产化雏形**：多模型、持久化、流式协议、卡片渲染、输出校验都已具备

### 一句话总结
`ark-agentic` 的真正价值，不是“让模型回答问题”，而是“让 Agent 在真实业务系统中更稳定地运行”。

### 可引用位置
- `src/ark_agentic/core/validation.py:110`
- `src/ark_agentic/core/runner.py:495`
- `src/ark_agentic/core/stream/event_bus.py:4`
- `src/ark_agentic/core/memory/manager.py:54`

---

## 第 18 页：可延展讨论

### 可顺带提到的演进方向
- 存储层解耦：Session / Memory 后续可切 Redis / DB
- SubAgent 支持：当前是待办项，说明架构预留了扩展方向
- Auth Profile / Failover：多模型路由与降级能力
- 更完整的 Semantic Skill Matcher 落地

### 可引用位置
- `.claude-summary.md:305`
- `.claude-summary.md:306`
- `.claude-summary.md:307`
- `.claude-summary.md:308`

---

## 最后一页：结束语

### 收束用语
如果要用一句话评价这个项目，我会说：

**它最有价值的地方，不是把 LLM 接进来，而是把工具、技能、记忆、流式输出和 UI 协议一起纳入了统一的 Agent Runtime。**

### 适合现场结束时再强调一次
- 这是一个 ReAct Agent 框架
- 但更重要的是，它是一个上下文工程框架
- 再往前走一步，它已经接近一个可产品化的 Agent 操作系统雏形
