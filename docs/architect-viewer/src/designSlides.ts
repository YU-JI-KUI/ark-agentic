export type DesignSlide = {
  id: string
  section: string
  title: string
  subtitle?: string
  summary?: string
  highlights?: string[]
  columns?: Array<{
    title: string
    items: string[]
  }>
  references?: string[]
}

export const designSlides: DesignSlide[] = [
  {
    id: 'cover',
    section: '开场',
    title: 'ark-agentic 架构技术分享',
    subtitle: '一个轻量级 ReAct Agent 框架，如何把上下文工程落到运行时系统中',
    summary:
      '它不是单纯的 LLM 调用封装，而是一套围绕 ReAct 模式构建的 Agent Runtime。工具、技能、会话、记忆、流式输出和卡片化 UI 都被纳入同一个运行时框架。',
    highlights: [
      '核心公式：Agent = LLM + Tools + Skills + Session/State + Memory + Streaming/UI',
      '设计重心不是多模型接入，而是多源上下文编排',
      '更接近“面向业务的 Agent Runtime”，而不是简单 prompt chain',
    ],
    references: ['README.md:3', '.claude-summary.md:11', 'src/ark_agentic/core/runner.py:115'],
  },
  {
    id: 'architecture',
    section: '总览',
    title: '五层架构：从接入到业务落地',
    summary: '框架把“运行时共性能力”和“业务差异能力”拆开，让核心机制稳定，业务层按 Agent 装配。',
    columns: [
      {
        title: '五层结构',
        items: [
          '接入层：FastAPI / CLI / Studio',
          'Agent 装配层：insurance、securities 等工厂',
          'Core Runtime：Runner、Prompt、Session、Skills、Tools、Memory、Stream',
          '领域适配层：参数映射、服务适配、字段抽取、模板渲染',
          '资源层：skills、templates、mock data、static assets',
        ],
      },
      {
        title: '架构价值',
        items: [
          'Core 负责共性运行机制',
          'Agent 负责业务装配与策略注入',
          'Tools / Skills 表达领域能力',
          '有利于复用、演进和多业务并行扩展',
        ],
      },
    ],
    references: [
      '.claude-summary.md:38',
      'src/ark_agentic/app.py:57',
      'src/ark_agentic/api/chat.py:27',
      'src/ark_agentic/agents/securities/agent.py:36',
    ],
  },
  {
    id: 'runner',
    section: '运行时',
    title: 'AgentRunner：整个系统的执行中枢',
    summary: 'AgentRunner 不是一次性模型调用器，而是完整的 ReAct 循环执行器。',
    columns: [
      {
        title: '主执行链路',
        items: [
          '读取 session 与历史消息',
          '合并 input_context、外部历史和 state',
          '必要时触发 compaction',
          '构建 system prompt 并调用 LLM',
          '解析 tool calls，执行工具，写回结果',
          '进入下一轮推理，直到产出最终回答',
        ],
      },
      {
        title: '关键方法',
        items: [
          'run()：统一入口',
          '_run_loop()：ReAct 主循环',
          '_build_system_prompt()：上下文到 prompt 的编排点',
          '_call_llm_streaming()：流式调用',
          '_execute_tools()：工具调度与状态回写',
          'validate_response_against_tools()：结果一致性校验',
        ],
      },
    ],
    references: [
      'src/ark_agentic/core/runner.py:177',
      'src/ark_agentic/core/runner.py:342',
      'src/ark_agentic/core/runner.py:620',
      'src/ark_agentic/core/runner.py:744',
      'src/ark_agentic/core/runner.py:886',
    ],
  },
  {
    id: 'context',
    section: '上下文工程',
    title: '上下文被拆成多个来源，并在运行时统一编排',
    summary: '这里的上下文不是 prompt 里的几段文字，而是可管理、可持久化、可压缩、可组合的一套运行时资源。',
    columns: [
      {
        title: '上下文来源',
        items: [
          '当前用户输入',
          'Session 内短期上下文',
          '外部历史消息',
          '技能上下文',
          '用户画像 / 长期记忆',
          '当前可用工具集合',
          '输出协议与 UI 上下文',
        ],
      },
      {
        title: '工程价值',
        items: [
          'Prompt 从“拼字符串”升级为系统组件',
          '上下文能被治理，而不是无限堆叠',
          '不同上下文源可以按角色参与决策',
          '为长会话、复杂业务、多端接入提供基础能力',
        ],
      },
    ],
    references: [
      'src/ark_agentic/core/runner.py:196',
      'src/ark_agentic/core/runner.py:229',
      'src/ark_agentic/core/runner.py:243',
      'src/ark_agentic/core/prompt/builder.py:69',
      'src/ark_agentic/core/prompt/builder.py:196',
    ],
  },
  {
    id: 'session-history',
    section: '会话治理',
    title: '短期上下文：Session + 外部历史合并策略',
    summary: 'SessionManager 管理短期连续性；history_merge 则解决跨渠道历史注入时的重复与顺序问题。',
    columns: [
      {
        title: 'SessionManager 能力',
        items: [
          '创建和加载 session',
          '维护消息历史',
          '持久化 session state',
          '支持 state_delta 回写',
          '在需要时触发会话压缩',
        ],
      },
      {
        title: '历史合并亮点',
        items: [
          'pair-based：以 (user, assistant) 对作为去重单位',
          'fuzzy dedup：模糊去重，不依赖严格全等',
          'anchor insertion：计算插入计划，而不是粗暴 append',
          '减少重复消息、错位消息对上下文的污染',
        ],
      },
    ],
    references: [
      'src/ark_agentic/core/session.py:24',
      'src/ark_agentic/core/types.py:321',
      'src/ark_agentic/core/history_merge.py:80',
      'src/ark_agentic/core/history_merge.py:155',
      'src/ark_agentic/core/history_merge.py:229',
    ],
  },
  {
    id: 'skills-tools',
    section: '能力组织',
    title: '技能系统 + 工具系统：把业务 SOP 与行动能力统一纳管',
    summary: '技能负责“知道该怎么做”，工具负责“真正去做”，两者共同塑造 Agent 的业务行为。',
    columns: [
      {
        title: '技能系统',
        items: [
          'SkillLoader：加载 Markdown 技能文档',
          'SkillMatcher：根据 query/context 判断是否注入',
          'ReadSkillTool：dynamic 模式下按需读取技能全文',
          '支持 full / dynamic / semantic 三种加载模式',
          '把 SOP、规范、注意事项抽离为独立资产',
        ],
      },
      {
        title: '工具系统',
        items: [
          'AgentTool：统一工具接口与 schema',
          'ToolRegistry：统一注册、查找、导出工具能力',
          'Runner 负责调度工具与回写结果',
          '工具结果可被后续工具和后续轮次继续使用',
          '支撑“查数据 -> 生成卡片”这类链式编排',
        ],
      },
    ],
    references: [
      'src/ark_agentic/core/skills/loader.py:25',
      'src/ark_agentic/core/skills/base.py:144',
      'src/ark_agentic/core/skills/semantic_matcher.py:18',
      'src/ark_agentic/core/tools/base.py:46',
      'src/ark_agentic/core/tools/registry.py:14',
      'src/ark_agentic/core/runner.py:948',
    ],
  },
  {
    id: 'memory',
    section: '记忆体系',
    title: '短期会话 + 长期记忆：两层上下文体系',
    summary: '这套设计避免把所有历史都塞给模型，而是用 Session 保连续性、用 Memory 保可召回性。',
    columns: [
      {
        title: '短期记忆',
        items: [
          '当前对话消息与状态',
          '服务于当前轮推理连续性',
          '与 tool result / state_delta 紧密协同',
        ],
      },
      {
        title: '长期记忆',
        items: [
          'MemoryManager 统一管理',
          '向量检索 + 关键词检索 + Hybrid RRF',
          '支持用户维度隔离',
          '支持文档增量同步与画像沉淀',
          '面向长期知识与用户偏好召回',
        ],
      },
    ],
    references: [
      'src/ark_agentic/core/memory/manager.py:54',
      'src/ark_agentic/core/memory/manager.py:146',
      'src/ark_agentic/core/memory/manager.py:281',
      '.claude-summary.md:16',
      '.claude-summary.md:17',
    ],
  },
  {
    id: 'compaction',
    section: '长会话治理',
    title: 'Compaction：在上下文窗口内维持稳定运行',
    summary: '长对话并不是简单截断，而是进行 token 估算、分块、摘要和紧凑化处理。',
    columns: [
      {
        title: '核心机制',
        items: [
          'token 估算与 oversized 判断',
          '按结构进行分块',
          'Simple / LLM Summarizer 抽象',
          '在压缩前尽量保留关键事实',
        ],
      },
      {
        title: '为什么重要',
        items: [
          '多轮业务流程天然会拉长会话',
          '上下文窗口有限，治理是必需项',
          '配合 Session 与 Memory 形成完整闭环',
          '是从 demo 走向真实业务的重要标志',
        ],
      },
    ],
    references: [
      'src/ark_agentic/core/compaction.py:33',
      'src/ark_agentic/core/compaction.py:103',
      'src/ark_agentic/core/compaction.py:163',
      'src/ark_agentic/core/compaction.py:256',
    ],
  },
  {
    id: 'streaming',
    section: '输出设计',
    title: '流式设计：不是简单 SSE，而是事件化协议层',
    summary: '框架把内部执行事件和对外输出协议做了解耦，便于接不同前端与企业集成格式。',
    columns: [
      {
        title: '核心组件',
        items: [
          'StreamEventBus：将 Runner 内部事件转成流式事件',
          'OutputFormatter：适配 agui / internal / enterprise / alone',
          'Chat API 层通过 SSE 持续向外输出',
        ],
      },
      {
        title: 'thinking / final 解析',
        items: [
          '支持 <think> / <final> 分流',
          '支持 chunk 跨边界断裂',
          '严格控制最终展示内容',
          '避免把内部思维链直接暴露给前端',
        ],
      },
    ],
    references: [
      'src/ark_agentic/core/stream/event_bus.py:63',
      'src/ark_agentic/core/stream/output_formatter.py:59',
      'src/ark_agentic/core/stream/output_formatter.py:155',
      'src/ark_agentic/core/stream/thinking_tag_parser.py:63',
      'src/ark_agentic/core/stream/thinking_tag_parser.py:182',
    ],
  },
  {
    id: 'cards',
    section: 'UI 协议',
    title: '卡片设计：A2UI 是协议化输出，而不是任意 JSON',
    summary: '这说明 UI 输出已经进入运行时协议层，Agent 不只是返回文本，而是在驱动结构化交互界面。',
    columns: [
      {
        title: 'A2UI 事件模型',
        items: [
          'beginRendering',
          'surfaceUpdate',
          'dataModelUpdate',
          'deleteSurface',
          '顶层字段采用白名单强校验',
        ],
      },
      {
        title: '协议价值',
        items: [
          '保证前后端集成稳定',
          'components 与 catalogId 二选一，体现两类渲染路径',
          '便于卡片模板与动态组件共存',
          '更适合富交互前端与企业场景集成',
        ],
      },
    ],
    references: [
      'src/ark_agentic/core/a2ui/contract_models.py:7',
      'src/ark_agentic/core/a2ui/contract_models.py:55',
      'src/ark_agentic/core/a2ui/contract_models.py:97',
      '.claude-summary.md:18',
    ],
  },
  {
    id: 'securities',
    section: '业务案例',
    title: '证券智能体：框架能力如何落到具体业务链路',
    summary: 'securities agent 展示了“领域输入清洗 + 工具调用 + 卡片渲染”是如何串成完整业务交互链路的。',
    columns: [
      {
        title: '装配与预处理',
        items: [
          'agent.py 装配 LLM、tools、session、skills、memory',
          'enrich_securities_context 负责上下文预处理',
          '把认证串和用户信息转成更稳定的结构化上下文',
        ],
      },
      {
        title: '工具与卡片',
        items: [
          '业务工具负责查询账户、持仓、标的详情',
          'display_card 从上下文取前序工具结果',
          'template_renderer 将数据转换为卡片展示',
          '体现了输出也是上下文工程的一部分',
        ],
      },
    ],
    references: [
      'src/ark_agentic/agents/securities/agent.py:36',
      'src/ark_agentic/agents/securities/agent.py:102',
      'src/ark_agentic/agents/securities/tools/service/param_mapping.py:210',
      'src/ark_agentic/agents/securities/tools/agent/display_card.py:44',
    ],
  },
  {
    id: 'closing',
    section: '总结',
    title: '为什么这个项目值得分享',
    summary: '它最有价值的地方，不是把 LLM 接进来，而是把工具、技能、记忆、流式输出和 UI 协议一起纳入统一的 Agent Runtime。',
    columns: [
      {
        title: '三点结论',
        items: [
          '把上下文工程系统化：从 prompt 技巧上升到运行时设计',
          '把业务 SOP 资产化：技能、模板、工具形成可维护资产层',
          '具备生产化雏形：多模型、持久化、流式协议、卡片输出、结果校验都已具备',
        ],
      },
      {
        title: '后续演进方向',
        items: [
          '存储层解耦：Session / Memory 可切 Redis / DB',
          'SubAgent 支持：强化复杂任务拆解与并行执行',
          'Auth Profile / Failover：更强的生产治理能力',
          '更完整的 Semantic Skill Matcher 落地',
        ],
      },
    ],
    references: [
      'src/ark_agentic/core/validation.py:110',
      '.claude-summary.md:305',
      '.claude-summary.md:306',
      '.claude-summary.md:307',
      '.claude-summary.md:308',
    ],
  },
]
