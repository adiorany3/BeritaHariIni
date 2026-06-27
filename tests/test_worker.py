from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

import worker


class WorkerBroadcastTests(unittest.TestCase):
    def test_broadcast_chat_ids_prefers_broadcast_then_fallback_allowed(self) -> None:
        with patch.dict(os.environ, {"TELEGRAM_BROADCAST_CHAT_IDS": "100,200", "TELEGRAM_ALLOWED_CHAT_IDS": "300"}, clear=True):
            self.assertEqual(worker._broadcast_chat_ids(), {100, 200})
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_CHAT_IDS": "300"}, clear=True):
            self.assertEqual(worker._broadcast_chat_ids(), {300})

    def test_send_morning_digest_sends_title_summary_and_link_to_each_chat(self) -> None:
        fake_bot = Mock()
        with patch("worker.TelegramNewsBot", return_value=fake_bot) as bot_class:
            sent = worker.send_morning_digest(
                token="telegram-token",
                jina_api_key="jina-key",
                chat_ids={111, 222},
                theme="Berita terbaru pagi ini",
                articles=[
                    {
                        "title": "Harga Telur Ayam Naik",
                        "scraped_info": "Harga telur ayam naik menjadi Rp32.000 per kilogram.",
                        "source": "kompas.com",
                        "published_at": "2026-06-27T07:00:00+07:00",
                        "url": "https://www.kompas.com/read/harga-telur",
                    }
                ],
                metadata={"article_scrape_success": "1", "article_scrape_attempted": "1"},
                limit=5,
                request_timeout=25,
            )
        self.assertEqual(sent, 2)
        bot_class.assert_called_once()
        self.assertEqual(fake_bot.send_message.call_count, 2)
        sent_payload = fake_bot.send_message.call_args_list[0].args[1]
        self.assertIn("Berita terbaru pagi ini", sent_payload)
        self.assertIn("Harga Telur Ayam Naik", sent_payload)
        self.assertIn("Rp32.000", sent_payload)
        self.assertIn("Buka teks saja", sent_payload)
        self.assertIn("https://r.jina.ai/https://www.kompas.com/read/harga-telur", sent_payload)
        self.assertIn("Buka berita asli", sent_payload)

    def test_main_requires_telegram_when_flag_enabled(self) -> None:
        with patch.dict(os.environ, {"WORKER_REQUIRE_TELEGRAM": "1", "WORKER_SEND_TELEGRAM": "0"}, clear=True), \
             patch("worker.fetch_news", return_value=([], {})), \
             patch("worker.read_json", return_value={"articles": []}), \
             patch("worker.write_json"):
            with self.assertRaises(RuntimeError):
                worker.main()


if __name__ == "__main__":
    unittest.main()
