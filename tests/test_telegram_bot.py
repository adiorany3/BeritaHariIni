from __future__ import annotations

import unittest
from threading import Event
from unittest.mock import Mock, patch

from telegram_bot import (
    TelegramNewsBot,
    build_news_messages,
    chat_is_allowed,
    normalise_theme,
    parse_allowed_chat_ids,
)


class TelegramBotTests(unittest.TestCase):
    def test_normalise_theme_keeps_phrase_intact(self) -> None:
        self.assertEqual(normalise_theme("harga telur"), "harga telur")
        self.assertEqual(normalise_theme("/berita harga telur ayam"), "harga telur ayam")
        self.assertEqual(normalise_theme("/cari@BotSaya mobil listrik"), "mobil listrik")
        self.assertEqual(normalise_theme("/start"), "")

    def test_allowed_chat_ids(self) -> None:
        allowed = parse_allowed_chat_ids("123, 456\n789")
        self.assertEqual(allowed, {123, 456, 789})
        self.assertTrue(chat_is_allowed(123, allowed))
        self.assertFalse(chat_is_allowed(111, allowed))
        self.assertTrue(chat_is_allowed(111, set()))

    def test_build_news_messages_contains_title_summary_and_original_link(self) -> None:
        messages = build_news_messages(
            "harga telur",
            [
                {
                    "title": "Harga Telur Ayam Naik di Pasar Jakarta",
                    "scraped_info": "Pedagang menyebut harga telur ayam naik menjadi Rp32.000 per kilogram.",
                    "source": "kompas.com",
                    "published_at": "2026-06-27T12:00:00",
                    "url": "https://www.kompas.com/read/2026/06/27/harga-telur",
                }
            ],
            {"article_scrape_success": "1", "article_scrape_attempted": "1"},
        )
        text = "\n".join(messages)
        self.assertIn("Harga Telur Ayam Naik", text)
        self.assertIn("Rp32.000", text)
        self.assertIn("Baca versi bersih", text)
        self.assertIn("https://r.jina.ai/https://www.kompas.com/read/2026/06/27/harga-telur", text)
        self.assertIn("Buka berita asli", text)
        self.assertIn("https://www.kompas.com/read/2026/06/27/harga-telur", text)


    def test_run_polling_deletes_webhook_before_waiting_for_updates(self) -> None:
        session = Mock()
        session.post.return_value.json.return_value = {"ok": True, "result": []}
        session.post.return_value.raise_for_status = Mock()
        bot = TelegramNewsBot(token="telegram-token", jina_api_key="jina-token", session=session)
        stop_event = Event()
        stop_event.set()

        bot.run_polling(poll_timeout=5, stop_event=stop_event, delete_webhook_on_start=True)

        first_url = session.post.call_args_list[0].args[0]
        first_payload = session.post.call_args_list[0].kwargs["json"]
        self.assertIn("deleteWebhook", first_url)
        self.assertEqual(first_payload, {"drop_pending_updates": False})

    def test_get_me_and_webhook_info_call_safe_telegram_methods(self) -> None:
        session = Mock()
        session.post.return_value.json.return_value = {"ok": True, "result": {"username": "BotSaya"}}
        session.post.return_value.raise_for_status = Mock()
        bot = TelegramNewsBot(token="telegram-token", jina_api_key="jina-token", session=session)

        self.assertEqual(bot.get_me()["result"]["username"], "BotSaya")
        bot.get_webhook_info()

        called_urls = [call.args[0] for call in session.post.call_args_list]
        self.assertTrue(any("getMe" in url for url in called_urls))
        self.assertTrue(any("getWebhookInfo" in url for url in called_urls))

    def test_handle_text_fetches_news_for_theme_and_sends_message(self) -> None:
        session = Mock()
        session.post.return_value.json.return_value = {"ok": True, "result": {}}
        session.post.return_value.raise_for_status = Mock()
        bot = TelegramNewsBot(token="telegram-token", jina_api_key="jina-token", session=session)
        with patch(
            "telegram_bot.fetch_news",
            return_value=(
                [
                    {
                        "title": "Harga Telur Ayam Naik di Pasar Jakarta",
                        "summary": "Harga telur ayam naik menjadi Rp32.000 per kilogram.",
                        "source": "kompas.com",
                        "published_at": "2026-06-27T12:00:00",
                        "url": "https://www.kompas.com/read/2026/06/27/harga-telur",
                    }
                ],
                {"article_scrape_success": "1", "article_scrape_attempted": "1"},
            ),
        ) as mocked_fetch:
            bot.handle_text(123, "harga telur")
        mocked_fetch.assert_called_once()
        _, kwargs = mocked_fetch.call_args
        self.assertEqual(kwargs["query"], "harga telur")
        sent_payloads = [call.kwargs["json"] for call in session.post.call_args_list]
        sent_texts = [payload.get("text", "") for payload in sent_payloads if "text" in payload]
        self.assertTrue(any("Harga Telur Ayam Naik" in text for text in sent_texts))


if __name__ == "__main__":
    unittest.main()
