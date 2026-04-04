这是一份针对金融、证券等高严谨度场景的 Agent 防幻觉设计说明。**下文「已实现」与仓库代码一致（`local-presentation` 分支方向）；「未实现」保留原架构设想供后续迭代。**

---

# 防幻觉校验：设计愿景与当前落地

## 已实现（代码现状）

### 接入方式：整段回复 + `after_agent`，非流式句级拦截

- **未做** Token/SSE 句级 Buffer、流式拦截器；校验在 **一轮 ReAct 结束、最终 assistant 文本生成之后** 执行。
- [`AgentRunner._finalize_run`](src/ark_agentic/core/runner.py) 调用 `after_agent` 钩子；若回调返回 `CallbackResult(response=...)`，则 **替换** 本次 `RunResult.response`（用于 Critic 重写或兜底文案）。
- 通用 Runner **已移除** `enable_output_validation` 及在 `_finalize_response` 内嵌的数值校验；校验 **按 Agent 域** 通过回调注册（当前仅证券 Agent 注册）。

### 证券域：状态中的事实基准 + CSV 实体白名单

- 实现：[`create_securities_validation_callback`](src/ark_agentic/agents/securities/validation.py)。
- **事实来源 $C_{api}$（实现形态）**：从 `session.state` 中按 `_SECURITIES_TOOL_KEYS` 读取各工具经 `state_delta` 写入的快照，再合成 `list[AgentToolResult]`；**不是**从消息里逐条解析 tool message。
- **实体**：仅 [`EntityTrie`](src/ark_agentic/core/validation.py)（[flashtext](https://github.com/vi3k6i5/flashtext) `KeywordProcessor`）+ **CSV**（`code` / `name` 列）加载白名单；**无 Trie 时实体维度跳过**（满分、不 veto）。
- **Critic 重试**：`route == "retry"` 时用独立 `llm.ainvoke` 按 `retry_prompt` 重写；最多 `max_retry_attempts`（默认 3）；失败则固定兜底话术。`llm is None` 时直接返回兜底，不重试。
- **元数据**：首轮 `response.metadata["validation"]` 写入 `route`、`total_score`、`vetoed`、`dimension_scores`、`issues` 等。

### 核心打分模块：[`ark_agentic.core.validation`](src/ark_agentic/core/validation.py)

| 项目 | 实现要点 |
|------|-----------|
| 权重 | $W_{num}=0.5,\ W_{ent}=0.3,\ W_{time}=0.2$（常量 `_NUMBER_WEIGHT` 等） |
| 路由阈值 | `total_score >= 85` → `safe`；`60 <= score < 85` → `warn`；**`score < 60` 或任一度 veto** → `retry`（并生成 `retry_prompt`） |
| 数值 | 从回复用正则抽数；**仅 `abs(n) >= 100`** 参与业务比对（`_MIN_BUSINESS_NUMBER`）；工具侧递归收集非零数值；精确匹配 1.0 分，相对误差 ≤1%（`_DEFAULT_NUMERIC_TOLERANCE`）0.6 分，**万单位折算**后再比 0.8 分；否则该数 **veto** |
| 实体 | 仅 Trie：回复 / 用户输入 / 工具 JSON 拼串上 `extract`；在工具或用户中命中计分，否则 veto |
| 时间 | 工具 JSON + **`session_state` 递归**扫 `YYYY-MM-DD` 合并为 `candidate_dates`；**显式日期**须为 `candidate_dates` 子集，否则 veto；**用户未提「昨日」而回复写「昨日」** → veto；**用户明确「昨日」而回复写「今日/当前」** → veto；**不**用系统日历强制对齐「今日」与 `business_date`（避免与交易日语义冲突） |
| 重试提示 | `_serialize_tool_snapshot`：`json.dumps` 按工具块输出，**单块/总长截断**（`_RETRY_PER_TOOL_MAX_CHARS` / `_RETRY_TOOL_SNAPSHOT_MAX_CHARS`） |

**模型类型**：[`ValidationResult`](src/ark_agentic/core/validation.py) 含 `passed`、`issues`（含 `dimension`）、`vetoed`、`total_score`、`route`、`retry_prompt`、`dimension_scores`。

**工具函数**：`resolve_relative_time` 仍提供（整串「今天」「上周X」等 → ISO 日期），**当前 `_score_time` 未对整段回复做子串相对时间解析**；单元测试覆盖该函数。

---

## 未实现 / 与初稿差异（后续可做）

以下对应原文「句级缓冲 + 异步双轨 + 流式阻断」设想，**当前仓库未实现**：

- 流式 SSE 监听、按标点切句的 **Sentence Buffer**。
- 句级并行校验、按句 **阻断推流**。
- UI：绿色高亮溯源、「数据校验中」黄色态（需前后端协议配合）。

**工程建议（仍适用）**：打分路径以纯 Python（正则、JSON 遍历）为主；域差异用 **可插拔回调 + 配置**（证券已实现回调模式），而非把业务校验写死在 `AgentRunner` 核心循环内。

---

# 附录：初稿中的符号与公式（与实现对齐部分）

- **$C_{api}$**：实现上 = 当前用于校验的 `AgentToolResult` 内容（证券场景下主要来自 `session.state` 快照）。
- **$S_{total}$**：与代码一致，为三维加权；**veto** 时对应维度 issues + `route=retry`（或总分过低）。
- **数值子项**：实现除「精确 / 容差 / 万单位」外，还带 **按出现次数** 的平均分母，与初稿公式形式略有不同，但语义一致（无中生有大数 → veto）。

---

## 相关文件

| 路径 | 说明 |
|------|------|
| [`src/ark_agentic/core/validation.py`](src/ark_agentic/core/validation.py) | 数字/实体(Trie)/时间校验、`validate_response_against_tools`、`EntityTrie` |
| [`src/ark_agentic/agents/securities/validation.py`](src/ark_agentic/agents/securities/validation.py) | 证券 `after_agent` 回调、state 抽取、Critic 重试 |
| [`src/ark_agentic/agents/securities/agent.py`](src/ark_agentic/agents/securities/agent.py) | 注册 `after_agent`、CSV 路径 `mock_data/stocks/a_shares_seed.csv` |
| [`src/ark_agentic/core/runner.py`](src/ark_agentic/core/runner.py) | `after_agent` 可替换最终 `response` |
| [`tests/unit/core/test_validation.py`](tests/unit/core/test_validation.py) | 校验与 Trie 单测 |
