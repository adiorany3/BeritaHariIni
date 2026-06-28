from __future__ import annotations

import os
import tempfile
import unittest
import requests
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from telegram_bot import (
    TelegramNewsBot,
    TelegramPollingConflict,
    TelegramUpdateDeduper,
    build_news_messages,
    chat_is_allowed,
    normalise_theme,
    parse_allowed_chat_ids,
    redact_sensitive,
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
        self.assertIn("Buka teks bersih (TXT)", text)
        self.assertIn("https://beritaterbaru.streamlit.app?reader=https%3A%2F%2Fwww.kompas.com%2Fread%2F2026%2F06%2F27%2Fharga-telur", text)
        self.assertNotIn("https://r.jina.ai/https://www.kompas.com/read/2026/06/27/harga-telur", text)
        self.assertIn("Buka berita asli", text)
        self.assertIn("https://www.kompas.com/read/2026/06/27/harga-telur", text)

    def test_build_news_messages_uses_streamlit_text_reader_when_app_url_configured(self) -> None:
        with patch.dict(os.environ, {"STREAMLIT_APP_URL": "https://berita-demo.streamlit.app"}, clear=False):
            messages = build_news_messages(
                "ai gambar",
                [
                    {
                        "title": "Startup AI Gambar Rilis Fitur Baru",
                        "scraped_info": "Perusahaan merilis fitur baru untuk membuat gambar dari teks.",
                        "source": "contoh.id",
                        "published_at": "2026-06-27T12:00:00",
                        "url": "https://contoh.id/ai-gambar",
                    }
                ],
                {"article_scrape_success": "1", "article_scrape_attempted": "1"},
            )
        text = "\n".join(messages)
        self.assertIn("Buka teks bersih (TXT)", text)
        self.assertIn("https://berita-demo.streamlit.app?reader=https%3A%2F%2Fcontoh.id%2Fai-gambar", text)
        self.assertIn("Buka berita asli", text)

    def test_build_news_messages_uses_telegram_specific_text_reader_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "STREAMLIT_APP_URL": "https://dashboard.example.com",
                "TELEGRAM_TEXT_READER_APP_URL": "https://reader.example.com",
            },
            clear=False,
        ):
            messages = build_news_messages(
                "ai gambar",
                [
                    {
                        "title": "Startup AI Gambar Rilis Fitur Baru",
                        "scraped_info": "Perusahaan merilis fitur baru untuk membuat gambar dari teks.",
                        "source": "contoh.id",
                        "published_at": "2026-06-27T12:00:00",
                        "url": "https://contoh.id/ai-gambar",
                    }
                ],
                {"article_scrape_success": "1", "article_scrape_attempted": "1"},
            )
        text = "\n".join(messages)
        self.assertIn("Buka teks bersih (TXT)", text)
        self.assertIn("https://reader.example.com?reader=https%3A%2F%2Fcontoh.id%2Fai-gambar", text)
        self.assertNotIn("https://dashboard.example.com?reader=", text)
        self.assertNotIn("https://r.jina.ai/", text)


    def test_build_news_messages_accepts_app_url_alias_without_scheme(self) -> None:
        with patch.dict(os.environ, {"APP_URL": "beritaterbaru.streamlit.app/"}, clear=False):
            messages = build_news_messages(
                "ai gambar",
                [
                    {
                        "title": "Startup AI Gambar Rilis Fitur Baru",
                        "scraped_info": "Perusahaan merilis fitur baru untuk membuat gambar dari teks.",
                        "source": "contoh.id",
                        "published_at": "2026-06-27T12:00:00",
                        "url": "https://contoh.id/ai-gambar",
                    }
                ],
                {"article_scrape_success": "1", "article_scrape_attempted": "1"},
            )
        text = "\n".join(messages)
        self.assertIn("https://beritaterbaru.streamlit.app?reader=https%3A%2F%2Fcontoh.id%2Fai-gambar", text)
        self.assertNotIn("https://beritaterbaru.streamlit.app/?reader=", text)

    def test_build_news_messages_uses_scraped_content_only_not_serp_summary(self) -> None:
        messages = build_news_messages(
            "ai gambar",
            [
                {
                    "title": "Startup AI Gambar Rilis Fitur Baru",
                    "summary": "Deskripsi dari SERP yang tidak boleh jadi konten utama.",
                    "scraped_info": "",
                    "source": "contoh.id",
                    "published_at": "2026-06-27T12:00:00",
                    "url": "https://contoh.id/ai-gambar",
                }
            ],
            {"article_scrape_success": "0", "article_scrape_attempted": "1"},
        )
        text = "\n".join(messages)
        self.assertNotIn("Deskripsi dari SERP", text)
        self.assertIn("Konten artikel belum berhasil di-scrape", text)
        self.assertIn("Buka teks bersih (TXT)", text)
        self.assertIn("https://beritaterbaru.streamlit.app?reader=https%3A%2F%2Fcontoh.id%2Fai-gambar", text)
        self.assertIn("Buka berita asli", text)




    def test_redact_sensitive_removes_telegram_token_from_error_url(self) -> None:
        leaked = "409 Client Error: Conflict for url: https://api.telegram.org/bot123456:ABC_def-GHI/getUpdates"
        safe = redact_sensitive(leaked)
        self.assertIn("bot<REDACTED>", safe)
        self.assertNotIn("123456:ABC_def-GHI", safe)
        self.assertNotIn("https://api.telegram.org/bot123456", safe)

    def test_get_updates_409_conflict_raises_safe_message_without_token(self) -> None:
        response = requests.Response()
        response.status_code = 409
        response.url = "https://api.telegram.org/bot123456:ABC_def-GHI/getUpdates"
        error = requests.HTTPError(
            "409 Client Error: Conflict for url: https://api.telegram.org/bot123456:ABC_def-GHI/getUpdates",
            response=response,
        )
        session = Mock()
        session.post.return_value.raise_for_status.side_effect = error
        bot = TelegramNewsBot(token="123456:ABC_def-GHI", jina_api_key="jina-token", session=session)

        with self.assertRaises(TelegramPollingConflict) as ctx:
            bot.get_updates(None, 5)

        message = str(ctx.exception)
        self.assertIn("instance bot lain", message)
        self.assertNotIn("123456:ABC_def-GHI", message)
        self.assertNotIn("api.telegram.org/bot", message)

    def test_run_polling_409_conflict_reports_once_and_stops_without_token(self) -> None:
        response = requests.Response()
        response.status_code = 409
        response.url = "https://api.telegram.org/bot123456:ABC_def-GHI/getUpdates"
        error = requests.HTTPError(
            "409 Client Error: Conflict for url: https://api.telegram.org/bot123456:ABC_def-GHI/getUpdates",
            response=response,
        )
        session = Mock()
        session.post.return_value.raise_for_status.side_effect = error
        bot = TelegramNewsBot(token="123456:ABC_def-GHI", jina_api_key="jina-token", session=session)
        events: list[tuple[str, str]] = []

        bot.run_polling(
            poll_timeout=5,
            delete_webhook_on_start=False,
            status_callback=lambda event, message: events.append((event, message)),
        )

        self.assertEqual(session.post.call_count, 1)
        self.assertTrue(any(event == "conflict" for event, _ in events))
        joined = "\n".join(message for _, message in events)
        self.assertIn("instance bot lain", joined)
        self.assertNotIn("123456:ABC_def-GHI", joined)
        self.assertNotIn("api.telegram.org/bot", joined)

    def test_update_deduper_claims_message_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "telegram_updates_state.json"
            deduper = TelegramUpdateDeduper(state_path)
            update = {
                "update_id": 10,
                "message": {"message_id": 20, "chat": {"id": 123}, "text": "harga telur"},
            }
            self.assertTrue(deduper.claim(update))
            self.assertFalse(deduper.claim(update))

    def test_handle_update_skips_duplicate_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            session = Mock()
            session.post.return_value.json.return_value = {"ok": True, "result": {}}
            session.post.return_value.raise_for_status = Mock()
            bot = TelegramNewsBot(
                token="telegram-token",
                jina_api_key="jina-token",
                session=session,
                update_state_path=Path(tmpdir) / "updates.json",
            )
            update = {
                "update_id": 100,
                "message": {"message_id": 5, "chat": {"id": 123}, "text": "/help"},
            }
            self.assertTrue(bot.handle_update(update))
            self.assertFalse(bot.handle_update(update))
            send_calls = [call for call in session.post.call_args_list if "sendMessage" in call.args[0]]
            self.assertEqual(len(send_calls), 1)

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
