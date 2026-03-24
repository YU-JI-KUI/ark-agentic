export type DesignSlide = {
  id: string
  section: string
  title: string
  subtitle?: string
  summary?: string
  layout?: 'split' | 'stack'
  highlights?: string[]
  columns?: Array<{
    title: string
    items: string[]
  }>
  icons?: string[]
}

export const designSlides: DesignSlide[] = [
  {
    id: 'cover',
    section: '开场',
    title: 'Ark-Agentic：面向生产的轻量级 Agent 运行时框架',
    subtitle: '从“Prompt 调试”转向“上下文工程运行时”',
    summary:
      'ark-agentic 不是一个单纯的 LLM 调用封装，而是一套围绕 ReAct 模式构建的 Agent Runtime。它把工具、技能、会话、记忆、流式输出和卡片化 UI 统一纳入了同一个运行时框架。',
    layout: 'stack',
    highlights: [
      '项目重点不是“把模型接进来”，而是“让 Agent 在真实业务系统里稳定运行”。',
      '关注的是完整运行链路，而不是单次模型请求。',
      '这是一个面向生产落地的 Agent Runtime，而不是简单 prompt chain。',
    ],
    icons: ['Agent Runtime / Workflow', 'ReAct Loop', 'LLM Orchestration', 'Tools Integration', 'Streaming UI'],
  },
  {
    id: 'pain-points',
    section: '背景',
    title: 'Demo 很简单，但生产化很难',
    summary: '真正难的不是“让模型回答”，而是“让 Agent 作为系统稳定运行”。',
    layout: 'split',
    columns: [
      {
        title: '典型痛点',
        items: [
          '逻辑碎片化：业务 SOP 硬编码在 Prompt 中，难以维护、难以协作。',
          '上下文失控：长对话容易堆积脏历史，缺乏状态管理、压缩和去重机制。',
          'UI 交付难：流式输出、卡片、表单等复杂前端交互缺乏统一协议。',
          '架构过重：部分主流框架适合复杂编排，但对业务落地团队不够轻便。',
        ],
      },
      {
        title: 'Ark-Agentic 的应对思路',
        items: [
          '用 Skills 解决 SOP 资产化。',
          '用 Session / History Merge / Compaction 治理上下文。',
          '用 AGUI / A2UI 解决输出协议和富交互问题。',
          '用轻量 ReAct Runtime 保持整体工程复杂度可控。',
        ],
      },
    ],
    icons: ['SOP / Playbook', 'Context Management', 'Compression', 'AGUI Protocol', 'Interactive Cards'],
  },
  {
    id: 'comparison',
    section: '选型视角',
    title: '与主流框架的差异化分析',
    summary: 'Ark-Agentic 更像面向业务落地的轻量 Agent Runtime，而不是纯编排框架。',
    layout: 'split',
    columns: [
      {
        title: 'LangGraph · Graph',
        items: ['图结构 / 状态机强。', '适合复杂分支决策。', '编排能力强，心智负担也更高。', '更偏复杂工作流控制。'],
      },
      {
        title: 'OpenClaw · Assistant',
        items: ['偏个人助手与系统集成。', '强调外部连接与操作。', '适合 assistant infrastructure。', '上下文治理和 UI 协议不是主卖点。'],
      },
      {
        title: 'Ark-Agentic · Runtime',
        items: ['轻量 ReAct Runtime。', '继承 OpenClaw 的 Skill 机制。', '强调上下文工程与记忆治理。', '内置 AG-UI / A2UI。', '更适合 SOP 密集型业务落地。'],
      },
    ],
    icons: ['Graph', 'State Machine', 'Assistant', 'System Integration', 'ReAct Runtime', 'Context Engineering', 'Enterprise UI'],
  },
  {
    id: 'formula',
    section: '总览',
    title: 'Agent = LLM + Tools + Skills + Session/State + Memory + Streaming/UI',
    summary: '这个项目的设计重心不是多模型接入，而是多源上下文编排。',
    layout: 'stack',
    columns: [
      {
        title: '公式拆解',
        items: [
          'LLM：负责推理与决策。',
          'Tools：负责行动执行。',
          'Skills：负责业务规则、流程、SOP 注入。',
          'Session / State：负责短期上下文与跨轮状态。',
          'Memory：负责长期知识、画像与召回。',
          'Streaming / UI：负责把过程和结果稳定交付给前端。',
        ],
      },
      {
        title: '工程哲学',
        items: ['坚持轻量、实用、工程化。', '避免把所有逻辑塞进单一 prompt。', '避免把 Agent 系统退化成一堆胶水代码。'],
      },
    ],
    icons: ['LLM', 'Tools', 'Skills', 'Session State', 'Memory', 'Streaming UI'],
  },
  {
    id: 'five-layers',
    section: '架构',
    title: '五层架构：从接入到业务能力落地',
    summary: '这套分层把“运行时共性能力”和“业务差异能力”拆开了。',
    layout: 'split',
    columns: [
      {
        title: '五层结构',
        items: [
          '接入层：FastAPI / CLI / Studio。',
          'Agent 装配层：insurance、securities 等业务智能体工厂。',
          'Core Runtime 层：Runner、Prompt、Session、Skills、Tools、Memory、Stream。',
          '领域适配层：参数映射、服务适配、字段抽取、模板渲染。',
          '资源层：skills、templates、mock data、static assets。',
        ],
      },
      {
        title: '分层价值',
        items: ['Core 负责共性机制。', 'Agent 负责业务装配。', 'Tools / Skills 表达领域能力。', '资源层承载可维护的业务资产。'],
      },
    ],
    icons: ['FastAPI', 'CLI', 'Runtime Core', 'Adapter', 'Template', 'Assets'],
  },
  {
    id: 'context-engineering',
    section: '上下文工程',
    title: '上下文工程：把业务 SOP、Prompt 与运行时资源统一编排',
    summary: '上下文不是 prompt 里的几段文字，而是被运行时管理、可按需注入的业务资源集合。',
    layout: 'split',
    columns: [
      {
        title: '上下文来源与系统观',
        items: [
          '当前用户输入、Session 内短期上下文、外部历史消息共同组成即时语境。',
          '技能上下文把业务 SOP、规范、注意事项外置为可维护资产。',
          '用户画像 / 长期记忆为跨轮、跨会话召回提供补充。',
          '当前可用工具集合与输出协议 / UI 上下文也参与模型决策边界。',
          'Prompt 从“拼字符串”升级为运行时统一编排的系统组件。',
        ],
      },
      {
        title: '为什么 Skills 是上下文工程的一部分',
        items: [
          '把业务流程、规范、注意事项从代码中拆出来，避免 SOP 硬编码在 prompt。',
          'SkillLoader 加载 Markdown 技能文档，SkillMatcher 根据 query/context 决定注入。',
          'ReadSkillTool 支持 dynamic 模式下按需读取全文。',
          '支持 full / dynamic / semantic 三种模式，让运行时决定“当前该注入什么知识”。',
          'PromptBuilder 最终把角色、工具、技能、记忆与当前上下文统一拼装。',
        ],
      },
    ],
    icons: ['Context', 'Prompt Builder', 'Session', 'Skills', 'Memory', 'Tools', 'Markdown', 'Dynamic Loading'],
  },
  {
    id: 'memory-design',
    section: '记忆设计',
    title: '记忆设计：短期会话治理 + 长期记忆中枢',
    summary: '项目的记忆设计不是“外挂一个向量库”，而是“短期状态治理 + 长期知识沉淀 + 混合检索召回”的一体化设计。',
    layout: 'stack',
    columns: [
      {
        title: '短期记忆：Session 与历史治理',
        items: [
          'SessionManager 管理消息历史、session state、state_delta 回写与必要时的会话压缩。',
          'Session 不只是聊天记录，还承载可持续演进的结构化状态。',
          '外部历史注入采用 pair-based 组织、fuzzy dedup 与 anchor insertion，减少重复和错位污染。',
          '短期会话层负责保证当前轮次连续性与运行稳定性。',
        ],
      },
      {
        title: '长期记忆：统一门面 + 混合检索',
        items: [
          'MemoryManager 作为统一门面，对外提供受控的长期记忆能力。',
          '统一存储思路可承载向量索引、关键词索引、embedding cache 与文件追踪。',
          '检索采用向量检索 + 关键词检索融合，兼顾语义召回与精确匹配。',
          '支持用户维度隔离、增量同步、仅重建变化内容与安全 reindex。',
        ],
      },
      {
        title: '关键技术补充（参考 memory_design_ppt）',
        items: [
          '结构感知分块：优先按 Markdown 标题边界切块，保留知识层级。',
          '双引擎混合打分：向量召回 + FTS/BM25 关键词检索，归一化后融合。',
          'Embedding Cache：按 content hash 缓存向量，内容未变化时跳过重新向量化。',
          '记忆生命周期闭环：对话产生 → LLM 提取 → profile / agent memory 分流写入 → sync 重建索引。',
          '用户边界通过 user_id 隔离与目录分区实现，天然支持多用户。',
        ],
      },
    ],
    icons: ['Session', 'State', 'History Merge', 'Memory Manager', 'Vector Search', 'FTS / BM25', 'Embedding Cache', 'User Profile'],
  },
  {
    id: 'runner',
    section: '运行时',
    title: 'AgentRunner：整个系统的执行中枢',
    summary: 'AgentRunner 不是一次性模型调用器，而是完整的 ReAct 循环执行器。',
    layout: 'split',
    columns: [
      {
        title: '主执行链路',
        items: [
          '读取 session 与历史消息。',
          '合并 input_context、外部历史和 state。',
          '必要时触发上下文压缩。',
          '构建 system prompt。',
          '调用 LLM。',
          '解析 tool calls。',
          '执行工具并写回结果。',
          '驱动下一轮推理。',
          '生成最终回答并进行结果校验。',
        ],
      },
      {
        title: '关键方法',
        items: ['run()：统一入口。', '_run_loop()：ReAct 主循环。', '_build_system_prompt()：上下文编排点。', '_call_llm_streaming()：流式调用。', '_execute_tools()：工具调度与结果回写。'],
      },
    ],
    icons: ['Runner', 'Loop', 'Tool Call', 'State Update', 'Validation'],
  },
  {
    id: 'prompt-builder',
    section: 'Prompt 体系',
    title: 'Prompt 构建机制：多源上下文的统一拼装器',
    summary: 'PromptBuilder 不是小工具，而是运行时中的上下文编排器。',
    layout: 'stack',
    columns: [
      {
        title: '它负责拼什么',
        items: ['身份与角色描述。', '运行时说明。', '工具描述。', '技能描述。', '用户画像。', '当前上下文。', 'Memory 使用说明。'],
      },
      {
        title: '设计意义',
        items: [
          'Prompt 在这里不是临时拼接的一段字符串，而是明确的系统组件。',
          '它把多源上下文以统一规则组织起来。',
          '保证运行时行为的一致性和可扩展性。',
          '也是治理 prompt 膨胀和职责混乱的关键位置。',
        ],
      },
    ],
    icons: ['Prompt Builder', 'Context Assembly', 'Role Prompt', 'Tool Schema', 'Memory Hint'],
  },
  {
    id: 'compaction',
    section: '长会话治理',
    title: '在上下文窗口内维持稳定运行',
    summary: '长会话不是简单截断，而是压缩、摘要和结构化保留。',
    layout: 'split',
    columns: [
      {
        title: '为什么重要',
        items: [
          '多轮业务对话天然会拉长上下文。',
          '复杂流程会积累大量无效或次要历史。',
          '如果没有治理，模型效果和成本都会快速失控。',
          '目标是在窗口有限前提下尽量保留关键事实并维持连续性。',
        ],
      },
      {
        title: '核心机制',
        items: ['token 估算。', 'oversized 判断。', '分块与摘要。', 'Simple / LLM Summarizer 抽象。'],
      },
    ],
    icons: ['Token', 'Compression', 'Summarization', 'Chunking', 'Window Control'],
  },
  {
    id: 'cards',
    section: '协议与卡片设计',
    title: 'AG-UI + A2UI：传输协议与渲染载荷的一体化设计',
    summary: 'AG-UI 负责稳定传输，A2UI 负责结构化渲染；其中 A2UI 的 block 设计是核心亮点。',
    layout: 'split',
    columns: [
      {
        title: 'AG-UI：与框架无缝集成的事件传输层',
        items: [
          'AG-UI 本质上是 Agent → 前端的实时通信总线，基于 SSE 承载文本、工具调用、状态同步与 UI 事件。',
          '它把 Runner、工具系统和最终回答统一映射为事件流，让过程输出和结果输出走同一条协议链路。',
          'OutputFormatter 负责适配 agui / enterprise / internal / alone，不把前端协议差异侵入核心运行时。',
          '因此它既能无缝接入当前框架，也能随着集团侧协议框架升级而平滑调整。',
        ],
      },
      {
        title: 'A2UI：亮点在 block 化的声明式 UI 设计',
        items: [
          'A2UI 不是任意 JSON，而是后端驱动的声明式 UI 协议：后端决定“渲染什么”，前端决定“如何渲染”。',
          'block 设计把常见业务展示模式沉淀为可复用资产，让卡片构建从一次性拼装升级为稳定能力。',
          '它同时兼顾固定模板的稳定性与动态编排的灵活性，更适合金融、保险这类结构化表达很强的场景。',
          '样式与结构边界被约束后，前后端协作成本更低，生成结果也更稳定、更容易持续演进。',
        ],
      },
    ],
    icons: ['AG-UI', 'SSE', 'Event Bus', 'A2UI', 'Block Design', 'Declarative UI', 'Surface Update', 'Design Token'],
  },
  {
    id: 'practice',
    section: '实践落地',
    title: '从框架基座到业务敏捷交付',
    summary: '通过“核心框架 + 业务脚手架”的模式，实现“基座统一，业务百花齐放”。',
    layout: 'stack',
    columns: [
      {
        title: '实践落地逻辑',
        items: [
          '核心框架沉淀 ReAct 运行时、上下文治理、协议解析等底层能力。',
          '业务智能体只需关注工具、技能、模板和业务上下文装配。',
          '框架统一封装流式协议和 UI 组件输出。',
          '模型、存储、记忆、检索都可按抽象接口替换。',
          '支持从轻量部署逐步演进到更重型能力。',
        ],
      },
      {
        title: '业务案例',
        items: ['证券 Agent：实现领域输入清洗、自动化工具调用与结果卡片渲染。', '保险 Agent：解决取款、报案等复杂 SOP 的技能注入与输出验证。'],
      },
    ],
    icons: ['Scaffold', 'Configurable', 'Plug-in', 'Securities', 'Insurance'],
  },
  {
    id: 'closing',
    section: '总结',
    title: 'Ark-Agentic 正在形成可产品化的 Agent 基座',
    summary: '它最有价值的地方，不是把 LLM 接进来，而是把工具、技能、记忆、流式输出和 UI 协议一起纳入了统一的 Agent Runtime。',
    layout: 'stack',
    columns: [
      {
        title: '最终结论',
        items: ['这是一个 ReAct Agent 框架。', '但更重要的是，它是一个上下文工程框架。', '再往前一步，它已经接近一个可产品化的 Agent 基座。'],
      },
    ],
    icons: ['ReAct', 'Context Engineering', 'Runtime', 'UI Protocol', 'Productization'],
  },
]
