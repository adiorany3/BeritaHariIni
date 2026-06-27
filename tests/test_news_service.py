from __future__ import annotations

import unittest
from datetime import datetime

from news_service import default_query, parse_search_response, today_indonesia


class NewsServiceTests(unittest.TestCase):
    def test_default_query_contains_indonesian_date(self) -> None:
        now = datetime(2026, 6, 27, 10, 0)
        self.assertIn("27 Juni 2026", default_query(now))

    def test_parse_markdown_links(self) -> None:
        markdown = """
[1] Title: Contoh Berita
[Contoh Berita](https://example.com/berita)

Ringkasan artikel.
"""
        articles = parse_search_response(markdown, "2026-06-27T10:00:00+07:00")
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Contoh Berita")
        self.assertEqual(articles[0]["source"], "example.com")

    def test_parse_markdown_deduplicates_title_and_url(self) -> None:
        markdown = """
[Berita Sama](https://example.com/a)
[Berita Sama](https://example.com/a)
"""
        articles = parse_search_response(markdown, "2026-06-27T10:00:00+07:00")
        self.assertEqual(len(articles), 1)


if __name__ == "__main__":
    unittest.main()
