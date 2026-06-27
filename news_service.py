"""Pengambilan dan normalisasi hasil berita dari Jina Search."""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

JAKARTA = ZoneInfo("Asia/Jakarta")
JINA_SEARCH_URL = "https://s.jina.ai/"
MONTHS_ID = (
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)


def jakarta_now() -> datetime:
    return datetime.now(JAKARTA)


def today_indonesia(now: datetime | None = None) -> str:
    now = now or jakarta_now()
    return f"{now.day} {MONTHS_ID[now.month - 1]} {now.year}"


def default_query(now: datetime | None = None) -> str:
    """Memaksa konteks tanggal Jakarta agar hasil lebih relevan untuk hari ini."""
    return f"Berita Indonesia terbaru hari ini {today_indonesia(now)}"


def _clean_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _valid_url(value: Any) -> str:
    value = str(value or "").strip().rstrip(".,;:!?")
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _host(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


def _article_id(url: str, title: str) -> str:
    return sha256(f"{url}|{title.lower()}".encode("utf-8")).hexdigest()[:20]


def _normalise_item(raw: dict[str, Any], detected_at: str) -> dict[str, str] | None:
    title = _clean_text(raw.get("title") or raw.get("name") or raw.get("headline"), 300)
    url = _valid_url(raw.get("url") or raw.get("link") or raw.get("href"))
    if not title or not url:
        return None

    description = _clean_text(
        raw.get("description")
        or raw.get("snippet")
        or raw.get("content")
        or raw.get("text")
        or raw.get("body"),
        600,
    )
    published_at = _clean_text(
        raw.get("published_at")
        or raw.get("publishedDate")
        or raw.get("date")
        or raw.get("published")
        or raw.get("time"),
        80,
    )
    return {
        "id": _article_id(url, title),
        "title": title,
        "url": url,
        "source": _host(url),
        "summary": description,
        "published_at": published_at,
        "detected_at": detected_at,
    }


def _walk_json(value: Any, detected_at: str) -> list[dict[str, str]]:
    """Mendukung bentuk respons Jina yang berbeda tanpa mengunci ke satu skema."""
    found: list[dict[str, str]] = []
    if isinstance(value, dict):
        item = _normalise_item(value, detected_at)
        if item:
            found.append(item)
        for child in value.values():
            found.extend(_walk_json(child, detected_at))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_json(child, detected_at))
    return found


def _parse_markdown(text: str, detected_at: str) -> list[dict[str, str]]:
    """Membaca link Markdown jika endpoint mengembalikan hasil sebagai teks."""
    items: list[dict[str, str]] = []
    link_pattern = re.compile(r"(?<!!)\[([^\]]{3,300})\]\((https?://[^\s)]+)\)")
    for match in link_pattern.finditer(text):
        title, url = match.groups()
        start, end = match.span()
        # Ringkasan biasanya berada dekat dengan tautan pada respons Markdown.
        context = text[end : end + 450]
        context = re.sub(r"\[[^\]]+\]\([^)]*\)", "", context)
        context = _clean_text(context.split("\n\n", 1)[0], 450)
        item = _normalise_item(
            {"title": title, "url": url, "description": context}, detected_at
        )
        if item:
            items.append(item)
    return items


def _deduplicate(items: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for item in items:
        url_key = item["url"].rstrip("/").lower()
        title_key = re.sub(r"\W+", "", item["title"].lower())
        if url_key in seen_urls or title_key in seen_titles:
            continue
        # Menghindari tautan dokumentasi Jina bila muncul pada hasil pencarian.
        if _host(item["url"]).endswith("jina.ai"):
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def parse_search_response(payload: str | dict[str, Any] | list[Any], detected_at: str, limit: int = 20) -> list[dict[str, str]]:
    """Ubah JSON atau Markdown dari Jina menjadi daftar artikel seragam."""
    parsed: Any = payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = None

    items = _walk_json(parsed, detected_at) if parsed is not None else []
    if not items and isinstance(payload, str):
        items = _parse_markdown(payload, detected_at)
    return _deduplicate(items, limit)


def fetch_news(
    api_key: str,
    query: str | None = None,
    max_results: int = 20,
    timeout: int = 45,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Panggil Jina Search dengan header X-Engine: direct dari permintaan pengguna."""
    if not api_key:
        raise ValueError("JINA_API_KEY belum diatur.")

    now = jakarta_now()
    query = (query or default_query(now)).strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Engine": "direct",
        "Accept": "application/json, text/markdown;q=0.9, text/plain;q=0.8",
        "User-Agent": "news-monitor-streamlit/1.0",
    }
    response = requests.get(
        JINA_SEARCH_URL,
        params={"q": query},
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()

    detected_at = now.isoformat()
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        payload: str | dict[str, Any] | list[Any] = response.json()
    else:
        payload = response.text

    articles = parse_search_response(payload, detected_at, max_results)
    metadata = {
        "query": query,
        "fetched_at": detected_at,
        "today_jakarta": today_indonesia(now),
        "result_count": str(len(articles)),
    }
    return articles, metadata
