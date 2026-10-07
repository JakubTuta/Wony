"""Claude's replies travel back into the tool loop unchanged. Rebuilding them
from the tool calls alone dropped the thinking blocks Anthropic requires back,
which is why thinking was off for every turn.

Run directly: python tests/test_model_messages.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _reply():
    import anthropic

    return anthropic.types.Message.model_validate({
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5",
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "content": [
            {"type": "thinking", "thinking": "Need the weather first.", "signature": "sig"},
            {"type": "tool_use", "id": "toolu_1", "name": "weather", "input": {"city": "Oslo"}},
        ],
    })


class TestRawRepliesReplay(unittest.TestCase):
    def test_the_thinking_block_goes_back_with_the_call(self) -> None:
        from helpers import model

        calls = model._anthropic_tool_calls(_reply())
        self.assertEqual(calls[0]["name"], "weather")

        neutral = [
            {"role": "user", "content": "weather?"},
            {"role": "tool_call", **calls[0]},
            {"role": "tool_result", "id": "toolu_1", "name": "weather", "content": "Sunny."},
        ]
        converted = model._to_anthropic_messages(neutral)
        assistant = converted[1]["content"]
        self.assertEqual([block.type for block in assistant], ["thinking", "tool_use"])
        self.assertEqual(converted[2]["content"][0]["tool_use_id"], "toolu_1")

    def test_a_call_without_a_raw_reply_is_still_rebuilt(self) -> None:
        from helpers import model

        converted = model._to_anthropic_messages([
            {"role": "user", "content": "x"},
            {"role": "tool_call", "id": "t1", "name": "weather", "args": {}},
            {"role": "tool_result", "id": "t1", "name": "weather", "content": "ok"},
        ])
        self.assertEqual(converted[1]["content"][0]["type"], "tool_use")


class TestThinkingChoice(unittest.TestCase):
    def test_spoken_turns_do_not_think_typed_ones_do(self) -> None:
        import anthropic

        from helpers import model

        self.assertIs(model._anthropic_thinking(True, "claude-haiku-4-5", think=False), anthropic.NOT_GIVEN)
        budget = model._anthropic_thinking(True, "claude-haiku-4-5", think=True)
        self.assertEqual(budget["type"], "enabled")
        self.assertLess(budget["budget_tokens"], model._MAX_TOKENS)
        self.assertEqual(model._anthropic_thinking(True, "claude-sonnet-5-5", think=True), {"type": "adaptive"})


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
