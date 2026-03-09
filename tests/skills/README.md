# Skill evals and workspace (skill-creator)

测试相关资产与项目代码分离：技能定义在 `src/ark_agentic/agents/insurance/skills/`，evals 与运行结果在此目录。

## 结构

- **insurance/** — 保险技能 evals
  - `withdraw_money/evals/evals.json` — 保险取款技能用例
  - `rewrite_plan/evals/evals.json` — 方案改写技能用例
- **insurance-skills-workspace/** — 运行产物（skill-creator 约定）
  - `iteration-1/` — 第一轮 4 个 eval（with_skill / without_skill）及 benchmark
  - `review.html` — 静态 Eval Viewer（用浏览器打开）

## 技能路径（运行 evals 时需指向）

- 保险取款: `src/ark_agentic/agents/insurance/skills/withdraw_money/SKILL.md`
- 方案改写: `src/ark_agentic/agents/insurance/skills/rewrite_plan/SKILL.md`

## 常用命令

- 生成 Viewer（需 UTF-8 环境或 patch `Path.read_text`）:
  ```bash
  python <skill-creator>/eval-viewer/generate_review.py tests/skills/insurance-skills-workspace/iteration-1 \
    --skill-name "insurance-skills" \
    --benchmark tests/skills/insurance-skills-workspace/iteration-1/benchmark.json \
    --static tests/skills/insurance-skills-workspace/review.html
  ```
