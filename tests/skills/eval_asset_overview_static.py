"""
静态评估 asset_overview 技能

评估技能的:
1. 技能结构完整性
2. 描述触发准确性
3. 工具契约明确性
4. 状态机清晰度
5. 错误处理覆盖
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
    """检查 frontmatter 完整性"""
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
    """检查技能结构"""
    results = {"passed": 0, "failed": 0, "items": []}

    required_sections = [
        ("技能目标", "技能目标"),
        ("用户意图识别", "用户意图识别"),
        ("工具契约", "工具契约"),
        ("执行状态机", "执行状态机"),
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


def check_tool_references(content: str) -> dict:
    """检查工具引用"""
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("引用 account_overview 工具", "account_overview" in content),
        ("引用 display_card 工具", "display_card" in content),
        ("工具调用格式正确", "account_overview()" in content),
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


def check_state_machine(content: str) -> dict:
    """检查状态机定义"""
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("定义 STATE_1_INTENT_PARSE", "STATE_1_INTENT_PARSE" in content),
        ("定义 STATE_2_FETCH_DATA", "STATE_2_FETCH_DATA" in content),
        ("定义 STATE_3_ANALYSIS", "STATE_3_ANALYSIS" in content),
        ("定义 STATE_4_CARD_DISPLAY", "STATE_4_CARD_DISPLAY" in content),
        ("包含状态转换图", "STATE_1" in content and "→" in content or "↓" in content),
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
    """检查错误处理"""
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("工具不可用处理", "工具不可用" in content),
        ("数据为空处理", "数据为空" in content),
        ("超时处理", "超时" in content),
        ("部分失败处理", "部分" in content and "失败" in content),
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
    """检查约束条件"""
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("禁止使用历史数据", "历史" in content and "禁止" in content),
        ("禁止提供投资建议", "投资建议" in content and "禁止" in content),
        ("禁止泄露原始 JSON", "原始 JSON" in content or "原始数据" in content),
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
    """检查两融账户支持"""
    results = {"passed": 0, "failed": 0, "items": []}

    checks = [
        ("识别两融账户类型", "MARGIN" in content),
        ("维持担保比率指标", "担保比率" in content or "维持担保" in content),
        ("风险等级展示", "风险等级" in content),
        ("保证金相关指标", "保证金" in content),
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
    print("asset_overview 技能静态评估")
    print("=" * 60)
    print()

    content = read_skill()

    categories = [
        ("Frontmatter 完整性", check_frontmatter),
        ("技能结构", check_skill_structure),
        ("工具引用", check_tool_references),
        ("状态机定义", check_state_machine),
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
        },
        "summary": {
            "total_passed": total_passed,
            "total_failed": total_failed,
            "pass_rate": total_passed / (total_passed + total_failed),
        },
    }

    output_path = (
        Path(__file__).parent / "asset_overview-workspace" / "static_benchmark.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(benchmark, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
