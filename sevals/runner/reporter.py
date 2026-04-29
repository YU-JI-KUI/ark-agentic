"""
reporter — 生成评测 HTML 报告

职责：接收所有 CaseScore，渲染成自包含的 HTML 文件。
与测试逻辑完全解耦：只依赖 CaseScore dataclass，不依赖 pytest。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .scorer import CaseScore


@dataclass
class SkillReport:
    """单个 skill 的汇总报告。"""
    skill: str
    agent: str
    cases: list[CaseScore] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass
class EvalReport:
    """整次评测运行的完整报告。"""
    run_at: datetime = field(default_factory=datetime.now)
    model: str = field(default_factory=lambda: os.getenv("MODEL_NAME", "unknown"))
    skills: list[SkillReport] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(s.total for s in self.skills)

    @property
    def passed(self) -> int:
        return sum(s.passed for s in self.skills)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


# ── HTML 模板 ──────────────────────────────────────────────────────────────────

_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ark Eval Report · {run_at}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background: #f5f6fa; color: #2d3436; line-height: 1.6; }}

  /* ── 顶部摘要 ── */
  .header {{ background: #2d3436; color: #fff; padding: 32px 40px; }}
  .header h1 {{ font-size: 22px; font-weight: 600; margin-bottom: 4px; }}
  .header .meta {{ font-size: 13px; color: #b2bec3; }}
  .summary {{ display: flex; gap: 24px; margin-top: 20px; }}
  .stat {{ background: rgba(255,255,255,.08); border-radius: 8px;
           padding: 14px 20px; min-width: 110px; }}
  .stat-value {{ font-size: 28px; font-weight: 700; }}
  .stat-label {{ font-size: 12px; color: #b2bec3; margin-top: 2px; }}
  .pass-rate {{ color: {pass_rate_color}; }}

  /* ── skill 卡片 ── */
  .content {{ padding: 32px 40px; display: flex; flex-direction: column; gap: 28px; }}
  .skill-card {{ background: #fff; border-radius: 12px;
                 box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }}
  .skill-header {{ padding: 16px 24px; border-bottom: 1px solid #f0f0f0;
                   display: flex; align-items: center; gap: 12px; }}
  .skill-name {{ font-size: 16px; font-weight: 600; }}
  .skill-agent {{ font-size: 12px; color: #636e72; background: #f0f0f0;
                  border-radius: 4px; padding: 2px 8px; }}
  .skill-rate {{ margin-left: auto; font-size: 14px; font-weight: 600; }}

  /* ── 用例表格 ── */
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background: #f8f9fa; padding: 10px 16px; text-align: left;
        font-size: 12px; color: #636e72; font-weight: 600;
        text-transform: uppercase; letter-spacing: .5px; }}
  td {{ padding: 12px 16px; font-size: 13px;
        border-top: 1px solid #f5f5f5; vertical-align: top; }}
  tr.pass td:first-child {{ border-left: 3px solid #00b894; }}
  tr.fail td:first-child {{ border-left: 3px solid #d63031; }}
  tr:hover td {{ background: #fafafa; }}

  /* ── 工具 badge ── */
  .tools {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .badge {{ border-radius: 4px; padding: 2px 8px; font-size: 11px;
            font-weight: 500; white-space: nowrap; }}
  .badge-hit     {{ background: #d4f5e9; color: #00864e; }}
  .badge-missing {{ background: #ffe0e0; color: #c0392b; }}
  .badge-extra   {{ background: #fff3cd; color: #856404; }}
  .badge-expect  {{ background: #e8f4fd; color: #0066cc; }}

  /* ── 结果 badge ── */
  .result {{ font-size: 12px; font-weight: 700; border-radius: 4px;
             padding: 3px 10px; display: inline-block; }}
  .result-pass {{ background: #d4f5e9; color: #00864e; }}
  .result-fail {{ background: #ffe0e0; color: #c0392b; }}

  .score {{ font-size: 13px; color: #636e72; }}
  .reason {{ font-size: 12px; color: #d63031; margin-top: 4px; }}
  .desc {{ font-size: 12px; color: #636e72; margin-top: 2px; }}
  .input-text {{ font-size: 13px; }}
</style>
</head>
<body>

<div class="header">
  <h1>Ark Eval Report</h1>
  <div class="meta">运行时间：{run_at} &nbsp;·&nbsp; 模型：{model}</div>
  <div class="summary">
    <div class="stat">
      <div class="stat-value pass-rate">{pass_rate_pct}%</div>
      <div class="stat-label">通过率</div>
    </div>
    <div class="stat">
      <div class="stat-value">{passed}</div>
      <div class="stat-label">通过</div>
    </div>
    <div class="stat">
      <div class="stat-value">{failed}</div>
      <div class="stat-label">失败</div>
    </div>
    <div class="stat">
      <div class="stat-value">{total}</div>
      <div class="stat-label">总用例</div>
    </div>
  </div>
</div>

<div class="content">
{skill_cards}
</div>

</body>
</html>
"""

