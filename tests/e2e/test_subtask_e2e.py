"""E2E test for spawn_subtasks tool — bypasses LLM trigger decision.

Manually constructs a ToolCall and calls SpawnSubtasksTool.execute() directly.
Sub-runners still go through real LLM + mock data service.

Prerequisites:
    - API_KEY, MODEL_NAME, LLM_PROVIDER env vars set
    - DATA_SERVICE_MOCK=true (auto-set below as fallback)

Usage:
    uv run python scripts/test_subtask_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

os.environ.setdefault("DATA_SERVICE_MOCK", "true")

from ark_agentic.agents.insurance import create_insurance_agent
from ark_agentic.core.types import ToolCall

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Creating insurance agent with enable_subtasks=True ...")
    agent = create_insurance_agent()

    if not agent.tool_registry.has("spawn_subtasks"):
        logger.error("spawn_subtasks not registered — check enable_subtasks in RunnerConfig")
        sys.exit(1)

    logger.info("Tools: %s", agent.tool_registry.list_names())

    session = await agent.session_manager.create_session(
        user_id="test_user_001",
        state={"user:id": "test_user_001", "user:name": "张三"},
    )
    sid = session.session_id
    logger.info("Parent session: %s", sid)

    tc = ToolCall.create("spawn_subtasks", {
        "tasks": [
            {"task": "查询客户 test_user_001 的基本信息", "label": "客户信息"},
            {"task": "查询客户 test_user_001 名下保单列表及可取款额度", "label": "保单取款"},
        ],
    })

    logger.info("Calling spawn_subtasks.execute() ...")
    tool = agent.tool_registry.get_required("spawn_subtasks")
    result = await tool.execute(tc, {"session_id": sid})

    print("\n===== SUBTASK RESULTS =====")
    for sub in result.content.get("subtasks", []):
        print(f"\n[{sub.get('label', '?')}] status={sub.get('status')}")
        answer = sub.get("result", "")
        print(f"  result: {answer[:300]}{'...' if len(answer) > 300 else ''}")
        if sub.get("execution"):
            print(f"  execution: {json.dumps(sub['execution'], ensure_ascii=False)}")

    print("\n===== METADATA =====")
    if result.metadata:
        print(f"  keys: {list(result.metadata.keys())}")
        if "state_delta" in result.metadata:
            print(f"  state_delta: {result.metadata['state_delta']}")
        if "transcripts" in result.metadata:
            for label, transcript in result.metadata["transcripts"].items():
                print(f"  transcript[{label}]: {len(transcript)} messages")
    else:
        print("  (none)")

    print("\n===== PARENT SESSION =====")
    print(f"  token_usage: {session.token_usage}")
    print()
    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
