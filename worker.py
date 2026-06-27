"""Pekerja terjadwal: cari berita, kirim artikel baru, lalu simpan hasil ke data/."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from news_service import fetch_news
from storage import article_ids, read_json, write_json
from telegram import send_news

BASE_DIR = Path(__file__).resolve().parent
LATEST_PATH = BASE_DIR / "data" / "latest_news.json"
SENT_PATH = BASE_DIR / "data" / "sent_news.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger(__name__)


def main() -> None:
    api_key = os.environ.get("JINA_API_KEY", "").strip()
    query = os.environ.get("NEWS_QUERY", "").strip() or None
    max_results = int(os.environ.get("MAX_RESULTS", "20"))
    notification_limit = int(os.environ.get("NOTIFICATION_LIMIT", "5"))

    articles, metadata = fetch_news(api_key, query=query, max_results=max_results)
    previous = read_json(LATEST_PATH, {"articles": []})
    sent = read_json(SENT_PATH, {"sent_ids": []})

    previous_ids = article_ids(previous)
    sent_ids = {str(item) for item in sent.get("sent_ids", [])}
    candidates = [
        article for article in articles
        if article["id"] not in sent_ids and article["id"] not in previous_ids
    ]
    to_notify = candidates[:notification_limit]

    if to_notify:
        send_news(
            os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
            to_notify,
            metadata["today_jakarta"],
        )
        sent_ids.update(article["id"] for article in to_notify)
        LOGGER.info("Mengirim %d notifikasi baru ke Telegram.", len(to_notify))
    else:
        LOGGER.info("Tidak ada artikel baru untuk dikirim.")

    output = {
        "metadata": metadata,
        "articles": articles,
    }
    write_json(LATEST_PATH, output)
    # Batasi riwayat agar file tetap kecil. Artikel baru yang belum dikirim tidak hilang.
    write_json(SENT_PATH, {"sent_ids": sorted(sent_ids)[-2000:]})
    LOGGER.info("Menyimpan %d hasil pencarian.", len(articles))


if __name__ == "__main__":
    main()
