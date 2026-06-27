"""Notifikasi Telegram untuk tautan artikel langsung yang lolos filter hari ini."""
from __future__ import annotations

from typing import Any

import requests


def _clean(value: str, max_length: int) -> str:
    return " ".join(str(value or "").split())[:max_length]


def build_message(articles: list[dict[str, Any]], date_label: str) -> str:
    lines = [f"📰 Berita baru hari ini | {date_label}", ""]
    for index, article in enumerate(articles, start=1):
        title = _clean(article.get("title", "Tanpa judul"), 180)
        category = _clean(article.get("category", "Lainnya"), 60)
        source = _clean(article.get("source", "Sumber tidak diketahui"), 80)
        source_type = _clean(article.get("source_type", "publisher"), 30)
        published_at = _clean(article.get("published_at", "Hari ini"), 80)
        url = _clean(article.get("url", ""), 500)
        lines.extend(
            [
                f"{index}. {title}",
                f"Kategori: {category} | Sumber: {source}{' (Konten sosial)' if source_type == 'social' else ''} | Waktu: {published_at}",
                url,
                "",
            ]
        )
    lines.append("Tautan mengarah ke artikel atau postingan asli. Periksa sumber sebelum membagikan atau mengambil keputusan.")
    return "\n".join(lines)


def send_news(
    bot_token: str,
    chat_id: str,
    articles: list[dict[str, Any]],
    date_label: str,
    timeout: int = 30,
) -> None:
    if not bot_token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum diatur.")
    if not articles:
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": build_message(articles, date_label),
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram menolak pesan: {body.get('description', 'unknown error')}")
