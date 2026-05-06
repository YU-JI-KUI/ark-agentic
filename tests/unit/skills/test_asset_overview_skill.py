"""
测试 asset_overview 技能

运行方式:
    SECURITIES_SERVICE_MOCK=true uv run python tests/skills/test_asset_overview_skill.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from unittest.mock import patch

from ark_agentic.agents.securities import SecuritiesAgent
from ark_agentic.core.llm import create_chat_model


async def run_eval(agent, prompt: str, eval_name: str, with_skill: bool):
    """运行单个评估"""
    session_id = await agent.create_session()

    if not with_skill:
        agent.skill_loader = None

    try:
        result = await agent.run(session_id, prompt)
        return {
            "prompt": prompt,
            "response": result.get("response", ""),
            "tool_calls": result.get("tool_calls", []),
            "session_id": session_id,
        }
    except Exception as e:
        return {
            "prompt": prompt,
            "error": str(e),
            "session_id": session_id,
        }


async def main():
    os.environ["SECURITIES_SERVICE_MOCK"] = "true"

    evals = [
        {"id": 1, "name": "simple-view", "prompt": "查看我的账户资产"},
        {
            "id": 2,
            "name": "analyze-loss",
            "prompt": "帮我分析一下我的资产情况，看看为什么最近一直在亏损",
        },
        {
            "id": 3,
            "name": "margin-account",
            "prompt": "我的两融账户现在风险怎么样？担保比率多少？",
        },
        {"id": 4, "name": "implicit-intent", "prompt": "我有多少钱？"},
    ]

    workspace = Path(__file__).parent / "asset_overview-workspace" / "iteration-1"

    print("创建 Agent...")
    llm = create_chat_model("deepseek-chat")
    with patch.object(SecuritiesAgent, "build_llm", return_value=llm):
        agent = SecuritiesAgent()

    print(f"\n运行 {len(evals)} 个评估...\n")

    for eval_item in evals:
        eval_name = eval_item["name"]
        prompt = eval_item["prompt"]

        print(f"=== {eval_name} ===")
        print(f"Prompt: {prompt}")

        for config in ["with_skill", "without_skill"]:
            output_dir = workspace / f"eval-{eval_name}" / config / "outputs"
            output_dir.mkdir(parents=True, exist_ok=True)

            print(f"  [{config}] 运行中...")
            result = await run_eval(agent, prompt, eval_name, config == "with_skill")

            output_file = output_dir / "output.txt"
            with open(output_file, "w", encoding="utf-8") as f:
                if "error" in result:
                    f.write(f"ERROR: {result['error']}\n")
                else:
                    f.write(result.get("response", ""))

            tool_file = output_dir / "tool_calls.json"
            with open(tool_file, "w", encoding="utf-8") as f:
                json.dump(result.get("tool_calls", []), f, ensure_ascii=False, indent=2)

            print(f"  [{config}] 完成 -> {output_file}")

        print()

    print("评估完成！")


if __name__ == "__main__":
    asyncio.run(main())
