# 幻觉（Hallucination）处理设计文档

版本：2026-04-06

## 目的

梳理仓库中已实现的幻觉检测/校验机制，评估优缺点，并给出可落地的改进与工程化建议，便于在金融场景中降低 LLM 幻觉带来的风险。

## 现状概览（代码位置）

- 核心校验器：[src/ark_agentic/core/validation.py](src/ark_agentic/core/validation.py)
- 证券域回调：[src/ark_agentic/agents/securities/validation.py](src/ark_agentic/agents/securities/validation.py)
- 注册点：AgentRunner 的 `after_agent` 回调（`src/ark_agentic/core/runner.py`）
- 相关设计草案/计划：[plans/anti_hallucination_new.md](plans/anti_hallucination_new.md), [plans/anti_hallucination_draft.md](plans/anti_hallucination_draft.md)
- 单元测试：`tests/unit/agents/test_securities_validation.py` 等

## 已实现要点（可直接复用）

- 单轮闭环（Single-pass loop）：LLM 生成包含 `answer + citations` 的结构化输出，系统做确定性校验（无二次推理）。
- 结构化 Cite：`{value,type,source}`，type: ENTITY/TIME/NUMBER，source: `tool_x` 或 `context`。
- 确定性校验逻辑（`validate_citations`）：
  - 校验 citation 是否在对应 source 文本中出现（字符串/子串匹配）；
  - 从 `answer` 中使用正则（日期/数字）与 `EntityTrie`（flashtext）抽取未标注要素，标为 `UNCITED`；
  - 归一化处理日期（中文/紧凑 YYYYMMDD → ISO）并解析相对时间；
  - 基于错误数计算分数并路由：`safe` / `warn` / `retry`；`retry` 会触发 Critic 重试（可限次）。
- 工程集成：证券 Agent 将工具快照写入 `session.state`，回调读取 `_pending_citations` 与工具快照进行验证，结果写入 `response.metadata["validation"]`。

## 优点

- 低工程成本：纯 Python（regex + flashtext + JSON 遍历），无额外模型依赖，延迟低。
- 可解释性强：明确的 errors 列表与 route，便于在 UI 中展示溯源。
- 易扩展：校验器以 hook 形式注入 AgentRunner，可按域注册不同 `tool_keys` 与 `EntityTrie`。

## 限制与风险

- 字符串匹配为主，缺乏语义对齐（例如同义/别名、模糊数值表达、四舍五入误差等场景易误判）。
- 对复杂推理型幻觉（模型编造不存在的数据源、跨表推理错误）覆盖有限。
- 性能：当前对每个 tool source 做全量正则替换与 JSON -> str 序列化，面对大型工具输出（几十 MB）有成本。
- 流式场景未覆盖：校验发生在 final answer 之后，无法在生成流中早期阻断幻觉输出。

## 改进建议（优先级排序）

1. 可配置阈值与维度权重（高优先）：将 `_ERROR_PENALTY`, `_MIN_BUSINESS_NUMBER`, 时间/实体/数字权重暴露为可注入的 `ValidationConfig`。方便按域调优。

2. 增加模糊/语义匹配（中优先）：
   - 对数字：支持容差比对（相对误差阈值）与单位换算（万/亿）；已有实现部分支持，需集中配置并补充单测。
   - 对实体：在 Trie 命中之外提供可选的语义近似（e.g., fuzzy match via edit distance 或向量检索）作为降级分数，而非直接 veto。

3. 性能优化（中优先）：延迟归一化工具文本，仅当 `_pending_citations` 中存在 `tool_...` 引用或需要比对时再处理；对大型 JSON 支持按字段抽取而非全串化。

4. 流式/句级校验（中低优先）：设计 Sentence Buffer 接口，按句或按句端标点触发快速本地校验，遇 `retry` 可在流中插入占位或断流提示。

5. 可观测性与指标（高优先）：增加统计与日志（校验通过率、各类错误分布、重试次数、重试成功率），并将 `validation` metadata 标准化以便采集。

6. UI/UX 约定（中优先）：定义前端展示字段（`route`, `score`, `issues[]`），以及当 `route==retry` 时的交互策略（自动重试/提示用户/显示兜底文案）。

## 建议的 API / Config

新增 `ValidationConfig` dataclass：

```py
class ValidationConfig:
    number_weight: float = 0.5
    entity_weight: float = 0.3
    time_weight: float = 0.2
    error_penalty: float = 0.2
    min_business_number: float = 100.0
    numeric_tolerance: float = 0.01  # 1%
    max_retry_attempts: int = 3
    enable_fuzzy_entity: bool = False

    # perf toggles
    lazy_normalize_tool_text: bool = True
```

Hook 工厂签名扩展：

```py
def create_citation_validation_hook(tool_keys: set[str], *, config: ValidationConfig, entity_trie: EntityTrie | None = None) -> BeforeCompleteCallback:
    ...
```

## 迁移/迭代计划（小步快跑）

1. 将现有常量提取为 `ValidationConfig`（1 天）并添加单元测试覆盖。
2. 添加 `lazy_normalize_tool_text` 路由控制，避免不必要的全量正则替换（0.5 天）。
3. 增加更多数值与日期解析单测（0.5–1 天）。
4. 集成基础指标（Prometheus/日志）与 `response.metadata.validation` 字段格式化（1 天）。
5. 评估语义/向量方法对实体匹配的价值，试验 PoC（2–3 天）。

## 测试建议

- 覆盖場景：显式/隐式日期、相对時間、千分位/单位（万、亿）、模糊实体别名、工具文本中 YYYYMMDD 格式。
- 为 `retry` 分支写端到端测试：mock tool snapshot → 模拟 LLM 返回不带 cite 的回答 → 验证 Critic 重试行为与兜底文案。

## 小结

当前仓库实现已提供一个实用、低成本的幻觉检测闭环，适合金融类结构化场景。下一步应先把运行时阈值与权重配置化、补强测试与可观测性，再在需要的域引入渐进式模糊/语义匹配与流式句级拦截。

---
文件生成自仓库现状扫描，若需我将按上述计划把 `ValidationConfig` 与 tests 的改动提交为小 PR，或直接把文档同步到 docs/ 下，请回复首选路径。
