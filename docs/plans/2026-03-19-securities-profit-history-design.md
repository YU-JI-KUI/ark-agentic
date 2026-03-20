# 证券历史盈亏查询能力增强方案

**日期**: 2026-03-19  
**状态**: 设计已确认（待实施）

## 1. 目标

在现有证券智能体中支持历史盈亏查询能力，覆盖账户层趋势、历史股票盈亏排行、逐日收益明细，默认卡片优先展示，并保持现有 skill 边界稳定。

---

## 2. 范围与非范围

### 范围
- 扩展 `profit_inquiry` skill：支持本周/本月/今年/近一年/开户以来/自定义区间历史盈亏查询
- 新增三个历史收益相关工具能力：
  - 工具1：账户层历史收益曲线（`asset_profit_curve`，对接 `getUerAssetPftCurve`）
  - 工具2：指定历史区间内持仓**股票**盈亏排行
  - 工具3：指定历史区间内逐日收益明细（每日一条）
- 接入 service adapter、参数映射、mock、字段抽取、display_card
- 增加相关测试（参数映射、字段抽取、技能集成）

### 非范围
- 不进行 `asset_overview` 与 `profit_inquiry` 的物理合并
- 不改 core runner/matcher 机制
- 不改协议层
- 不扩展工具2到 ETF/基金/港股通排行（本期仅股票）

---

## 3. 设计决策（已确认）

1. 不硬合并 skill 文件，采用“语义合并、文件分治”
2. 历史盈亏能力归 `profit_inquiry` 主线
3. 展示策略为“卡片优先”
4. 混合问法默认顺序为“先资产后收益”
5. 工具2对象限定为“股票”

---

## 4. 架构与职责

### 4.1 Skill 职责划分
- `asset_overview`：资产现状/账户健康/总览卡片；收益问题分流
- `profit_inquiry`：收益分析统一入口（当前收益 + 历史收益）

### 4.2 工具1（账户层历史收益曲线）
新增工具：`asset_profit_curve`
- 入参：
  - `account_type`
  - `time_type`（1/3/4/5/13/15）
  - `begin_time`（time_type=5 必填）
  - `end_time`（time_type=5 必填）
- 出参：
  - 曲线点列表
  - 区间汇总（累计盈亏、收益率等可用字段）

> 约束：工具1仅账户层历史信息，不提供 ETF/基金/个股分类历史。

### 4.3 工具2（历史股票盈亏排行）
新增工具（命名待定）：`stock_profit_ranking`
- 入参：`account_type`, `time_type`, `begin_time`, `end_time`, `top_n`（可选）
- 出参：历史区间股票盈亏排行（盈利/亏损榜）
- 范围：仅股票标的

### 4.4 工具3（历史逐日收益明细）
新增工具（命名待定）：`daily_profit_series`
- 入参：`account_type`, `time_type`, `begin_time`, `end_time`
- 出参：区间内每日收益序列（date + profit_amount + rate 可选）

---

## 5. 时间参数映射

- 本月 → `timeType=1`
- 今年 → `timeType=3`
- 近一年 → `timeType=4`
- 自定义区间 → `timeType=5` + `beginTime/endTime`
- 开户以来 → `timeType=13`
- 本周 → `timeType=15`

日期格式统一 `YYYYMMDD`（例如 `20240601`）。

默认策略（建议）：用户未指定区间时，按本月（`timeType=1`）。

---

## 6. 路由与展示策略

### 6.1 查询路由优先级
- “历史总盈亏/收益趋势/账户历史表现” → 工具1（`asset_profit_curve`）
- “哪只股票赚最多/亏最多/排行” → 工具2（`stock_profit_ranking`）
- “每天收益/逐日收益/按天明细” → 工具3（`daily_profit_series`）
- 混合问法（如“近一年趋势+亏损前5股票”）→ 先工具1后工具2（先资产后收益）

### 6.2 卡片优先
`profit_inquiry` 命中历史盈亏意图后，默认先走卡片：
1. 调用对应历史工具
2. 调用 `display_card(source_tool="...")`
3. 返回短确认语

### 6.3 文本降级
以下场景降级文本：
- 卡片渲染失败
- 返回数据为空
- 用户明确要求仅文本

---

## 7. 影响面文件（实施时）

