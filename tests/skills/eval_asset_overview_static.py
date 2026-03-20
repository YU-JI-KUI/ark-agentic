"""
静态评估 asset_overview 技能 (重构后版本)

评估技能的:
1. 技能结构完整性
2. 意图模型清晰度
3. 路由边界定义
4. 工具契约明确性
5. 执行流程清晰度
6. 输出策略
7. 错误处理覆盖
"""

import json
from pathlib import Path

SKILL_PATH = (
    Path(__file__).parent.parent.parent
    / "src/ark_agentic/agents/securities/skills/asset_overview/SKILL.md"
)


def read_skill():
    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        return f.read()


def check_frontmatter(content: str) -> dict:
    results = {"passed": 0, "failed": 0, "items": []}

    lines = content.split("\n")
    in_frontmatter = False
    frontmatter_lines = []

    for line in lines:
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter:
            frontmatter_lines.append(line)

    frontmatter_text = "\n".join(frontmatter_lines)

    checks = [
        ("name 字段", "name:" in frontmatter_text),
        ("description 字段", "description:" in frontmatter_text),
        ("required_tools 字段", "required_tools:" in frontmatter_text),
        ("group 字段", "group:" in frontmatter_text),
    ]

    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        results["items"].append(f"  {status} {check_name}")
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


def check_skill_structure(content: str) -> dict:
    results = {"passed": 0, "failed": 0, "items": []}

    required_sections = [
        ("技能目标", "技能目标"),
        ("意图模型", "意图模型"),
        ("工具契约", "工具契约"),
        ("执行流程", "执行流程"),
        ("输出策略", "输出策略"),
        ("错误处理", "错误处理"),
    ]

    for section_name, keyword in required_sections:
        found = keyword in content
        status = "✓" if found else "✗"
        results["items"].append(f"  {status} 包含 {section_name} 章节")
        if found:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


def check_intent_model(content: str) -> dict:
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("定义 account_type 枚举", "account_type:" in content and "NORMAL" in content),
        ("定义 mode 枚举", "mode:" in content),
        ("定义 MODE_CARD", "MODE_CARD" in content),
        ("定义 MODE_TEXT", "MODE_TEXT" in content),
        ("包含默认推断规则", "默认推断规则" in content),
    ]

    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        results["items"].append(f"  {status} {check_name}")
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


def check_routing_boundary(content: str) -> dict:
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("定义路由边界", "路由边界" in content),
        ("指向 holdings_analysis", "holdings_analysis" in content),
        ("指向 profit_inquiry", "profit_inquiry" in content),
        ("包含跳转提示", "跳转" in content),
    ]

    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        results["items"].append(f"  {status} {check_name}")
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


def check_tool_references(content: str) -> dict:
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("引用 account_overview 工具", "account_overview" in content),
        ("引用 display_card 工具", "display_card" in content),
        ("工具调用顺序约束", "必须在" in content),
        ("display_card 调用示例", "display_card(source_tool=" in content),
    ]

    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        results["items"].append(f"  {status} {check_name}")
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


def check_execution_flow(content: str) -> dict:
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("定义 STEP_1_INTENT_PARSE", "STEP_1_INTENT_PARSE" in content),
        ("定义 STEP_2_FETCH_DATA", "STEP_2_FETCH_DATA" in content),
        ("定义 MODE_CARD 分支", "MODE_CARD" in content and "触发条件" in content),
        ("定义 MODE_TEXT 分支", "MODE_TEXT" in content),
        ("包含流程图", "STEP_1" in content and "↓" in content),
    ]

    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        results["items"].append(f"  {status} {check_name}")
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


def check_output_strategy(content: str) -> dict:
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("MODE_CARD 字数限制(≤30字)", "≤30字" in content),
        ("MODE_TEXT 字数限制(≤200字)", "≤200字" in content),
        (
            "MODE_TEXT 禁止 display_card",
            "MODE_TEXT" in content and "禁止调用 display_card" in content,
        ),
        ("包含普通账户示例", "普通账户" in content and "示例" in content),
        ("包含两融账户示例", "两融账户" in content and "示例" in content),
    ]

    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        results["items"].append(f"  {status} {check_name}")
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


def check_error_handling(content: str) -> dict:
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("工具不可用处理", "工具不可用" in content),
        ("数据为空处理", "数据为空" in content),
        ("超时处理", "超时" in content),
        ("部分失败处理", "部分失败" in content),
    ]

    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        results["items"].append(f"  {status} {check_name}")
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


def check_constraints(content: str) -> dict:
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("禁止使用历史数据", "历史" in content and "禁止" in content),
        ("禁止提供投资建议", "投资建议" in content and "禁止" in content),
        ("禁止泄露原始数据", "原始" in content),
        ("实时调用工具约束", "实时调用" in content or "必须每次" in content),
    ]

    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        results["items"].append(f"  {status} {check_name}")
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


def check_margin_support(content: str) -> dict:
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("识别两融账户类型", "MARGIN" in content),
        ("维持担保比率指标", "担保比率" in content),
        ("风险等级展示", "风险等级" in content),
        ("净资产/总负债指标", "净资产" in content or "总负债" in content),
    ]

    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        results["items"].append(f"  {status} {check_name}")
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    return results


def main():
    print("=" * 60)
    print("asset_overview 技能静态评估 (重构后版本)")
    print("=" * 60)
    print()

    content = read_skill()

    categories = [
        ("Frontmatter 完整性", check_frontmatter),
        ("技能结构", check_skill_structure),
        ("意图模型", check_intent_model),
        ("路由边界定义", check_routing_boundary),
        ("工具引用", check_tool_references),
        ("执行流程", check_execution_flow),
        ("输出策略", check_output_strategy),
        ("错误处理", check_error_handling),
        ("约束条件", check_constraints),
        ("两融账户支持", check_margin_support),
    ]

    total_passed = 0
    total_failed = 0

    for category_name, check_func in categories:
        result = check_func(content)
        total_passed += result["passed"]
        total_failed += result["failed"]

        print(f"### {category_name}")
        print(f"通过: {result['passed']}/{result['passed'] + result['failed']}")
        for item in result["items"]:
            print(item)
        print()

    print("=" * 60)
    print(f"总计: {total_passed} 通过, {total_failed} 失败")
    print(f"通过率: {total_passed / (total_passed + total_failed) * 100:.1f}%")
    print("=" * 60)

    benchmark = {
        "metadata": {
            "skill_name": "asset_overview",
            "skill_path": str(SKILL_PATH),
            "eval_type": "static",
            "version": "refactored",
        },
        "summary": {
            "total_passed": total_passed,
            "total_failed": total_failed,
            "pass_rate": total_passed / (total_passed + total_failed),
        },
    }

    output_path = (
        Path(__file__).parent
        / "asset_overview-workspace"
        / "iteration-2"
        / "static_benchmark.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(benchmark, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
