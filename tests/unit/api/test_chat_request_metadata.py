"""Chat request metadata invariants.

build_chat_request_meta was inlined into the /chat handler in
ark_agentic/plugins/api/chat.py. The propagation of meta:chat_request
through the runner is covered by tests/unit/core/test_runner_metadata.py
(test_user_message_carries_chat_request_*).
"""
