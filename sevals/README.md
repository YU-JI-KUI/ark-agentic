# Evals — Skill 评测框架

独立于主框架的评测目录，验证各 skill 的工具调用准确率。

## 目录结构

```
evals/
├── cases/                      # 评测用例（JSON，按 agent 分组）
│   └── insurance/
│       └── withdraw_money.json
├── runner/                     # 评测工具包
│   ├── agent_factory.py        # 创建隔离 agent 实例
│   ├── case_loader.py          # 加载 JSON 用例
│   └── scorer.py               # 评分逻辑
├── conftest.py                 # pytest fixture（data 隔离）
├── test_insurance.py           # 保险 agent 测试入口
└── README.md
```

## 运行

```bash
# 全部评测
uv run pytest sevals/ -v

# 只跑保险
uv run pytest sevals/test_insurance.py -v

# 显示每个 case 的详细命中情况
uv run pytest sevals/ -v -s
```

## 用例格式（cases/insurance/withdraw_money.json）

```json
{
  "skill": "withdraw_money",
  "agent": "insurance",
  "user_id": "eval_u001",
  "cases": [
    {
      "id": "summary_no_amount",
      "description": "用户问能取多少，应触发 SUMMARY 流程",
      "input": "我能取多少钱",
      "expect_tools": ["rule_engine", "render_a2ui"]
    }
  ]
}
```

### 字段说明

| 字段 | 必须 | 说明 |
|---|---|---|
| `skill` | ✅ | 对应的 skill 名称 |
| `agent` | ✅ | 使用哪个 agent（insurance / securities） |
| `user_id` | ✅ | 固定 mock 用户 ID |
| `id` | ✅ | case 唯一标识 |
| `description` | ✅ | 描述测试意图 |
| `input` | ✅ | 用户输入文本 |
| `expect_tools` | ✅ | 期望调用的工具列表；空数组表示不应调用任何工具 |

## 评分规则（第一版）

- **命中**：expect_tools 中的工具都被实际调用 → score = 1.0 → PASS
- **遗漏**：有工具未被调用 → score < 1.0 → FAIL
- **多调**：调用了 expect_tools 之外的工具 → 仅记录，不扣分（第一版）
- **expect 为空**：实际无调用 → PASS；有调用 → FAIL

## data 隔离

每个测试用例使用 pytest `tmp_path` 独立临时目录，测试结束自动清理，
不影响也不依赖 `data/` 下的任何生产数据。

## 后续维度（渐进叠加，旧 case 无需改动）

在 case 中追加可选字段即可启用更多校验：

```json
{
  "expect_tool_args": {"rule_engine": {"action": "list_options"}},
  "expect_tool_order": ["rule_engine", "render_a2ui"],
  "response_excludes": ["¥", "50000"]
}
```
