# Securities 双技能迁移 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将证券域技能重构为 `asset_query` 与 `profit_analysis` 两技能，并通过“按固定时间类型/按时间范围”两类统一查询工具封装实时与历史接口，提升模型调用稳定性与可维护性。

**Architecture:** 保持 `core matcher/runner` 不变，仅在 securities 域做业务层改造。旧技能不保留，直接切换为双技能；工具层新增统一封装器，将现有实时接口与新增历史接口映射到两类标准查询入口（period/range），分析技能只消费统一查询结果。

**Tech Stack:** Python 3.12+, Ark-Agentic skills/tool framework, Pydantic, pytest

---

## 0. 关键约束（已确认）

1. **不保留旧技能**：迁移完成后仅保留 `asset_query` 与 `profit_analysis`，避免冲突。  
2. **工具统一封装**：面向模型只暴露两类查询接口：
   - 基于固定时间类型（当天/周/月/年）
   - 基于时间范围（start_date~end_date）
3. **工具命名语义清晰**：新命名统一以 `query_` 前缀表达“查询动作”。
4. **模型决策优先简单参数**：时间参数统一、查询维度可枚举，减少自由文本歧义。

---

## 1. 目标技能结构（迁移后）

- `asset_query`（查询型）
  - 实时+历史查询
  - 账户层/资产类别层/标的层信息检索
  - 仅返回客观数据与简述，不做深度归因

- `profit_analysis`（分析型）
  - 收益/亏损/风险/波动解读
  - 必要时先调用查询工具补证据
  - 分析意图强优先（“为什么/原因/风险/怎么看”等）

> 注意：`asset_overview`、`holdings_analysis`、`profit_inquiry` 迁移后下线，不再参与加载。

---

## 2. 工具清单与参数设计（统一封装）

### 2.1 模型可见工具（最终）

#### Tool A: `query_assets_by_period`
**用途**：固定时间类型查询（TODAY/WEEK/MONTH/YEAR）。

**参数设计**：
- `account_type: str`  
  - 可选：`normal` / `margin`
- `period_type: str`  
  - 可选：`TODAY` / `WEEK` / `MONTH` / `YEAR`
- `query_topic: str`  
  - 可选：
    - `ACCOUNT_OVERVIEW`（账户总览）
    - `ASSET_HOLDINGS`（资产持仓，如 ETF/基金/港股通）
    - `SECURITY_DETAIL`（标的详情）
    - `PROFIT_TREND`（账户收益趋势）
    - `STOCK_PROFIT_RANKING`（股票盈亏排行）
    - `DAILY_PROFIT_SERIES`（逐日收益）
- `asset_scope: str | null`  
  - 可选：`ALL` / `ETF` / `FUND` / `HKSC` / `STOCK`
  - 默认 `ALL`
- `security_code: str | null`（`SECURITY_DETAIL` 必填）
- `sort_order: str | null`（排行主题可选：`DESC`/`ASC`）
- `top_n: int | null`（排行主题可选，默认 5）
- `output_mode: str | null`（`CARD`/`TEXT`，默认 `CARD`）

#### Tool B: `query_assets_by_date_range`
**用途**：指定时间范围查询（start_date~end_date）。

**参数设计**：
- `account_type: str`（`normal` / `margin`）
- `start_date: str`（`YYYYMMDD`）
- `end_date: str`（`YYYYMMDD`）
- `query_topic: str`（同 Tool A）
- `asset_scope: str | null`（同 Tool A）
- `security_code: str | null`（同 Tool A）
- `sort_order: str | null`（同 Tool A）
- `top_n: int | null`（同 Tool A）
- `output_mode: str | null`（同 Tool A）

### 2.2 封装层对底层接口映射

- `ACCOUNT_OVERVIEW` → `account_overview`（实时）
- `ASSET_HOLDINGS` → `etf_holdings` / `fund_holdings` / `hksc_holdings`（按 `asset_scope` 路由）
- `SECURITY_DETAIL` → `security_detail`
- `PROFIT_TREND` → `getUerAssetPftCurve`（历史账户收益曲线；账户层）
- `STOCK_PROFIT_RANKING` → 新历史股票排行接口（仅股票）
- `DAILY_PROFIT_SERIES` → 新历史逐日收益接口

### 2.3 时间映射规则（封装器内部）

- `TODAY` / `WEEK` / `MONTH` / `YEAR` 映射为内部 timeType 或实时查询策略
- `start_date/end_date` 映射为 range 查询
- 日期统一 `YYYYMMDD`，封装器负责标准化与校验

