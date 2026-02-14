
import pytest
import os
import json
import asyncio
from typing import Any, List, Dict
from ark_agentic.core.llm import LLMClientProtocol

# Ensure mock environment
os.environ["SECURITIES_SERVICE_MOCK"] = "true"

class SmarterMockLLM(LLMClientProtocol):
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        
        last_msg = messages[-1]
        role = last_msg.get("role")
        content = last_msg.get("content", "")
        
        # 1. User Input -> Tool Call
        if role == "user":
            content_lower = str(content).lower()
            if "asset" in content_lower or "overview" in content_lower:
                # Return OpenAI-format response with tool call
                return {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion",
                    "created": 1677652288,
                    "model": "mock-gpt",
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": "call_mock_123",
                                "type": "function",
                                "function": {
                                    "name": "account_overview",
                                    "arguments": "{}"
                                }
                            }]
                        },
                        "finish_reason": "tool_calls"
                    }],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 10,
                        "total_tokens": 20
                    }
                }
        
        # 2. Tool Output -> Final Answer
        if role == "tool":
            # The tool output is in content
            print(f"Tool Output received: {content}")
            try:
                data = json.loads(content)
                margin_ratio = data.get("margin_ratio")
                
                final_content = "No margin data found."
                if margin_ratio is not None:
                     final_content = f"Margin Ratio is {margin_ratio}"
                
                return {
                    "id": "chatcmpl-mock-2",
                    "object": "chat.completion",
                    "created": 1677652299,
                    "model": "mock-gpt",
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": final_content,
                        },
                        "finish_reason": "stop"
                    }],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "total_tokens": 30
                    }
                }
            except Exception as e:
                print(f"Error parsing tool output in mock LLM: {e}")
                
        return {
            "id": "chatcmpl-mock-error",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "I don't know what to do."
                },
                "finish_reason": "stop"
            }]
        }

@pytest.mark.asyncio
async def test_agent_margin_context_e2e():
    import logging
    logging.basicConfig(level=logging.DEBUG)
    
    from ark_agentic.agents.securities.agent import create_securities_agent
    
    mock_llm = SmarterMockLLM()
    agent = create_securities_agent(llm_client=mock_llm)
    
    # Session setup
    session = await agent.session_manager.create_session()
    # KEY STEP: Inject "margin" context
    agent.session_manager.set_context(session.session_id, "account_type", "margin")
    agent.session_manager.set_context(session.session_id, "user_id", "U001")
    
    # Run
    print("Starting Agent Run...")
    result = await agent.run(
        session_id=session.session_id,
        user_input="Show my asset overview"
    )
    
    # Assert
    print(f"Final Agent Response Content: {result.response.content}")
    assert "Margin Ratio is 2.8" in str(result.response.content)
    print("Integration Test Passed!")

if __name__ == "__main__":
    asyncio.run(test_agent_margin_context_e2e())
