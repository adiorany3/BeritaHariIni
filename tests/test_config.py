from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import config


class ConfigTests(unittest.TestCase):
    def test_sectioned_streamlit_style_secrets_are_read(self) -> None:
        fake = {
            "jina": {"api_key": "jina-secret", "respond_with": "no-content"},
            "telegram": {"bot_token": "telegram-secret", "allowed_chat_ids": [123, 456]},
            "news": {"enable_rss": True, "max_search_rounds": 2},
        }
        with patch.dict(os.environ, {}, clear=True), patch.object(config, "_combined_secrets", return_value=fake):
            self.assertEqual(config.get_secret("JINA_API_KEY"), "jina-secret")
            self.assertEqual(config.get_secret("TELEGRAM_BOT_TOKEN"), "telegram-secret")
            self.assertEqual(config.get_secret("TELEGRAM_ALLOWED_CHAT_IDS"), "123,456")
            self.assertEqual(config.get_secret("NEWS_ENABLE_RSS"), "1")
            self.assertEqual(config.get_secret_int("NEWS_MAX_SEARCH_ROUNDS", 1), 2)

    def test_environment_takes_precedence_over_secrets(self) -> None:
        fake = {"jina": {"api_key": "from-secret"}}
        with patch.dict(os.environ, {"JINA_API_KEY": "from-env"}, clear=True), patch.object(config, "_combined_secrets", return_value=fake):
            self.assertEqual(config.get_secret("JINA_API_KEY"), "from-env")


    def test_telegram_streamlit_runtime_flags_are_read(self) -> None:
        fake = {"telegram": {"auto_start": True, "delete_webhook_on_start": True, "drop_pending_updates": False}}
        with patch.dict(os.environ, {}, clear=True), patch.object(config, "_combined_secrets", return_value=fake):
            self.assertTrue(config.get_secret_bool("TELEGRAM_AUTO_START", False))
            self.assertTrue(config.get_secret_bool("TELEGRAM_DELETE_WEBHOOK_ON_START", False))
            self.assertFalse(config.get_secret_bool("TELEGRAM_DROP_PENDING_UPDATES", True))

    def test_apply_secrets_to_environment(self) -> None:
        fake = {"telegram": {"token": "telegram-secret"}, "news": {"allow_social": False}}
        with patch.dict(os.environ, {}, clear=True), patch.object(config, "_combined_secrets", return_value=fake):
            config.apply_secrets_to_environment(("TELEGRAM_BOT_TOKEN", "NEWS_ALLOW_SOCIAL"))
            self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "telegram-secret")
            self.assertEqual(os.environ["NEWS_ALLOW_SOCIAL"], "0")


if __name__ == "__main__":
    unittest.main()