---

## 3. 实施任务（Bite-sized）

### Task 1: 重构技能目录并移除旧技能

**Files:**
- Create: `src/ark_agentic/agents/securities/skills/asset_query/SKILL.md`
- Create: `src/ark_agentic/agents/securities/skills/profit_analysis/SKILL.md`
- Delete: `src/ark_agentic/agents/securities/skills/asset_overview/SKILL.md`
- Delete: `src/ark_agentic/agents/securities/skills/holdings_analysis/SKILL.md`
- Delete: `src/ark_agentic/agents/securities/skills/profit_inquiry/SKILL.md`
- Test: `tests/test_skills_integration.py`

**Step 1:** 写 `asset_query` 技能规则（查询优先、输出约束、工具调用顺序）。  
**Step 2:** 写 `profit_analysis` 技能规则（先取数后分析、风险解读模板）。  
**Step 3:** 删除旧技能文件，确保不会被 loader 加载。  
**Step 4:** 增加技能加载测试，断言只剩 2 个技能。

---

### Task 2: 实现统一查询封装工具

**Files:**
- Create: `src/ark_agentic/agents/securities/tools/agent/query_assets_by_period.py`
- Create: `src/ark_agentic/agents/securities/tools/agent/query_assets_by_date_range.py`
- Modify: `src/ark_agentic/agents/securities/tools/agent/__init__.py`
- Modify: `src/ark_agentic/agents/securities/tools/__init__.py`
- Test: `tests/agents/securities/test_param_mapping.py`

**Step 1:** 为两类工具定义 Pydantic 输入模型与校验规则。  
**Step 2:** 实现 `query_topic + asset_scope` 到底层工具/API 的路由。  
**Step 3:** 统一返回结构（data + summary + metadata），供分析技能复用。  
**Step 4:** 为 period/range 场景补参数单测。

---

### Task 3: 接入底层服务映射与抽取

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/service/adapters/__init__.py`
- Modify: `src/ark_agentic/agents/securities/tools/service/__init__.py`
- Modify: `src/ark_agentic/agents/securities/tools/service/param_mapping.py`
- Modify: `src/ark_agentic/agents/securities/tools/service/field_extraction.py`
- Modify: `src/ark_agentic/agents/securities/tools/service/mock_loader.py`
- Modify: `src/ark_agentic/agents/securities/schemas.py`
- Test: `tests/agents/securities/test_field_extraction.py`

**Step 1:** 新增历史排行/逐日收益映射项。  
**Step 2:** 统一 timeType 与 range 参数标准化。  
**Step 3:** 完成返回字段抽取与 schema 对齐。  
**Step 4:** 增加 mock 数据与抽取测试。

---

### Task 4: 展示层统一（卡片优先、文本降级）

**Files:**
- Modify: `src/ark_agentic/agents/securities/tools/agent/display_card.py`
- Modify: `src/ark_agentic/agents/securities/template_renderer.py`
- Test: `tests/test_skills_integration.py`

**Step 1:** 为统一封装工具结果增加 card 渲染分支。  
**Step 2:** 统一降级文案模板。  
**Step 3:** 增加 CARD/TEXT 两种模式集成测试。

---

### Task 5: 双技能路由与回归测试

**Files:**
- Modify: `tests/test_skills_integration.py`
- Modify: `tests/core/test_runner_skill_load_mode.py`
- Modify: `tests/core/test_read_skill_tool.py`

**Step 1:** 构建查询意图/分析意图/混合意图样例集。  
**Step 2:** 断言分析意图强制进入 `profit_analysis`。  
**Step 3:** 回归验证历史与实时查询均可用。

---

## 4. 验证命令

```bash
uv run pytest tests/agents/securities/test_param_mapping.py -v
uv run pytest tests/agents/securities/test_field_extraction.py -v
SECURITIES_SERVICE_MOCK=true uv run pytest tests/test_skills_integration.py -v
SECURITIES_SERVICE_MOCK=true uv run pytest tests/agents/securities/ -v
```

---

## 5. 完成判据（DoD）

- 技能目录仅存在 `asset_query` 与 `profit_analysis`
- 模型仅使用 `query_assets_by_period` / `query_assets_by_date_range` 两类查询工具进行查询决策
- 历史能力覆盖：账户趋势、股票排行、逐日收益
- 分析意图稳定路由到 `profit_analysis`
- 卡片优先策略与文本降级可用
- 全量测试通过且无旧技能冲突
