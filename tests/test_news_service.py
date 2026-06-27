from __future__ import annotations

import os
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from news_service import (
    default_query,
    fallback_queries,
    fetch_news,
    fetch_raw_markdown,
    parse_search_response,
    parse_search_response_details,
    score_article_quality,
    today_indonesia,
)


DETECTED_AT = "2026-06-27T14:00:00+07:00"


class NewsServiceTests(unittest.TestCase):
    def test_default_query_contains_indonesian_date_and_categories(self) -> None:
        now = datetime(2026, 6, 27, 10, 0)
        query = default_query(now)
        self.assertIn("27 Juni 2026", query)
        self.assertIn("teknologi", query)
        self.assertIn("otomotif", query)

    def test_only_direct_articles_today_are_kept_and_categorised(self) -> None:
        markdown = """
[1] Title: Contoh sumber berita

## [Ponsel Baru Memakai Teknologi AI untuk Pendidikan](https://contoh.id/teknologi/ponsel-ai-pendidikan)
15 menit yang lalu

### [Menu Teknologi](https://contoh.id/teknologi)

## [Artikel Kemarin yang Tidak Boleh Tampil](https://contoh.id/berita/kemarin)
Kemarin

[Google redirect](https://news.google.com/read/abc)
5 menit yang lalu

![Image 1](https://contoh.id/assets/foto.jpg)
"""
        articles = parse_search_response(markdown, DETECTED_AT)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Ponsel Baru Memakai Teknologi AI untuk Pendidikan")
        self.assertEqual(articles[0]["category"], "Teknologi")
        self.assertEqual(articles[0]["published_at"], "15 menit yang lalu")
        self.assertEqual(articles[0]["url"], "https://contoh.id/teknologi/ponsel-ai-pendidikan")

    def test_explicit_date_must_match_today(self) -> None:
        markdown = """
### [Berita hari ini](https://contoh.id/berita/hari-ini)
Jumat, 27 Jun 2026 11:00 WIB

### [Berita lama](https://contoh.id/berita/lama)
Kamis, 26 Jun 2026 23:50 WIB
"""
        articles = parse_search_response(markdown, DETECTED_AT)
        self.assertEqual([item["title"] for item in articles], ["Berita hari ini"])

    def test_relative_hours_crossing_midnight_is_not_today(self) -> None:
        detected_at = "2026-06-27T00:30:00+07:00"
        markdown = """
### [Artikel semalam](https://contoh.id/berita/semalam)
2 jam yang lalu
"""
        articles = parse_search_response(markdown, detected_at)
        self.assertEqual(articles, [])

    def test_duplicate_article_is_kept_once(self) -> None:
        markdown = """
## [Berita Sama](https://contoh.id/berita/sama)
10 menit yang lalu

### [Berita Sama](https://contoh.id/berita/sama)
10 menit yang lalu
"""
        articles = parse_search_response(markdown, DETECTED_AT)
        self.assertEqual(len(articles), 1)

    def test_social_content_is_kept_but_profiles_and_engagement_are_ignored(self) -> None:
        markdown = """
### [Lainnya](https://www.instagram.com/contoh_akun/)
27 Juni 2026
432K Followers

### [Video Teknologi AI untuk Siswa Indonesia](https://www.youtube.com/watch?v=contoh123)
27 Juni 2026
811K Subscribers
2.4K likes

### [Update Mobil Listrik Baru untuk Perkotaan](https://www.tiktok.com/@media/video/751234567890)
Sabtu, 27 Juni 2026
12K likes
234 komentar

### [Kelana Kota](https://www.suarasurabaya.net/kelana-kota/)
Sabtu, 27 Juni 2026
Program radio harian

### [Pemerintah Rilis Program Teknologi Baru untuk Sekolah](https://contoh.id/berita/program-teknologi-baru-sekolah)
Sabtu, 27 Juni 2026 10:00 WIB
"""
        articles = parse_search_response(markdown, DETECTED_AT)
        self.assertEqual(len(articles), 3)
        self.assertEqual([item["source"] for item in articles], ["YouTube", "TikTok", "contoh.id"])
        self.assertEqual([item["source_type"] for item in articles], ["social", "social", "publisher"])
        self.assertEqual(articles[0]["category"], "Teknologi")
        self.assertEqual(articles[1]["category"], "Otomotif")
        self.assertNotIn("Subscribers", articles[0]["summary"])
        self.assertNotIn("likes", articles[1]["summary"])


    def test_unverified_direct_article_is_available_only_as_dashboard_fallback(self) -> None:
        markdown = """
### [Riset Teknologi Baru untuk Sekolah Indonesia](https://contoh.id/berita/riset-teknologi-sekolah)
Ringkasan berita yang membahas inovasi pendidikan digital di Indonesia.
"""
        strict_articles = parse_search_response(markdown, DETECTED_AT)
        self.assertEqual(strict_articles, [])

        candidates, stats = parse_search_response_details(
            markdown,
            DETECTED_AT,
            allow_unverified_fallback=True,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["time_status"], "needs_time_verification")
        self.assertEqual(candidates[0]["published_at"], "Waktu belum terdeteksi")
        self.assertEqual(stats["unverified_articles"], 1)

    def test_old_article_is_never_promoted_to_unverified_fallback(self) -> None:
        markdown = """
### [Artikel Lama](https://contoh.id/berita/artikel-lama-panjang)
26 Juni 2026
"""
        candidates, _ = parse_search_response_details(
            markdown,
            DETECTED_AT,
            allow_unverified_fallback=True,
        )
        self.assertEqual(candidates, [])


    def test_json_search_response_uses_timestamp_and_content_context(self) -> None:
        payload = {
            "code": 200,
            "data": [
                {
                    "title": "Kompas Rilis Laporan Teknologi Baru untuk Sekolah",
                    "url": "https://tekno.kompas.com/read/2026/06/27/120000/teknologi-baru-untuk-sekolah",
                    "content": "Artikel membahas teknologi pendidikan digital di Indonesia.",
                    "timestamp": "2026-06-27T12:00:00+07:00",
                }
            ],
        }
        articles = parse_search_response(payload, DETECTED_AT)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "tekno.kompas.com")
        self.assertEqual(articles[0]["published_at"], "2026-06-27T12:00:00")
        self.assertGreaterEqual(articles[0]["quality_score"], 70)

    def test_relative_days_are_not_treated_as_seconds(self) -> None:
        markdown = """
### [Artikel Satu Hari Lalu](https://contoh.id/berita/artikel-satu-hari-lalu)
1 hari yang lalu
"""
        articles = parse_search_response(markdown, DETECTED_AT)
        self.assertEqual(articles, [])

    def test_quality_score_rewards_editorial_relevance_and_penalises_generic_links(self) -> None:
        good_score, _ = score_article_quality(
            title="Pemerintah Rilis Program Teknologi Baru untuk Sekolah Indonesia",
            summary="Program ini membahas pembelajaran digital, sekolah, guru, dan siswa di Indonesia.",
            url="https://tekno.kompas.com/read/2026/06/27/120000/program-teknologi-baru-sekolah",
            time_status="verified_today",
            category_key="teknologi",
            query="berita teknologi sekolah Indonesia",
        )
        bad_score, _ = score_article_quality(
            title="Terpopuler Hari Ini",
            summary="",
            url="https://contoh.id/news",
            time_status="needs_time_verification",
            category_key="lainnya",
            query="berita teknologi sekolah Indonesia",
        )
        self.assertGreater(good_score, bad_score + 40)

    def test_fallback_queries_are_distinct_and_date_aware(self) -> None:
        queries = fallback_queries("berita energi", datetime(2026, 6, 27, 10, 0))
        self.assertGreaterEqual(len(queries), 2)
        self.assertTrue(all("27 Juni 2026" in query for query in queries))
        self.assertEqual(len(queries), len(set(queries)))


    def test_fetch_news_limits_slow_fallback_rounds(self) -> None:
        markdown = """
### [Artikel Pertama Teknologi Indonesia](https://contoh.id/berita/artikel-pertama-teknologi-indonesia)
27 Juni 2026
Ringkasan tentang teknologi Indonesia hari ini.
"""
        with patch.dict(os.environ, {"NEWS_MAX_SEARCH_ROUNDS": "2"}, clear=False):
            with patch("news_service.jakarta_now", return_value=datetime(2026, 6, 27, 14, 0)):
                with patch("news_service.fetch_raw_markdown", return_value=(markdown, {
                    "query": "berita",
                    "fetched_at": DETECTED_AT,
                    "today_jakarta": "27 Juni 2026",
                    "content_type": "application/json",
                    "response_format": "json_preferred",
                })) as mocked_fetch:
                    articles, metadata = fetch_news("token", query="berita", max_results=20)
        self.assertLessEqual(mocked_fetch.call_count, 2)
        self.assertEqual(metadata["max_search_rounds"], "2")
        self.assertEqual(metadata["search_rounds"], "2")
        self.assertEqual(len(articles), 1)

    def test_fetch_raw_markdown_uses_fast_jina_headers(self) -> None:
        response = Mock()
        response.text = '{"data": []}'
        response.headers = {"content-type": "application/json"}
        response.raise_for_status = Mock()
        with patch.dict(os.environ, {}, clear=True):
            with patch("news_service.requests.get", return_value=response) as mocked_get:
                raw, metadata = fetch_raw_markdown("token", query="berita", now=datetime(2026, 6, 27, 14, 0))
        _, kwargs = mocked_get.call_args
        headers = kwargs["headers"]
        self.assertEqual(raw, '{"data": []}')
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["X-Respond-With"], "no-content")
        self.assertEqual(headers["X-Retain-Images"], "none")
        self.assertEqual(headers["X-Md-Link-Style"], "discarded")
        self.assertEqual(headers["X-Timeout"], "12")
        self.assertEqual(kwargs["timeout"], 25)
        self.assertEqual(metadata["jina_respond_with"], "no-content")

    def test_today_indonesia(self) -> None:
        now = datetime(2026, 6, 27, 10, 0)
        self.assertEqual(today_indonesia(now), "27 Juni 2026")


if __name__ == "__main__":
    unittest.main()
