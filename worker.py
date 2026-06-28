"""Pekerja terjadwal: cari berita, simpan hasil, dan kirim digest Telegram bila dikonfigurasi.

Mode ini cocok untuk GitHub Actions `schedule`: workflow berjalan sebentar setiap pagi,
ambil berita terbaru, lalu mengirim judul + konten hasil scrape + link teks bersih TXT + link asli ke chat Telegram.
"""
from __future__ import annotations

import logging
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from config import apply_secrets_to_environment, get_secret, get_secret_bool, get_secret_int
from news_service import fetch_news
from storage import read_json, write_json
from telegram_bot import TelegramNewsBot, build_news_messages, list_subscription_targets, parse_allowed_chat_ids

BASE_DIR = Path(__file__).resolve().parent
LATEST_PATH = BASE_DIR / "data" / "latest_news.json"
SENT_PATH = BASE_DIR / "data" / "sent_news.json"
DIGEST_STATE_PATH = BASE_DIR / "data" / "telegram_digest_state.json"
DEFAULT_DEDUPE_TIMEZONE = "Asia/Jakarta"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOGGER = logging.getLogger(__name__)




def _today_key(timezone_name: str = DEFAULT_DEDUPE_TIMEZONE) -> str:
    """Tanggal lokal untuk kunci dedupe digest harian."""
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo(DEFAULT_DEDUPE_TIMEZONE)
    return datetime.now(tz).strftime("%Y-%m-%d")


def _digest_key(*, chat_id: int, theme: str, date_key: str) -> str:
    """Kunci stabil untuk mencegah digest pagi yang sama terkirim berkali-kali."""
    raw = f"{date_key}|{chat_id}|{theme.strip().lower()}"
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def _normalise_digest_state(value: object) -> dict:
    if not isinstance(value, dict):
        return {"sent_digests": []}
    sent = value.get("sent_digests")
    if not isinstance(sent, list):
        sent = []
    return {"sent_digests": [item for item in sent if isinstance(item, dict)]}


def _digest_already_sent(state: dict, *, chat_id: int, theme: str, date_key: str) -> bool:
    key = _digest_key(chat_id=chat_id, theme=theme, date_key=date_key)
    return any(item.get("key") == key for item in state.get("sent_digests", []))


def _mark_digest_sent(state: dict, *, chat_id: int, theme: str, date_key: str) -> None:
    key = _digest_key(chat_id=chat_id, theme=theme, date_key=date_key)
    if any(item.get("key") == key for item in state.get("sent_digests", [])):
        return
    state.setdefault("sent_digests", []).append(
        {
            "key": key,
            "chat_id": chat_id,
            "theme": theme,
            "date": date_key,
            "sent_at": datetime.now(ZoneInfo(DEFAULT_DEDUPE_TIMEZONE)).isoformat(timespec="seconds"),
        }
    )
    # Simpan ringkas: cukup 120 catatan terakhir supaya file state tidak membesar.
    state["sent_digests"] = state.get("sent_digests", [])[-120:]


def _unsent_chat_ids(chat_ids: set[int], *, state: dict, theme: str, date_key: str) -> set[int]:
    return {
        chat_id
        for chat_id in chat_ids
        if not _digest_already_sent(state, chat_id=chat_id, theme=theme, date_key=date_key)
    }


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




def send_subscription_digests(
    *,
    token: str,
    jina_api_key: str,
    subscriptions: dict[int, dict],
    request_timeout: int,
    max_search_rounds: int | None,
    default_limit: int,
    date_key: str,
    digest_state: dict,
    dedupe_enabled: bool = True,
    force_send: bool = False,
) -> int:
    """Kirim digest pagi berdasarkan topik langganan per chat.

    Return jumlah chat yang berhasil dikirimi setidaknya satu pesan.
    """
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN belum diatur.")
    bot = TelegramNewsBot(
        token=token,
        jina_api_key=jina_api_key,
        news_limit=default_limit,
        request_timeout=request_timeout,
        max_search_rounds=max_search_rounds,
    )
    sent_chats = 0
    for chat_id, config in sorted(subscriptions.items()):
        topics = [str(topic).strip() for topic in config.get("topics", []) if str(topic).strip()]
        if not topics:
            continue
        limit = max(1, min(int(config.get("limit", default_limit) or default_limit), 10))
        any_sent = False
        for topic in topics:
            if dedupe_enabled and not force_send and _digest_already_sent(digest_state, chat_id=chat_id, theme=topic, date_key=date_key):
                LOGGER.info("Topik %s untuk chat %s sudah terkirim pada %s; lewati.", topic, chat_id, date_key)
                continue
            articles, metadata = fetch_news(
                jina_api_key,
                query=topic,
                max_results=limit,
                timeout=request_timeout,
                max_search_rounds=max_search_rounds,
            )
            for message in build_news_messages(f"Pagi ini - {topic}", articles[:limit], metadata):
                bot.send_message(chat_id, message)
            _mark_digest_sent(digest_state, chat_id=chat_id, theme=topic, date_key=date_key)
            any_sent = True
        if any_sent:
            sent_chats += 1
    return sent_chats


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
        dedupe_enabled = get_secret_bool("WORKER_DEDUPE_TELEGRAM", True)
        force_send = get_secret_bool("WORKER_FORCE_SEND", False)
        dedupe_date = get_secret("WORKER_DEDUPE_DATE", "").strip() or _today_key(
            get_secret("WORKER_DEDUPE_TIMEZONE", DEFAULT_DEDUPE_TIMEZONE).strip() or DEFAULT_DEDUPE_TIMEZONE
        )
        digest_state = _normalise_digest_state(read_json(DIGEST_STATE_PATH, {"sent_digests": []}))
        use_subscriptions = get_secret_bool("WORKER_USE_TELEGRAM_SUBSCRIPTIONS", True)
        subscriptions = list_subscription_targets() if use_subscriptions else {}
        if subscriptions:
            sent = send_subscription_digests(
                token=token,
                jina_api_key=api_key,
                subscriptions=subscriptions,
                request_timeout=telegram_timeout,
                max_search_rounds=max_search_rounds,
                default_limit=telegram_limit,
                date_key=dedupe_date,
                digest_state=digest_state,
                dedupe_enabled=dedupe_enabled,
                force_send=force_send,
            )
            write_json(DIGEST_STATE_PATH, digest_state)
            LOGGER.info("Digest topik langganan Telegram terkirim ke %d chat.", sent)
        else:
            target_chat_ids = set(chat_ids)
            if dedupe_enabled and not force_send:
                target_chat_ids = _unsent_chat_ids(
                    chat_ids, state=digest_state, theme=theme, date_key=dedupe_date
                )
            if not target_chat_ids:
                LOGGER.info(
                    "Digest Telegram untuk %s sudah pernah terkirim hari ini; pengiriman dilewati.",
                    dedupe_date,
                )
                write_json(DIGEST_STATE_PATH, digest_state)
            else:
                sent = send_morning_digest(
                    token=token,
                    jina_api_key=api_key,
                    chat_ids=target_chat_ids,
                    theme=theme,
                    articles=articles,
                    metadata=metadata,
                    limit=telegram_limit,
                    request_timeout=telegram_timeout,
                )
                for chat_id in target_chat_ids:
                    _mark_digest_sent(digest_state, chat_id=chat_id, theme=theme, date_key=dedupe_date)
                write_json(DIGEST_STATE_PATH, digest_state)
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
