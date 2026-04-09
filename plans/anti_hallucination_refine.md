在提示词中强迫 LLM 生成带有 `citations` 的 JSON 结构，不仅会大幅增加 Token 消耗，还会因为 JSON 序列化和注意力分散导致首字延迟（TTFT）显著恶化。这与追求极致性能（比如你之前将导航端到端延迟优化 40% 的思路）是背道而驰的。

在 `ark-agentic-framework` 这种企业级 Agent 框架中，将“证据链生成”与“文本生成”解耦，走向**后置验证（Post-hoc Validation）**是目前兼顾轻量与高效的最佳实践。

下面为你提供主流方案的对比，以及一套贴合你现有代码的轻量化改造建议。

### 一、 主流幻觉检测方案对比

从多视角的架构评估来看，目前行业内处理 RAG/Agent 幻觉检测主要有三条路径：

1.  **LLM Self-Citation（你目前的方案）**
    * **机制：** LLM 在输出回答的同时，按严格格式输出引用来源。
    * **缺点：** 性能开销极大，容易出现格式错误，且大模型“自圆其说”的特性可能导致它伪造一条不存在的工具数据来迎合引用。
2.  **Cross-Encoder / NLI 模型后置校验（学术界主流）**
    * **机制：** 用一个额外的轻量级自然语言推理（NLI）模型（如 DeBERTa），判断 Output 是否蕴含于 Context。
    * **缺点：** 虽然准确，但在工程上引入了新的模型推理服务，增加系统复杂度和延迟，不符合“简单优雅”的实用主义设计。
3.  **Lexical & Rule-based 逆向匹配（工业界实用首选）**
    * **机制：** LLM 仅输出纯文本纯享版回答。通过正则、Trie 树等规则引擎从输出中提取关键实体，逆向到 Context 和 Tool Outputs 中去全文检索。
    * **优点：** 极其轻量，毫秒级开销，无额外 Token 成本。

### 二、 轻量化工程重构建议

你的 `validation.py` 其实已经具备了极好的底子。你使用了 `FlashText` 处理实体，并且写了完善的日期和数字正则。我们只需要**将“校验器”翻转为“提取器”**。

具体架构调整如下：

#### 1. 释放 LLM，恢复纯文本流式输出
从 Prompt 中彻底移除要求输出 JSON 和调用 `cite_record` 的指令。让 LLM 专注于把回答写好，直接返回 Markdown 文本。这能极大提升证券类业务的响应速度。

#### 2. 构建后置“逆向提取-映射”流水线
在 `create_citation_validation_hook` 中，拦截 LLM 的纯文本输出，执行以下三步：

**Step A: 高速提取 (Extraction)**
直接复用你写好的提取逻辑，从 LLM 的 `answer` 中捞出三大件：
* **证券实体：** 用现有的 `EntityTrie.extract(answer)` 拿到所有股票名称、代码。
* **数字：** 用 `extract_numbers_from_text(answer)` 拿到所有业务数值（如账户资产、持仓数量）。
* **时间：** 用现有的正则捞出日期。

**Step B: 扁平化数据源构建 (Flattened Context)**
把当前轮次调用的所有工具输出（如持仓查询接口、行情接口返回的 JSON）扁平化转换为纯文本字符串，加上用户的历史 Context，作为唯一的**事实语料库**。
```python
# 伪代码：将工具数据和用户上下文拼接成一个巨大的事实字符串
fact_corpus = build_fact_corpus(tool_sources, context)
```

**Step C: 逆向匹配与归属 (Reverse Grounding)**
遍历 Step A 提取出的所有元素（$E_{1}, E_{2}...$），使用快速字符串匹配（对于 FlashText 来说是极快的）去事实语料库中查找。
* **命中：** 如果实体/数字在 `fact_corpus` 中存在，说明有数据支撑（Safe）。
* **未命中：** 如果提取出的数值或实体在所有接口返回中都找不到，触发 Hallucination 警告（Warn/Retry）。

#### 3. 性能优化技巧：Aho-Corasick 算法 / FlashText 双向应用
为了快速知道一个实体具体属于哪个工具（比如你想在前端 UI 呈现状态感知，用不同颜色高亮不同数据源的内容）：
你可以把 `tool_sources` 的 Key 作为返回值注入到 `FlashText` 中。
```python
# 动态构建一个针对当前请求的 KeywordProcessor
kp = KeywordProcessor()
for tool_key, tool_text in tool_sources.items():
    # 假设你对 tool_text 进行了分词或直接作为长字符串处理
    # 这样可以在 O(N) 的时间复杂度内，扫一遍 LLM 的 answer，
    # 瞬间得到 [("平安银行", "tool_market_data"), ("15000.00", "tool_account_asset")]
```

### 四、 本轮落地范围（收敛版）

为了降低改造风险，本轮仅做最小必要改动，明确**不改生命周期调用点**，继续沿用当前 `before_complete` 的接入方式。

#### 本轮会做
1. **移除 LLM 自提取 citation 的工具和提示词依赖**
   * 从证券 Agent prompt 中删除要求调用 `record_citations`、输出引用 JSON/结构化 citation 的约束。
   * 从证券 Agent 的工具注册中移除 `RecordCitationsTool`。
2. **在现有 `before_complete` hook 内切换为后置逆向校验**
   * 直接读取最终 `answer` 文本。
   * 使用 `EntityTrie.extract(answer)` 提取证券实体。
   * 使用现有数字/日期提取逻辑提取业务数值与时间。
   * 将 `tool_sources + context` 扁平化后做 reverse grounding，并归属命中的来源。
3. **保持现有 route 语义不变**
   * 仍然输出 `safe / warn / retry`。
   * 仍然在 `retry` 时通过 `before_complete` 返回反馈消息触发自修正。

#### 本轮不会做
1. **不改 Runner / 生命周期调用点**
   * 不调整 `before_complete` 的注册位置与触发时机。
2. **不改流式输出语义**
   * 不引入 buffer、draft/final 双通道或新的 stream event。
3. **不实现 Derived Data 容错**
   * 例如 `5000 + 2000 = 7000` 这种派生数值，暂不视为可自动豁免的 grounded claim。
4. **不全面清理遗留兼容代码**
   * 如 `parse_cited_response`、旧 citation 数据结构可以暂时保留，避免扩大改动面。

#### 实现要点
- 核心改造集中在 `src/ark_agentic/core/validation.py` 的 hook 内部逻辑。
- 校验输入由 `_pending_citations` 切换为 `response.content`。
- 对每个提取出的 claim：
  * 若能在某个 `tool_source` 或 `context` 中命中，则视为 grounded；
  * 若完全未命中，则记为校验错误；
  * 若命中多个来源，只要存在有效来源即可，不视为错误。
- 命中来源将被记录到错误/调试信息中，为后续 UI 高亮预留基础。
