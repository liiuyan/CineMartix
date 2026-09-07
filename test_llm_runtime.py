#!/usr/bin/env python3
"""LLM 运行时分流的最小单元测试；不会发起真实模型调用。"""

import unittest
from unittest.mock import Mock, patch

import config
from services.codex_runtime import close_codex_runtime
from utils import LLMBrain


class LLMRuntimeRoutingTests(unittest.TestCase):
    def test_codex_mode_routes_to_shared_runtime_without_api_client(self):
        fake_runtime = Mock()
        fake_runtime.think.return_value = "codex-result"

        with (
            patch.object(config.Strategy.System, "LLM_RUNTIME", "codex_sdk"),
            patch(
                "services.codex_runtime.get_codex_runtime",
                return_value=fake_runtime,
            ),
        ):
            brain = LLMBrain()
            result = brain.think("prompt", system_prompt="system")

        self.assertEqual(result, "codex-result")
        self.assertIsNone(brain.client)
        fake_runtime.think.assert_called_once_with("prompt", "system")

    def test_invalid_runtime_is_rejected_without_fallback(self):
        with patch.object(config.Strategy.System, "LLM_RUNTIME", "unknown"):
            with self.assertRaisesRegex(ValueError, "未知 LLM_RUNTIME"):
                LLMBrain()

    def test_api_mode_keeps_existing_deepseek_provider(self):
        with (
            patch.object(config.Strategy.System, "LLM_RUNTIME", "api"),
            patch.object(config.Strategy.System, "LLM_PROVIDER", "deepseek"),
            patch("openai.OpenAI") as openai_client,
        ):
            brain = LLMBrain()

        self.assertEqual(brain.runtime, "api")
        self.assertEqual(brain.provider, "deepseek")
        openai_client.assert_called_once_with(
            api_key=config.LLM_API_KEY,
            base_url=config.LLM_BASE_URL,
        )

    def test_codex_mode_reuses_one_runtime_for_multiple_brains(self):
        close_codex_runtime()
        try:
            with patch.object(config.Strategy.System, "LLM_RUNTIME", "codex_sdk"):
                first = LLMBrain()
                second = LLMBrain()

            self.assertIs(first.codex_runtime, second.codex_runtime)
        finally:
            close_codex_runtime()


if __name__ == "__main__":
    unittest.main()
