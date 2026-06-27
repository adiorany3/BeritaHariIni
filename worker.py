"""Pekerja terjadwal: cari berita lalu simpan hasil ke data/."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from news_service import fetch_news
from storage import read_json, write_json

BASE_DIR = Path(__file__).resolve().parent
LATEST_PATH = BASE_DIR / "data" / "latest_news.json"
SENT_PATH = BASE_DIR / "data" / "sent_news.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger(__name__)


def main() -> None:
    api_key = os.environ.get("JINA_API_KEY", "").strip()
    query = os.environ.get("NEWS_QUERY", "").strip() or None
    max_results = int(os.environ.get("MAX_RESULTS", "20"))

    articles, metadata = fetch_news(api_key, query=query, max_results=max_results)
    previous = read_json(LATEST_PATH, {"articles": []})

    previous_ids = {
        str(article.get("id", ""))
        for article in previous.get("articles", [])
        if isinstance(article, dict)
    }
    new_count = sum(
        1
        for article in articles
        if article.get("id") not in previous_ids
        and article.get("time_status", "verified_today") == "verified_today"
    )

    output = {
        "metadata": metadata,
        "articles": articles,
    }
    write_json(LATEST_PATH, output)
    # sent_news.json dipertahankan sebagai file kosong/kompatibilitas agar workflow lama tidak rusak.
    write_json(SENT_PATH, {"sent_ids": []})
    LOGGER.info("Menyimpan %d hasil pencarian; %d artikel baru terverifikasi.", len(articles), new_count)


if __name__ == "__main__":
    main()
