"""Konfigurasi aman untuk environment variable dan Streamlit Secrets.

Semua token/API key sebaiknya disimpan di Streamlit Community Cloud Secrets
atau file lokal `.streamlit/secrets.toml` yang tidak di-commit.
"""
from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent

CONFIG_ENV_NAMES: tuple[str, ...] = (
    "JINA_API_KEY",
    "JINA_PAGE_TIMEOUT",
    "JINA_RESPOND_WITH",
    "NEWS_QUERY",
    "MAX_RESULTS",
    "NEWS_MAX_SEARCH_ROUNDS",
    "NEWS_REQUEST_TIMEOUT",
    "NEWS_ENABLE_RSS",
    "NEWS_RSS_TIMEOUT",
    "NEWS_MAX_RSS_FEEDS",
    "NEWS_ALLOW_SOCIAL",
    "NEWS_ENABLE_ARTICLE_SCRAPE",
    "NEWS_ARTICLE_SCRAPE_TIMEOUT",
    "NEWS_MAX_ARTICLE_SCRAPES",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_CHAT_IDS",
    "TELEGRAM_BROADCAST_CHAT_IDS",
    "TELEGRAM_NEWS_LIMIT",
    "TELEGRAM_NEWS_TIMEOUT",
    "TELEGRAM_MAX_SEARCH_ROUNDS",
    "TELEGRAM_POLL_TIMEOUT",
    "TELEGRAM_AUTO_START",
    "TELEGRAM_DELETE_WEBHOOK_ON_START",
    "TELEGRAM_DROP_PENDING_UPDATES",
    "WORKER_SEND_TELEGRAM",
    "WORKER_REQUIRE_TELEGRAM",
    "WORKER_TELEGRAM_TITLE",
    "LOG_LEVEL",
)

SPECIAL_SECTION_ALIASES: dict[str, tuple[tuple[str, str], ...]] = {
    "JINA_API_KEY": (("jina", "api_key"), ("jina", "key")),
    "JINA_PAGE_TIMEOUT": (("jina", "page_timeout"),),
    "JINA_RESPOND_WITH": (("jina", "respond_with"),),
    "TELEGRAM_BOT_TOKEN": (("telegram", "bot_token"), ("telegram", "token")),
    "TELEGRAM_ALLOWED_CHAT_IDS": (("telegram", "allowed_chat_ids"), ("telegram", "chat_ids")),
    "TELEGRAM_BROADCAST_CHAT_IDS": (("telegram", "broadcast_chat_ids"), ("telegram", "chat_ids"), ("telegram", "allowed_chat_ids")),
    "TELEGRAM_NEWS_LIMIT": (("telegram", "news_limit"),),
    "TELEGRAM_NEWS_TIMEOUT": (("telegram", "news_timeout"),),
    "TELEGRAM_MAX_SEARCH_ROUNDS": (("telegram", "max_search_rounds"),),
    "TELEGRAM_POLL_TIMEOUT": (("telegram", "poll_timeout"),),
    "TELEGRAM_AUTO_START": (("telegram", "auto_start"),),
    "TELEGRAM_DELETE_WEBHOOK_ON_START": (("telegram", "delete_webhook_on_start"),),
    "TELEGRAM_DROP_PENDING_UPDATES": (("telegram", "drop_pending_updates"),),
    "NEWS_QUERY": (("news", "query"),),
    "MAX_RESULTS": (("news", "max_results"),),
    "WORKER_SEND_TELEGRAM": (("worker", "send_telegram"),),
    "WORKER_REQUIRE_TELEGRAM": (("worker", "require_telegram"),),
    "WORKER_TELEGRAM_TITLE": (("worker", "telegram_title"),),
    "LOG_LEVEL": (("app", "log_level"),),
}


