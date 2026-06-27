import json
import unittest

from news_service import parse_search_response


class ParseSearchResponseTests(unittest.TestCase):
    def test_parses_json_items(self):
        payload = {
            "data": [
                {
                    "title": "Judul berita terkini",
                    "url": "https://contoh.id/berita-1",
                    "description": "Ringkasan berita.",
                    "date": "2026-06-27",
                }
            ]
        }
        articles = parse_search_response(payload, "2026-06-27T10:00:00+07:00")
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["source"], "contoh.id")
        self.assertEqual(articles[0]["title"], "Judul berita terkini")

    def test_parses_markdown_links(self):
        payload = "[Berita terbaru](https://contoh.id/berita)\nRingkasan singkat."
        articles = parse_search_response(payload, "2026-06-27T10:00:00+07:00")
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["url"], "https://contoh.id/berita")

    def test_removes_duplicate_urls(self):
        payload = json.dumps(
            {
                "data": [
                    {"title": "A", "url": "https://contoh.id/a"},
                    {"title": "A lain", "url": "https://contoh.id/a"},
                ]
            }
        )
        articles = parse_search_response(payload, "2026-06-27T10:00:00+07:00")
        self.assertEqual(len(articles), 1)


if __name__ == "__main__":
    unittest.main()
