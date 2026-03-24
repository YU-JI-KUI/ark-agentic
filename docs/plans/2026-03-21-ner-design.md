# NER Tool Integration (UIE-mini)

## Overview
Add a tool-based NER capability to ark-agentic using the UIE-mini PyTorch model (ported from pingan). The tool will be callable by the LLM to extract entities on demand. It will not mutate session state automatically; instead it returns structured entities for the caller to use (e.g., prompt context or downstream tool parameters).

## Key Approach
- Implement a first-class `AgentTool` named `ner.extract`.
- Wrap UIE-mini PyTorch model loading and inference inside the tool.
- Register the tool in agent factories (insurance and securities) so it is available to the LLM.
- Keep the interface schema-driven and configurable, with a default schema in config.

## Architecture
- **Tool**: `src/ark_agentic/core/tools/ner.py`
  - Handles model loading, schema parsing, inference, and response formatting.
- **Model wrapper**: UIE-mini inference code adapted from pingan’s `TorchUIEMiner`.
- **Registration**: add `NERTool` to `ToolRegistry` in `agents/insurance/agent.py` and `agents/securities/agent.py`.

## Data Flow
1. LLM calls `ner.extract` with `{ text, schema? }`.
2. Tool runs UIE-mini with provided or default schema.
3. Tool returns `{ entities: [{ label, text, start, end, score }] }`.
4. Agent decides how to use results (e.g., inject into context or pass to other tools).

## Configuration
- Add NER config in agent settings:
  - model path
  - device (cpu/cuda)
  - default schema (list of labels)
  - optional confidence threshold
- Model loads lazily on first call and is cached.

## Error Handling
- If model fails to load or inference errors occur, return a structured error payload and allow the agent to continue without NER.
- If schema is missing, fall back to default schema.

## Testing
- Unit tests for tool invocation and schema handling.
- Registration tests to ensure NER tool is included in agent factories.

## Open Questions
- Should we support domain-specific schemas per agent as overrides?
- Should we add a lightweight LLM fallback when the model is unavailable?
