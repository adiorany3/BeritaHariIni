from __future__ import annotations

import json
import os
import unittest
import requests
from datetime import datetime
from unittest.mock import Mock, patch

from news_service import (
    default_query,
    enrich_articles_with_scraped_info,
    extract_article_information,
    fallback_queries,
    fetch_news,
    fetch_article_information,
    fetch_article_text_document,
    build_jina_reader_url,
    build_text_only_reader_url,
    reader_payload_to_clean_txt,
    fetch_raw_markdown,
    source_scoped_query,
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

    def test_social_content_is_blocked_by_default_but_publishers_are_kept(self) -> None:
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
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "contoh.id")
        self.assertEqual(articles[0]["source_type"], "publisher")
        self.assertEqual(articles[0]["category"], "Teknologi")


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
        self.assertTrue(any("site:" in query for query in queries))
        self.assertTrue(all(" OR " not in query and "(" not in query and ")" not in query for query in queries))
        self.assertTrue(all("-site:" not in query for query in queries))
        self.assertEqual(len(queries), len(set(queries)))

    def test_source_scoped_query_removes_social_terms(self) -> None:
        query = source_scoped_query("berita ekonomi YouTube Instagram TikTok", datetime(2026, 6, 27, 10, 0))
        self.assertIn("site:kompas.com", query)
        self.assertNotIn("-site:youtube.com", query)
        self.assertNotIn("Instagram TikTok", query)
        self.assertNotIn("OR", query)

    def test_multi_word_search_keeps_phrase_without_jina_complex_syntax(self) -> None:
        query = source_scoped_query("berita harga telur hari ini", datetime(2026, 6, 27, 10, 0))
        self.assertIn("harga telur", query)
        self.assertNotIn('"harga telur"', query)
        self.assertNotIn(" OR ", query)
        self.assertNotIn("-site:", query)
        self.assertIn("site:kompas.com", query)
        self.assertIn("27 Juni 2026", query)
        self.assertNotIn("berita harga telur hari ini 27 Juni", query)

    def test_user_supplied_social_heavy_jina_payload_returns_no_articles(self) -> None:
        payload = {
            "code": 200,
            "data": [
                {"title": "Game Changer Pertumbuhan vs Insentif Otomotif | MARKET REVIEW", "url": "https://www.youtube.com/watch?v=abc", "date": "Dec 1, 2025"},
                {"title": "Ekonomi Indonesia Terancam Rendah 2026? - TikTok", "url": "https://www.tiktok.com/@metro_tv/video/7592609955358821652", "date": "Jan 7, 2026"},
                {"title": "Google Berita - Google News", "url": "https://news.google.com/home?hl=id&gl=ID&ceid=ID%3Aid"},
                {"title": "Bloomberg Technoz Flash 5 kembali hadir", "url": "https://www.instagram.com/reel/DZ6btAWpAWD/", "date": "4 days ago"},
            ],
        }
        articles = parse_search_response(payload, DETECTED_AT)
        self.assertEqual(articles, [])


    def test_fetch_news_limits_slow_fallback_rounds(self) -> None:
        markdown = """
### [Artikel Pertama Teknologi Indonesia](https://contoh.id/berita/artikel-pertama-teknologi-indonesia)
27 Juni 2026
Ringkasan tentang teknologi Indonesia hari ini.
"""
        with patch.dict(os.environ, {"NEWS_MAX_SEARCH_ROUNDS": "2", "NEWS_ENABLE_RSS": "0", "NEWS_ENABLE_ARTICLE_SCRAPE": "0"}, clear=False):
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

    def test_multi_word_search_requires_all_terms_not_or(self) -> None:
        rss_items = [
            {
                "id": "rss-harga-emas",
                "title": "Harga Emas Hari Ini Naik di Pasar",
                "url": "https://www.kompas.com/read/2026/06/27/120000/harga-emas-hari-ini-naik",
                "source": "kompas.com",
                "source_type": "publisher",
                "summary": "Artikel hanya membahas harga emas dan logam mulia.",
                "published_at": "2026-06-27T12:00:00",
                "time_status": "verified_today",
                "category_key": "ekonomi",
                "category": "Ekonomi & Bisnis",
            },
            {
                "id": "rss-stok-telur",
                "title": "Stok Telur Melimpah di Pasar Tradisional",
                "url": "https://www.detik.com/read/2026/06/27/120000/stok-telur-melimpah",
                "source": "detik.com",
                "source_type": "publisher",
                "summary": "Artikel hanya membahas pasokan dan distribusi telur.",
                "published_at": "2026-06-27T12:00:00",
                "time_status": "verified_today",
                "category_key": "ekonomi",
                "category": "Ekonomi & Bisnis",
            },
            {
                "id": "rss-harga-telur",
                "title": "Harga Telur Ayam Naik di Pasar Jakarta",
                "url": "https://www.cnbcindonesia.com/news/20260627120000/harga-telur-ayam-naik",
                "source": "cnbcindonesia.com",
                "source_type": "publisher",
                "summary": "Pedagang melaporkan harga telur ayam naik hari ini di sejumlah pasar.",
                "published_at": "2026-06-27T12:00:00",
                "time_status": "verified_today",
                "category_key": "ekonomi",
                "category": "Ekonomi & Bisnis",
            },
        ]
        with patch.dict(os.environ, {"NEWS_MAX_SEARCH_ROUNDS": "0", "NEWS_ENABLE_RSS": "1", "NEWS_ENABLE_ARTICLE_SCRAPE": "0"}, clear=False):
            with patch("news_service.jakarta_now", return_value=datetime(2026, 6, 27, 14, 0)):
                with patch("news_service.fetch_rss_articles", return_value=(rss_items, {
                    "rss_enabled": "true",
                    "rss_articles": "3",
                    "rss_feeds_checked": "1",
                }, "RSS test")):
                    articles, metadata = fetch_news("token", query="harga telur", max_results=20)
        self.assertEqual(metadata["strict_query_relevance"], "true")
        self.assertEqual(metadata["query_phrase"], "harga telur")
        self.assertEqual(metadata["search_rounds"], "0")
        self.assertEqual([item["title"] for item in articles], [
            "Harga Telur Ayam Naik di Pasar Jakarta"
        ])

    def test_extract_article_information_prefers_query_phrase_and_numbers(self) -> None:
        content = """
Title: Harga Telur Ayam Naik di Pasar Jakarta
URL Source: https://contoh.id/berita/harga-telur
Markdown Content:
![foto](https://contoh.id/foto.jpg)
[Baca juga](https://contoh.id/link)
Pedagang pasar menyebut harga telur ayam naik menjadi Rp32.000 per kilogram pada Sabtu pagi.
Kenaikan harga telur terjadi karena pasokan dari sentra produksi berkurang menjelang akhir pekan.
Sementara itu harga beras relatif stabil di sejumlah pasar tradisional.
"""
        info = extract_article_information(
            content,
            title="Harga Telur Ayam Naik di Pasar Jakarta",
            query="harga telur",
        )
        self.assertIn("harga telur", info.lower())
        self.assertIn("Rp32.000", info)
        self.assertNotIn("https://", info)
        self.assertNotIn("Markdown Content", info)


    def test_build_jina_reader_url_keeps_original_url_clean(self) -> None:
        self.assertEqual(
            build_jina_reader_url("https://www.example.com/news/read?id=1&utm_source=x#comments"),
            "https://r.jina.ai/https://www.example.com/news/read?id=1",
        )
        self.assertEqual(build_jina_reader_url("not-a-url"), "")

    def test_build_text_only_reader_url_prefers_streamlit_reader_when_configured(self) -> None:
        self.assertEqual(
            build_text_only_reader_url(
                "https://www.example.com/news/read?id=1&utm_source=x#comments",
                "https://berita-demo.streamlit.app/",
            ),
            "https://berita-demo.streamlit.app?reader=https%3A%2F%2Fwww.example.com%2Fnews%2Fread%3Fid%3D1",
        )
        self.assertEqual(
            build_text_only_reader_url("https://www.example.com/news/read", ""),
            "https://r.jina.ai/https://www.example.com/news/read",
        )

    def test_reader_payload_to_clean_txt_removes_image_markdown_and_boilerplate(self) -> None:
        payload = json.dumps({
            "data": {
                "content": """Title: Potret Horor Venezuela Usai Gempa
URL Source: https://www.cnbcindonesia.com/news/abc
Markdown Content:
![Image 1: Foto reruntuhan](https://asset.cnbcindonesia.com/foto.jpg)

Pemerintah Venezuela melaporkan gempa dahsyat merusak sejumlah bangunan dan memicu evakuasi warga di beberapa kota.

Baca Juga: Artikel rekomendasi lain

Tim penyelamat masih menyisir lokasi terdampak untuk mencari korban dan memastikan akses bantuan darurat tetap terbuka.
"""
            }
        })
        text = reader_payload_to_clean_txt(
            payload,
            title="Potret Horor Venezuela Usai Gempa",
            source_url="https://www.cnbcindonesia.com/news/abc",
        )
        self.assertIn("Pemerintah Venezuela", text)
        self.assertIn("Tim penyelamat", text)
        self.assertIn("Sumber asli: https://www.cnbcindonesia.com/news/abc", text)
        self.assertNotIn("![Image", text)
        self.assertNotIn("Markdown Content", text)
        self.assertNotIn("Baca Juga", text)
        self.assertNotIn("https://asset", text)

    def test_fetch_article_text_document_uses_clean_txt_reader(self) -> None:
        response = Mock()
        response.text = '{"data":{"content":"![Image 1](https://foto.jpg)\n\nHarga telur ayam naik menjadi Rp32.000 per kilogram di pasar tradisional. Pedagang menyebut pasokan dari sentra produksi berkurang."}}'
        response.raise_for_status = Mock()
        with patch.dict(os.environ, {"NEWS_ARTICLE_SCRAPE_TIMEOUT": "8"}, clear=False):
            with patch("news_service.requests.get", return_value=response) as mocked_get:
                text, status = fetch_article_text_document(
                    "token",
                    "https://www.kompas.com/read/2026/06/27/harga-telur",
                    title="Harga Telur Naik",
                )
        self.assertEqual(mocked_get.call_args.args[0], "https://r.jina.ai/https://www.kompas.com/read/2026/06/27/harga-telur")
        self.assertEqual(mocked_get.call_args.kwargs["headers"]["X-Retain-Images"], "none")
        self.assertEqual(status, "text_only_scraped_with_jina_reader")
        self.assertIn("Harga Telur Naik", text)
        self.assertNotIn("![Image", text)

    def test_fetch_article_information_uses_jina_reader_without_opening_source_site(self) -> None:
        response = Mock()
        response.text = '{"data":{"content":"Pedagang menyebut harga telur ayam naik menjadi Rp32.000 per kilogram hari ini. Kenaikan terjadi karena pasokan berkurang dari sentra produksi."}}'
        response.raise_for_status = Mock()
        with patch.dict(os.environ, {"NEWS_ARTICLE_SCRAPE_TIMEOUT": "8", "NEWS_ENABLE_ARTICLE_CACHE": "0"}, clear=False):
            with patch("news_service.requests.get", return_value=response) as mocked_get:
                info, status = fetch_article_information(
                    "token",
                    {
                        "title": "Harga Telur Ayam Naik di Pasar Jakarta",
                        "url": "https://www.kompas.com/read/2026/06/27/120000/harga-telur-ayam-naik",
                    },
                    query="harga telur",
                )
        _, kwargs = mocked_get.call_args
        self.assertEqual(mocked_get.call_args.args[0], "https://r.jina.ai/https://www.kompas.com/read/2026/06/27/120000/harga-telur-ayam-naik")
        self.assertEqual(kwargs["headers"]["Accept"], "application/json")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer token")
        self.assertEqual(kwargs["headers"]["X-Retain-Images"], "none")
        self.assertEqual(status, "scraped_with_jina_reader")
        self.assertIn("Rp32.000", info)

    def test_enrich_articles_replaces_summary_with_scraped_information(self) -> None:
        articles = [{
            "id": "a1",
            "title": "Harga Telur Ayam Naik di Pasar Jakarta",
            "url": "https://www.kompas.com/read/2026/06/27/120000/harga-telur-ayam-naik",
            "summary": "Ringkasan lama dari RSS.",
        }]
        with patch.dict(os.environ, {"NEWS_ENABLE_ARTICLE_SCRAPE": "1", "NEWS_MAX_ARTICLE_SCRAPES": "1"}, clear=False):
            with patch("news_service.fetch_article_information", return_value=("Harga telur ayam naik menjadi Rp32.000 per kilogram.", "scraped_with_jina_reader")):
                enriched, metadata = enrich_articles_with_scraped_info("token", articles, query="harga telur")
        self.assertEqual(enriched[0]["summary"], "Harga telur ayam naik menjadi Rp32.000 per kilogram.")
        self.assertEqual(enriched[0]["scraped_info"], "Harga telur ayam naik menjadi Rp32.000 per kilogram.")
        self.assertEqual(metadata["article_scrape_success"], "1")

    def test_specific_search_does_not_stop_at_static_rss_results(self) -> None:
        rss_items = [
            {
                "id": "rss-ekonomi",
                "title": "Pemerintah Bahas Pertumbuhan Ekonomi Nasional",
                "url": "https://www.kompas.com/read/2026/06/27/120000/pertumbuhan-ekonomi-nasional",
                "source": "kompas.com",
                "source_type": "publisher",
                "summary": "Rapat pemerintah membahas ekonomi nasional hari ini.",
                "published_at": "2026-06-27T12:00:00",
                "time_status": "verified_today",
                "category_key": "ekonomi",
                "category": "Ekonomi & Bisnis",
            }
        ]
        jina_markdown = """
### [Produsen Rilis Mobil Listrik Baru untuk Pasar Indonesia](https://oto.detik.com/mobil-listrik/2026/06/27/produsen-rilis-mobil-listrik-baru)
27 Juni 2026
Artikel membahas peluncuran mobil listrik baru dan rencana produksi kendaraan ramah lingkungan.
"""
        with patch.dict(os.environ, {"NEWS_MAX_SEARCH_ROUNDS": "1", "NEWS_ENABLE_RSS": "1", "NEWS_ENABLE_ARTICLE_SCRAPE": "0"}, clear=False):
            with patch("news_service.jakarta_now", return_value=datetime(2026, 6, 27, 14, 0)):
                with patch("news_service.fetch_rss_articles", return_value=(rss_items, {
                    "rss_enabled": "true",
                    "rss_articles": "1",
                    "rss_feeds_checked": "1",
                }, "RSS generic")):
                    with patch("news_service.fetch_raw_markdown", return_value=(jina_markdown, {
                        "query": "mobil listrik",
                        "fetched_at": DETECTED_AT,
                        "today_jakarta": "27 Juni 2026",
                        "content_type": "application/json",
                        "response_format": "json_preferred",
                    })) as mocked_fetch:
                        articles, metadata = fetch_news("token", query="mobil listrik", max_results=20)
        self.assertEqual(mocked_fetch.call_count, 1)
        self.assertEqual(metadata["strict_query_relevance"], "true")
        self.assertEqual(metadata["search_rounds"], "1")
        self.assertEqual([item["title"] for item in articles], [
            "Produsen Rilis Mobil Listrik Baru untuk Pasar Indonesia"
        ])

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

    def test_fetch_raw_markdown_retries_422_with_simpler_query(self) -> None:
        first = Mock()
        first.text = ""
        first.headers = {"content-type": "application/json"}
        first.status_code = 422
        http_error = requests.HTTPError("422 Client Error")
        http_error.response = first
        first.raise_for_status.side_effect = http_error

        second = Mock()
        second.text = '{"data": []}'
        second.headers = {"content-type": "application/json"}
        second.raise_for_status = Mock()

        complex_query = '(site:antaranews.com OR site:liputan6.com) "ai gambar" 27 Juni 2026 -site:youtube.com'
        with patch.dict(os.environ, {}, clear=True):
            with patch("news_service.requests.get", side_effect=[first, second]) as mocked_get:
                raw, metadata = fetch_raw_markdown("token", query=complex_query, now=datetime(2026, 6, 27, 14, 0))

        self.assertEqual(raw, '{"data": []}')
        self.assertEqual(mocked_get.call_count, 2)
        first_query = mocked_get.call_args_list[0].kwargs["params"]["q"]
        retry_query = mocked_get.call_args_list[1].kwargs["params"]["q"]
        self.assertNotIn(" OR ", first_query)
        self.assertNotIn("-site:", first_query)
        self.assertNotIn('"', first_query)
        self.assertIn("ai gambar", retry_query)
        self.assertEqual(metadata["jina_retried_after_422"], "true")

    def test_today_indonesia(self) -> None:
        now = datetime(2026, 6, 27, 10, 0)
        self.assertEqual(today_indonesia(now), "27 Juni 2026")


if __name__ == "__main__":
    unittest.main()
