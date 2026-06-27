"""Pekerja terjadwal: cari berita, simpan hasil, dan kirim digest Telegram bila dikonfigurasi.

Mode ini cocok untuk GitHub Actions `schedule`: workflow berjalan sebentar setiap pagi,
ambil berita terbaru, lalu mengirim judul + ringkasan + link asli ke chat Telegram.
"""
from __future__ import annotations

import logging
from pathlib import Path

from config import apply_secrets_to_environment, get_secret, get_secret_bool, get_secret_int
from news_service import fetch_news
from storage import read_json, write_json
from telegram_bot import TelegramNewsBot, build_news_messages, parse_allowed_chat_ids

BASE_DIR = Path(__file__).resolve().parent
LATEST_PATH = BASE_DIR / "data" / "latest_news.json"
SENT_PATH = BASE_DIR / "data" / "sent_news.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger(__name__)


def _broadcast_chat_ids() -> set[int]:
    """Ambil penerima broadcast Telegram.

    Prioritas: TELEGRAM_BROADCAST_CHAT_IDS. Jika kosong, fallback ke
    TELEGRAM_ALLOWED_CHAT_IDS agar konfigurasi lama tetap bisa dipakai.
    """
    raw = get_secret("TELEGRAM_BROADCAST_CHAT_IDS", "").strip()
    if not raw:
        raw = get_secret("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    return parse_allowed_chat_ids(raw)


def _should_send_telegram() -> bool:
    """Default true saat token + chat id tersedia, bisa dimatikan eksplisit."""
    configured = bool(get_secret("TELEGRAM_BOT_TOKEN", "") and _broadcast_chat_ids())
    return get_secret_bool("WORKER_SEND_TELEGRAM", configured)


def send_morning_digest(
    *,
    token: str,
    jina_api_key: str,
    chat_ids: set[int],
    theme: str,
    articles: list[dict],
    metadata: dict,
    limit: int,
    request_timeout: int,
) -> int:
    """Kirim digest Telegram ke semua chat tujuan dan kembalikan jumlah chat sukses."""
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN belum diatur.")
    if not chat_ids:
        raise ValueError("TELEGRAM_BROADCAST_CHAT_IDS belum diatur.")

    bot = TelegramNewsBot(
        token=token,
        jina_api_key=jina_api_key,
        news_limit=limit,
        request_timeout=request_timeout,
    )
    messages = build_news_messages(theme, articles[:limit], metadata)
    sent = 0
    for chat_id in sorted(chat_ids):
        for message in messages:
            bot.send_message(chat_id, message)
        sent += 1
    return sent


def main() -> None:
    apply_secrets_to_environment()
    api_key = get_secret("JINA_API_KEY", "")
    query = get_secret("NEWS_QUERY", "").strip() or None
    max_results = get_secret_int("MAX_RESULTS", 20, minimum=1, maximum=100)
    request_timeout = get_secret_int("NEWS_REQUEST_TIMEOUT", 25, minimum=5, maximum=90)
    max_search_rounds_raw = get_secret("NEWS_MAX_SEARCH_ROUNDS", "")
    max_search_rounds = (
        get_secret_int("NEWS_MAX_SEARCH_ROUNDS", 2, minimum=0, maximum=5)
        if max_search_rounds_raw
        else None
    )

    articles, metadata = fetch_news(
        api_key,
        query=query,
        max_results=max_results,
        timeout=request_timeout,
        max_search_rounds=max_search_rounds,
    )
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

    if _should_send_telegram():
        token = get_secret("TELEGRAM_BOT_TOKEN", "")
        chat_ids = _broadcast_chat_ids()
        telegram_limit = get_secret_int("TELEGRAM_NEWS_LIMIT", 5, minimum=1, maximum=10)
        telegram_timeout = get_secret_int("TELEGRAM_NEWS_TIMEOUT", request_timeout, minimum=5, maximum=90)
        theme = (
            get_secret("WORKER_TELEGRAM_TITLE", "").strip()
            or query
            or "Berita terbaru pagi ini"
        )
        sent = send_morning_digest(
            token=token,
            jina_api_key=api_key,
            chat_ids=chat_ids,
            theme=theme,
            articles=articles,
            metadata=metadata,
            limit=telegram_limit,
            request_timeout=telegram_timeout,
        )
        LOGGER.info("Digest Telegram terkirim ke %d chat.", sent)
    elif get_secret_bool("WORKER_REQUIRE_TELEGRAM", False):
        raise RuntimeError(
            "WORKER_REQUIRE_TELEGRAM=1, tetapi TELEGRAM_BOT_TOKEN atau "
            "TELEGRAM_BROADCAST_CHAT_IDS belum dikonfigurasi."
        )
    else:
        LOGGER.info("Telegram broadcast dilewati karena token/chat id belum dikonfigurasi atau WORKER_SEND_TELEGRAM=0.")


if __name__ == "__main__":
    main()