_SKILL_CARD = """\
<div class="skill-card">
  <div class="skill-header">
    <span class="skill-name">{skill}</span>
    <span class="skill-agent">{agent}</span>
    <span class="skill-rate" style="color:{rate_color}">{passed}/{total} &nbsp;{rate_pct}%</span>
  </div>
  <table>
    <thead>
      <tr>
        <th style="width:140px">用例 ID</th>
        <th style="width:200px">用户输入</th>
        <th>期望工具 / 实际工具</th>
        <th style="width:110px">结果</th>
      </tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>
</div>
"""

_ROW = """\
      <tr class="{row_class}">
        <td>
          <div>{case_id}</div>
          <div class="desc">{description}</div>
        </td>
        <td><div class="input-text">{user_input}</div></td>
        <td>
          <div class="tools">{tool_badges}</div>
          {reason_html}
        </td>
        <td>
          <span class="result {result_class}">{result_text}</span>
          <div class="score">score {score:.2f}</div>
        </td>
      </tr>
"""


def _tool_badges(case: "CaseScore") -> str:
    badges = []
    for t in sorted(case.hit):
        badges.append(f'<span class="badge badge-hit">✓ {t}</span>')
    for t in sorted(case.missing):
        badges.append(f'<span class="badge badge-missing">✗ {t}</span>')
    for t in sorted(case.extra):
        badges.append(f'<span class="badge badge-extra">+ {t}</span>')
    # 若 expect 和 actual 都为空（正确无工具调用）
    if not case.hit and not case.missing and not case.extra:
        badges.append('<span class="badge badge-expect">无工具调用 ✓</span>')
    return "\n".join(badges)


def render_report(report: EvalReport) -> str:
    """将 EvalReport 渲染为 HTML 字符串。"""

    pass_rate_color = "#00b894" if report.pass_rate >= 0.8 else (
        "#fdcb6e" if report.pass_rate >= 0.5 else "#d63031"
    )

    skill_cards_html = []
    for skill in report.skills:
        rows_html = []
        for c in skill.cases:
            reason_html = (
                f'<div class="reason">{c.reason}</div>' if c.reason else ""
            )
            rows_html.append(_ROW.format(
                row_class="pass" if c.passed else "fail",
                case_id=c.case_id,
                description=c.description or "—",
                user_input=c.user_input,
                tool_badges=_tool_badges(c),
                reason_html=reason_html,
                result_class="result-pass" if c.passed else "result-fail",
                result_text="PASS" if c.passed else "FAIL",
                score=c.score,
            ))

        rate_color = "#00b894" if skill.pass_rate >= 0.8 else (
            "#fdcb6e" if skill.pass_rate >= 0.5 else "#d63031"
        )
        skill_cards_html.append(_SKILL_CARD.format(
            skill=skill.skill,
            agent=skill.agent,
            passed=skill.passed,
            total=skill.total,
            rate_color=rate_color,
            rate_pct=f"{skill.pass_rate * 100:.0f}",
            rows="".join(rows_html),
        ))

    return _HTML.format(
        run_at=report.run_at.strftime("%Y-%m-%d %H:%M:%S"),
        model=report.model,
        pass_rate_color=pass_rate_color,
        pass_rate_pct=f"{report.pass_rate * 100:.0f}",
        passed=report.passed,
        failed=report.total - report.passed,
        total=report.total,
        skill_cards="\n".join(skill_cards_html),
    )


def write_report(report: EvalReport, output_dir: str | Path = "sevals/reports") -> Path:
    """渲染并写入 HTML 文件，同时生成带日期的存档版本。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    html = render_report(report)

    latest = out / "latest.html"
    latest.write_text(html, encoding="utf-8")

    dated = out / f"{report.run_at.strftime('%Y-%m-%d_%H-%M-%S')}.html"
    dated.write_text(html, encoding="utf-8")

    return latest
