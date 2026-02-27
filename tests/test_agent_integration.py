
import pytest
import os
import json
import asyncio
from typing import Any, List, Dict, AsyncIterator

# Ensure mock environment
os.environ["SECURITIES_SERVICE_MOCK"] = "true"


class SmarterMockLLM:
    """Mock LLM that supports both streaming and non-streaming modes."""
    
    def _get_tool_call_response(self) -> Dict[str, Any]:
        """Return response with tool call for account_overview."""
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
    
    def _get_final_response(self, content: str) -> Dict[str, Any]:
        """Return final response with content."""
        return {
            "id": "chatcmpl-mock-2",
            "object": "chat.completion",
            "created": 1677652299,
            "model": "mock-gpt",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30
            }
        }
    
    async def _stream_response(self, response: Dict[str, Any]) -> AsyncIterator[Dict[str, Any]]:
        """Yield chunks for streaming mode."""
        # First chunk: role and maybe tool_calls start
        yield {
            "id": response["id"],
            "object": "chat.completion.chunk",
            "created": response["created"],
            "model": response["model"],
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": None
            }]
        }
        
        message = response["choices"][0]["message"]
        
        # Stream content if present
        if message.get("content"):
            yield {
                "id": response["id"],
                "object": "chat.completion.chunk",
                "created": response["created"],
                "model": response["model"],
                "choices": [{
                    "index": 0,
                    "delta": {"content": message["content"]},
                    "finish_reason": None
                }]
            }
        
        # Stream tool_calls if present
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                yield {
                    "id": response["id"],
                    "object": "chat.completion.chunk",
                    "created": response["created"],
                    "model": response["model"],
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "tool_calls": [{
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["function"]["name"],
                                    "arguments": tc["function"]["arguments"]
                                }
                            }]
                        },
                        "finish_reason": None
                    }]
                }
        
        # Final chunk with finish_reason
        yield {
            "id": response["id"],
            "object": "chat.completion.chunk",
            "created": response["created"],
            "model": response["model"],
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": response["choices"][0]["finish_reason"]
            }]
        }

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any] | AsyncIterator[Dict[str, Any]]:
        
        last_msg = messages[-1]
        role = last_msg.get("role")
        content = last_msg.get("content", "")
        
        response = None
        
        # 1. User Input -> Tool Call
        if role == "user":
            content_lower = str(content).lower()
            if "asset" in content_lower or "overview" in content_lower:
                response = self._get_tool_call_response()
        
        # 2. Tool Output -> Final Answer
        elif role == "tool":
            print(f"Tool Output received: {content}")
            try:
                data = json.loads(content)
                # 适配真实 API 数据格式: results.rmb.rzrqAssetsInfo.mainRatio
                main_ratio = None
                if data.get("status") == 1:  # 真实 API 格式
                    results = data.get("results", {})
                    rmb = results.get("rmb", {})
                    rzrq = rmb.get("rzrqAssetsInfo", {})
                    main_ratio = rzrq.get("mainRatio")
                else:  # 旧格式兼容
                    main_ratio = data.get("margin_ratio")
                
                final_content = "No margin data found."
                if main_ratio is not None:
                     final_content = f"Margin Ratio is {main_ratio}"
                
                response = self._get_final_response(final_content)
            except Exception as e:
                print(f"Error parsing tool output in mock LLM: {e}")
                response = self._get_final_response("I don't know what to do.")
        
        # Default fallback
        if response is None:
            response = {
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
        
        # Return stream or dict based on mode
        if stream:
            return self._stream_response(response)
        return response

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
    # 真实 API 返回的 mainRatio 值是 "35291.35"
    assert "Margin Ratio is 35291.35" in str(result.response.content)
    print("Integration Test Passed!")

if __name__ == "__main__":
    asyncio.run(test_agent_margin_context_e2e())
