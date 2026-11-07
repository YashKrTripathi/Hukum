import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("HUKUM_DB", ":memory:")

import phone_agent  # noqa: E402


class PhoneAgentTests(unittest.TestCase):
    def test_parse_valid_and_invalid(self):
        self.assertEqual(phone_agent._parse('sure {"action":"click","index":"4","say":"tapping install"}')["index"], 4)
        self.assertEqual(phone_agent._parse('{"action":"type","index":2,"text":"t series"}')["text"], "t series")
        self.assertEqual(phone_agent._parse("no json here")["action"], "fail")
        self.assertEqual(phone_agent._parse('{"action":"format_disk"}')["action"], "fail")

    def test_step_uses_model_and_survives_errors(self):
        with mock.patch.object(phone_agent.llm, "available", return_value=True), \
             mock.patch.object(phone_agent.llm, "chat_raw", return_value={"content": '{"action":"done","say":"installed"}'}):
            self.assertEqual(phone_agent.step("install instagram", '[1] button "Open"', [])["action"], "done")
        with mock.patch.object(phone_agent.llm, "available", return_value=True), \
             mock.patch.object(phone_agent.llm, "chat_raw", side_effect=RuntimeError("down")):
            self.assertEqual(phone_agent.step("x", "", [])["action"], "fail")
        with mock.patch.object(phone_agent.llm, "available", return_value=False):
            self.assertEqual(phone_agent.step("x", "", [])["action"], "fail")


if __name__ == "__main__":
    unittest.main()