- `src/ark_agentic/agents/securities/tools/agent/asset_profit_curve.py`（新增）
- `src/ark_agentic/agents/securities/tools/agent/stock_profit_ranking.py`（新增）
- `src/ark_agentic/agents/securities/tools/agent/daily_profit_series.py`（新增）
- `src/ark_agentic/agents/securities/tools/agent/__init__.py`
- `src/ark_agentic/agents/securities/tools/__init__.py`
- `src/ark_agentic/agents/securities/tools/service/adapters/__init__.py`
- `src/ark_agentic/agents/securities/tools/service/__init__.py`
- `src/ark_agentic/agents/securities/tools/service/param_mapping.py`
- `src/ark_agentic/agents/securities/tools/service/mock_loader.py`
- `src/ark_agentic/agents/securities/tools/service/field_extraction.py`
- `src/ark_agentic/agents/securities/schemas.py`
- `src/ark_agentic/agents/securities/tools/agent/display_card.py`
- `src/ark_agentic/agents/securities/template_renderer.py`（如需新曲线/排行/逐日卡片）
- `src/ark_agentic/agents/securities/skills/profit_inquiry/SKILL.md`
- `src/ark_agentic/agents/securities/skills/asset_overview/SKILL.md`（仅分流语义微调）
- `tests/agents/securities/test_param_mapping.py`
- `tests/agents/securities/test_field_extraction.py`
- `tests/test_skills_integration.py`

---

## 8. 验收标准

- 可查询账户层历史盈亏：本周、本月、今年、近一年、开户以来、自定义区间
- 可查询历史区间内股票盈亏排行（仅股票）
- 可查询历史区间内逐日收益明细
- 默认卡片展示，失败可文本降级
- 参数映射与日期格式校验通过
- 技能路由正确且不破坏现有资产总览能力

---

## 9. 风险与对策

1. 自然语言时间歧义
   - 对策：skill 明确规则 + tool 参数校验兜底
2. 工具能力边界误解（账户层 vs 分类层）
   - 对策：skill 中明确声明工具1仅账户层；分类/股票问题路由到工具2
3. 卡片链路失败
   - 对策：文本降级模板
4. 能力边界漂移
   - 对策：收益能力集中到 `profit_inquiry`，`asset_overview` 保持总览定位
5. 接口字段不稳定
   - 对策：字段抽取兼容解析 + 缺失字段日志

---

## 10. 技能层次重构（更新版：双技能模型）

### 10.1 最终结论（已确认）

基于联合分析，技能层次采用“双技能模型”替代原四技能草案：

- `asset_query`：查询型技能（实时/历史，账户层/资产类型层）
- `profit_analysis`：分析型技能（收益、损失、风险、原因解读）

> 判定规则：凡问题包含“为什么/原因/风险/解读/怎么看”等分析意图，即使未显式说“分析”，也进入 `profit_analysis`。

### 10.2 双技能职责边界

#### A. `asset_query`（查询型）

**职责**：按用户请求返回客观数据与简要说明，不做深度归因。

**覆盖能力**：
- 实时查询：账户总览、现金、ETF/基金/港股通持仓、标的详情
- 历史查询：
  - 账户层历史收益曲线（`asset_profit_curve`）
  - 历史区间股票盈亏排行（`stock_profit_ranking`，仅股票）
  - 历史逐日收益明细（`daily_profit_series`）

#### B. `profit_analysis`（分析型）

**职责**：针对收益/亏损/波动进行原因、风险、结构化解读；必要时先调用查询工具补齐证据。

**覆盖能力**：
- 当前收益分析
- 历史收益趋势解读
- 股票盈亏排行解读
- 逐日收益波动分析

### 10.3 路由规则（双技能）

1. **查询意图**（“查一下/给我看/当前多少/历史数据”）→ `asset_query`
2. **分析意图**（“为什么/原因/风险/是否异常/怎么理解”）→ `profit_analysis`
3. **混合问法**（查询+分析）→ 先按“先资产后收益”顺序取数，再由 `profit_analysis` 输出分析

### 10.4 行动计划（业务层重构，不改 core matcher/runner）

#### Phase 0：边界与契约治理（0.5 天）
1. 定义双技能路由词典（查询词、分析词、冲突处理优先级）
2. 校正工具契约（确保 required_tools 与正文一致）
3. 固化混合问法默认顺序“先资产后收益”

#### Phase 1：技能重组（1-2 天）
1. 新建 `asset_query/SKILL.md` 与 `profit_analysis/SKILL.md`
2. 将旧技能规则映射迁移到双技能结构
3. 直接下线旧技能（不保留并存），避免同域冲突

#### Phase 2：工具与展示接入（2-3 天）
1. 查询工具池接入双技能模型（含 3 个历史工具）
2. `display_card(source_tool=...)` 映射补齐
3. 建立“卡片优先，文本降级”统一策略

#### Phase 3：验证回归（1-2 天）
1. 路由测试：查询/分析/混合意图矩阵
2. 工具测试：参数校验、空数据、异常降级
3. 回归测试：原有资产查询与收益分析能力不退化

### 10.5 风险与缓解

1. 双技能边界过宽导致误路由
   - 缓解：路由词典 + 示例问句库 + 集成测试约束
2. 分析技能缺少证据支撑
   - 缓解：`profit_analysis` 强制“先取数后解读”
3. 旧技能并存造成冲突
   - 缓解：迁移期明确优先级与灰度策略，完成后下线旧技能