def _normalise_secret_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _streamlit_secrets_to_dict() -> dict[str, Any]:
    """Baca st.secrets bila tersedia, tanpa memaksa app harus berjalan via Streamlit."""
    try:
        import streamlit as st  # type: ignore
    except Exception:
        return {}
    try:
        if hasattr(st.secrets, "to_dict"):
            return dict(st.secrets.to_dict())
        return dict(st.secrets)
    except (FileNotFoundError, KeyError, AttributeError, RuntimeError):
        return {}
    except Exception:
        # Beberapa versi Streamlit bisa melempar exception spesifik saat runtime belum siap.
        return {}


def _local_secrets_to_dict() -> dict[str, Any]:
    """Fallback untuk menjalankan python telegram_bot.py/worker.py secara lokal.

    Streamlit Cloud menyimpan secrets lewat panel UI. Untuk lokal, file yang dibaca
    adalah `.streamlit/secrets.toml`, tetapi file asli wajib masuk `.gitignore`.
    """
    candidates = [
        Path.cwd() / ".streamlit" / "secrets.toml",
        BASE_DIR / ".streamlit" / "secrets.toml",
        Path.home() / ".streamlit" / "secrets.toml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("rb") as file:
                data = tomllib.load(file)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _combined_secrets() -> dict[str, Any]:
    combined: dict[str, Any] = {}
    # Local file dulu, lalu st.secrets menimpa jika tersedia.
    combined.update(_local_secrets_to_dict())
    combined.update(_streamlit_secrets_to_dict())
    return combined


def _mapping_get_case_insensitive(mapping: Mapping[str, Any], key: str) -> Any:
    if key in mapping:
        return mapping[key]
    lowered = key.lower()
    for candidate_key, value in mapping.items():
        if str(candidate_key).lower() == lowered:
            return value
    return None


def _section_for_name(name: str) -> tuple[str | None, str | None]:
    if name.startswith("NEWS_"):
        return "news", name.removeprefix("NEWS_").lower()
    if name.startswith("TELEGRAM_"):
        return "telegram", name.removeprefix("TELEGRAM_").lower()
    if name.startswith("JINA_"):
        return "jina", name.removeprefix("JINA_").lower()
    return None, None


def get_secret(name: str, default: str = "") -> str:
    """Ambil konfigurasi dari env, root secrets, atau section TOML.

    Prioritas: environment variable > root-level Streamlit secrets > sectioned
    Streamlit secrets, misalnya `[telegram] bot_token = "..."`.
    """
    env_value = os.getenv(name)
    if env_value not in {None, ""}:
        return str(env_value).strip()

    secrets = _combined_secrets()
    if not secrets:
        return default

    root_value = _mapping_get_case_insensitive(secrets, name)
    if root_value is None:
        root_value = _mapping_get_case_insensitive(secrets, name.lower())
    normalised = _normalise_secret_value(root_value)
    if normalised:
        return normalised

    candidates: list[tuple[str, str]] = list(SPECIAL_SECTION_ALIASES.get(name, ()))
    section, key = _section_for_name(name)
    if section and key:
        candidates.append((section, key))

    for section_name, key_name in candidates:
        section_value = _mapping_get_case_insensitive(secrets, section_name)
        if not isinstance(section_value, Mapping):
            continue
        value = _mapping_get_case_insensitive(section_value, key_name)
        normalised = _normalise_secret_value(value)
        if normalised:
            return normalised
    return default


def get_secret_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = get_secret(name, "")
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def get_secret_bool(name: str, default: bool = False) -> bool:
    raw = get_secret(name, "")
    if raw == "":
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def apply_secrets_to_environment(names: tuple[str, ...] = CONFIG_ENV_NAMES, *, overwrite: bool = False) -> None:
    """Salin secret ke os.environ agar modul lama yang membaca env tetap kompatibel."""
    for name in names:
        if not overwrite and os.getenv(name) not in {None, ""}:
            continue
        value = get_secret(name, "")
        if value:
            os.environ[name] = value


def has_secret(name: str) -> bool:
    return bool(get_secret(name, ""))
