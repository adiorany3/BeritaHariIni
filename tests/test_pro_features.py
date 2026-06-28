from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import worker
from news_service import enrich_validity_and_structure, structured_extraction
from telegram_bot import (
    add_subscription_topic,
    get_chat_subscription,
    list_subscription_targets,
    remove_subscription_topic,
    set_subscription_limit,
    TelegramNewsBot,
)


class ProFeatureTests(unittest.TestCase):
    def test_structured_extraction_for_harga_telur_finds_price_and_trend(self) -> None:
        article = {
            "title": "Harga Telur Ayam Naik di Pasar Jakarta",
            "scraped_info": "Harga telur ayam di Jakarta naik menjadi Rp32.000/kg karena pasokan berkurang.",
        }
        info = structured_extraction(article, query="harga telur")
        self.assertEqual(info["type"], "harga_pangan")
        joined = " ".join(info["highlights"])
        self.assertIn("Rp32.000/kg", joined)
        self.assertIn("naik", joined)

    def test_validity_and_event_dedupe_add_supporting_sources(self) -> None:
        articles = [
            {
                "title": "Harga Telur Ayam Naik di Pasar Jakarta",
                "url": "https://www.kompas.com/read/2026/06/27/harga-telur-jakarta",
                "source": "kompas.com",
                "time_status": "verified_today",
                "quality_score": 90,
                "scraped_info": "Harga telur ayam di Jakarta naik menjadi Rp32.000/kg.",
            },
            {
                "title": "Harga Telur Ayam Naik di Pasar Jakarta Hari Ini",
                "url": "https://www.detik.com/read/2026/06/27/harga-telur-jakarta",
                "source": "detik.com",
                "time_status": "verified_today",
                "quality_score": 85,
                "scraped_info": "Harga telur ayam di Jakarta naik menjadi Rp32.000/kg.",
            },
        ]
        enriched = enrich_validity_and_structure(articles, query="harga telur")
        self.assertEqual(len(enriched), 1)
        self.assertGreaterEqual(enriched[0]["supporting_source_count"], 2)
        self.assertIn("validity_score", enriched[0])
        self.assertIn("structured_info", enriched[0])

    def test_subscription_state_add_remove_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subscriptions.json"
            added, topics = add_subscription_topic(123, "harga telur", path=path)
            self.assertTrue(added)
            self.assertEqual(topics, ["harga telur"])
            set_subscription_limit(123, 4, path=path)
            self.assertEqual(get_chat_subscription(123, path=path)["limit"], 4)
            self.assertIn(123, list_subscription_targets(path=path))
            removed, topics = remove_subscription_topic(123, "harga telur", path=path)
            self.assertEqual(removed, 1)
            self.assertEqual(topics, [])

    def test_telegram_topik_command_saves_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch("telegram_bot.TELEGRAM_SUBSCRIPTIONS_PATH", Path(tmpdir) / "subs.json"):
            session = Mock()
            session.post.return_value.json.return_value = {"ok": True, "result": {}}
            session.post.return_value.raise_for_status = Mock()
            bot = TelegramNewsBot(token="telegram-token", jina_api_key="jina-token", session=session)
            bot.handle_text(123, "/topik harga telur")
            subscription = get_chat_subscription(123, path=Path(tmpdir) / "subs.json")
            self.assertEqual(subscription["topics"], ["harga telur"])
            sent_text = session.post.call_args_list[-1].kwargs["json"]["text"]
            self.assertIn("harga telur", sent_text)

    def test_worker_subscription_digest_fetches_each_topic(self) -> None:
        fake_bot = Mock()
        with patch("worker.TelegramNewsBot", return_value=fake_bot), patch(
            "worker.fetch_news",
            return_value=([
                {
                    "title": "Harga Telur Naik",
                    "scraped_info": "Harga telur naik menjadi Rp32.000/kg.",
                    "url": "https://contoh.id/harga-telur",
                    "source": "contoh.id",
                    "published_at": "hari ini",
                }
            ], {"article_scrape_success": "1", "article_scrape_attempted": "1"}),
        ) as mocked_fetch:
            state = {"sent_digests": []}
            sent = worker.send_subscription_digests(
                token="telegram-token",
                jina_api_key="jina-token",
                subscriptions={123: {"topics": ["harga telur", "AI gambar"], "limit": 2}},
                request_timeout=25,
                max_search_rounds=1,
                default_limit=2,
                date_key="2026-06-27",
                digest_state=state,
            )
        self.assertEqual(sent, 1)
        self.assertEqual(mocked_fetch.call_count, 2)
        self.assertEqual(fake_bot.send_message.call_count, 2)
        self.assertEqual(len(state["sent_digests"]), 2)


if __name__ == "__main__":
    unittest.main()
