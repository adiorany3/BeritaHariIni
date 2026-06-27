from __future__ import annotations

import unittest
from datetime import datetime

from news_service import default_query, parse_search_response, today_indonesia


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

    def test_social_profiles_and_non_news_program_pages_are_rejected(self) -> None:
        markdown = """
### [Lainnya](https://www.instagram.com/contoh_akun/)
27 Juni 2026
432K Followers

### [Berita Video Panjang di YouTube](https://www.youtube.com/watch?v=contoh)
27 Juni 2026
811K Subscribers

### [Kelana Kota](https://www.suarasurabaya.net/kelana-kota/)
Sabtu, 27 Juni 2026
Program radio harian

### [Pemerintah Rilis Program Teknologi Baru untuk Sekolah](https://contoh.id/berita/program-teknologi-baru-sekolah)
Sabtu, 27 Juni 2026 10:00 WIB
"""
        articles = parse_search_response(markdown, DETECTED_AT)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "contoh.id")
        self.assertEqual(articles[0]["title"], "Pemerintah Rilis Program Teknologi Baru untuk Sekolah")

    def test_today_indonesia(self) -> None:
        now = datetime(2026, 6, 27, 10, 0)
        self.assertEqual(today_indonesia(now), "27 Juni 2026")


if __name__ == "__main__":
    unittest.main()
