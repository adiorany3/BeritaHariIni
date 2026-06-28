"""Telegram bot interaktif untuk mencari berita berdasarkan tema yang dikirim user.

User cukup mengirim tema seperti "harga telur" atau "/berita harga telur".
Bot akan membalas judul, konten hasil scrape, link teks bersih TXT, dan link asli artikel.

Bot ini memakai long polling agar mudah dijalankan di VPS/Render/Railway/GitHub Codespaces,
tanpa perlu menyiapkan webhook publik.
"""
from __future__ import annotations

import html
import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event, RLock
from typing import Any

import requests

from config import apply_secrets_to_environment, get_secret, get_secret_bool, get_secret_int
from news_service import build_text_only_reader_url, fetch_news, jina_api_key_count
from storage import read_json, write_json

LOGGER = logging.getLogger(__name__)
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
SAFE_MESSAGE_LENGTH = 3800
DEFAULT_NEWS_LIMIT = 5
DEFAULT_POLL_TIMEOUT = 30
# Fallback khusus project ini agar link TXT bersih tetap muncul di Telegram
# walaupun secret GitHub Actions belum diisi. Tetap disarankan mengisi
# STREAMLIT_APP_URL/TELEGRAM_TEXT_READER_APP_URL di Secrets.
DEFAULT_TEXT_READER_APP_URL = "https://beritaterbaru.streamlit.app"
BASE_DIR = Path(__file__).resolve().parent
TELEGRAM_UPDATE_STATE_PATH = BASE_DIR / "data" / "telegram_updates_state.json"
TELEGRAM_SUBSCRIPTIONS_PATH = BASE_DIR / "data" / "telegram_subscriptions.json"
MAX_STORED_TELEGRAM_UPDATES = 600
MAX_TOPICS_PER_CHAT = 12


class TelegramPollingConflict(RuntimeError):
    """Raised when Telegram rejects getUpdates because another polling client is active."""


_TELEGRAM_TOKEN_PATTERNS = (
    re.compile(r"/bot[^/\s]+/"),
    re.compile(r"bot\d+:[A-Za-z0-9_-]+"),
)


def redact_sensitive(value: Any) -> str:
    """Hilangkan token/secret dari pesan error sebelum masuk UI/log.

    requests.HTTPError dari Telegram sering membawa URL lengkap seperti
    https://api.telegram.org/bot<TOKEN>/getUpdates. Pesan seperti itu tidak
    boleh tampil di Streamlit, Telegram, maupun GitHub logs.
    """
    text = str(value or "")
    for pattern in _TELEGRAM_TOKEN_PATTERNS:
        text = pattern.sub(lambda match: match.group(0).replace(match.group(0), "/bot<REDACTED>/") if match.group(0).startswith('/bot') else "bot<REDACTED>", text)
    # Jaga-jaga untuk token yang sudah terlanjur dimasking GitHub atau format lain.
    text = re.sub(r"https://api\.telegram\.org/bot[^\s]+", "https://api.telegram.org/bot<REDACTED>", text)
    return text


def _telegram_http_error_message(method: str, error: requests.HTTPError) -> str:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if status == 409 and method == "getUpdates":
        return (
            "Polling Telegram dihentikan karena ada instance bot lain yang sedang aktif. "
            "Matikan auto_start di salah satu deploy, hentikan worker/VPS lain, atau pastikan hanya satu proses yang menjalankan getUpdates."
        )
    if status:
        return f"Telegram API {method} gagal dengan HTTP {status}."
    return f"Telegram API {method} gagal."


HELP_TEXT = """📰 <b>Bot Berita Hari Ini</b>

Kirim tema berita, nanti bot akan mencari artikel hari ini dan membalas:
• judul
• konten hasil scrape artikel
• link teks bersih TXT dan link berita asli

Contoh:
<code>harga telur</code>
<code>mobil listrik</code>
<code>/berita AI pendidikan</code>

Perintah:
/start - mulai
/help - bantuan
/cari <tema> - cari berita sekarang
/pagi - kirim berita dari topik langganan sekarang
/topik <tema> - simpan topik langganan harian
/topikku - lihat topik langganan
/hapus <tema> - hapus topik, atau /hapus semua
/limit <1-10> - atur jumlah berita per topik
/status - cek status bot dan konfigurasi
""".strip()


def parse_allowed_chat_ids(value: str | None) -> set[int]:
    """Parse TELEGRAM_ALLOWED_CHAT_IDS="123,456" menjadi set int.

    Kosong berarti semua chat diizinkan. Ini memudahkan testing pribadi dulu, lalu
    bisa dikunci setelah chat_id diketahui dari log.
    """
    if not value:
        return set()
    allowed: set[int] = set()
    for part in re.split(r"[,\s]+", value.strip()):
        if not part:
            continue
        try:
            allowed.add(int(part))
        except ValueError:
            LOGGER.warning("Mengabaikan TELEGRAM_ALLOWED_CHAT_IDS tidak valid: %s", part)
    return allowed


def chat_is_allowed(chat_id: int, allowed_chat_ids: set[int]) -> bool:
    return not allowed_chat_ids or chat_id in allowed_chat_ids


def normalise_theme(text: str) -> str:
    """Ambil tema dari pesan Telegram.

    Mendukung teks langsung, /berita <tema>, /cari <tema>, dan mengabaikan mention bot
    seperti /berita@NamaBot <tema>.
    """
    cleaned = (text or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    command_match = re.match(r"^/(?:berita|cari|news)(?:@[A-Za-z0-9_]+)?(?:\s+(.+))?$", cleaned, re.IGNORECASE)
    if command_match:
        cleaned = (command_match.group(1) or "").strip()
    if cleaned.startswith("/"):
        return ""
    # Batasi agar query tidak terlalu panjang dan tidak disalahgunakan sebagai payload besar.
    return cleaned[:180]


def _escape(value: Any) -> str:
    return html.escape(str(value or "").strip(), quote=True)


def _compact(value: Any, limit: int = 520) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _normalise_app_base_url(value: str) -> str:
    """Rapikan URL app untuk link TXT bersih Telegram."""
    text = (value or "").strip().strip('"\'')
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = f"https://{text}"
    return text.rstrip("/")


def _telegram_text_reader_app_url() -> str:
    """URL publik aplikasi untuk link TXT bersih di Telegram.

    Jangan fallback ke `r.jina.ai` mentah untuk tombol TXT bersih, karena link
    langsung tersebut tidak membawa header pembersih dan masih bisa menampilkan
    markdown gambar seperti `![Image ...]`. GitHub Actions tidak bisa membaca
    Streamlit Secrets, jadi fungsi ini menerima banyak nama secret/variable dan
    memakai default project bila semuanya kosong.
    """
    candidates = (
        get_secret("TELEGRAM_TEXT_READER_APP_URL", ""),
        get_secret("TEXT_READER_APP_URL", ""),
        get_secret("STREAMLIT_APP_URL", ""),
        get_secret("PUBLIC_APP_URL", ""),
        get_secret("APP_URL", ""),
        get_secret("STREAMLIT_URL", ""),
        DEFAULT_TEXT_READER_APP_URL,
    )
    for candidate in candidates:
        normalised = _normalise_app_base_url(candidate)
        if normalised:
            return normalised
    return ""




def _normalise_topic(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:120]


def _load_subscription_state(path: str | Path | None = None) -> dict[str, Any]:
    path = path or TELEGRAM_SUBSCRIPTIONS_PATH
    payload = read_json(path, {"chats": {}})
    if not isinstance(payload, dict):
        return {"chats": {}}
    chats = payload.get("chats")
    if not isinstance(chats, dict):
        chats = {}
    normalised: dict[str, Any] = {"chats": {}}
    for chat_id, value in chats.items():
        if not isinstance(value, dict):
            continue
        topics = [_normalise_topic(topic) for topic in value.get("topics", []) if _normalise_topic(topic)]
        limit = value.get("limit", DEFAULT_NEWS_LIMIT)
        try:
            limit = max(1, min(int(limit), 10))
        except (TypeError, ValueError):
            limit = DEFAULT_NEWS_LIMIT
        normalised["chats"][str(chat_id)] = {
            "topics": topics[:MAX_TOPICS_PER_CHAT],
            "limit": limit,
            "updated_at": value.get("updated_at", ""),
        }
    return normalised


def _save_subscription_state(state: dict[str, Any], path: str | Path | None = None) -> None:
    write_json(path or TELEGRAM_SUBSCRIPTIONS_PATH, state)


def get_chat_subscription(chat_id: int, *, path: str | Path | None = None) -> dict[str, Any]:
    state = _load_subscription_state(path)
    value = state.get("chats", {}).get(str(chat_id), {})
    if not isinstance(value, dict):
        return {"topics": [], "limit": DEFAULT_NEWS_LIMIT}
    return {"topics": list(value.get("topics", [])), "limit": int(value.get("limit", DEFAULT_NEWS_LIMIT) or DEFAULT_NEWS_LIMIT)}


def list_subscription_targets(*, path: str | Path | None = None) -> dict[int, dict[str, Any]]:
    """Return chat_id -> {topics, limit} untuk worker pagi GitHub Actions."""
    state = _load_subscription_state(path)
    result: dict[int, dict[str, Any]] = {}
    for raw_chat_id, value in state.get("chats", {}).items():
        try:
            chat_id = int(raw_chat_id)
        except (TypeError, ValueError):
            continue
        topics = [topic for topic in value.get("topics", []) if topic]
        if not topics:
            continue
        result[chat_id] = {"topics": topics[:MAX_TOPICS_PER_CHAT], "limit": int(value.get("limit", DEFAULT_NEWS_LIMIT) or DEFAULT_NEWS_LIMIT)}
    return result


def add_subscription_topic(chat_id: int, topic: str, *, path: str | Path | None = None) -> tuple[bool, list[str]]:
    topic = _normalise_topic(topic)
    if not topic:
        return False, get_chat_subscription(chat_id, path=path)["topics"]
    state = _load_subscription_state(path)
    chats = state.setdefault("chats", {})
    current = chats.setdefault(str(chat_id), {"topics": [], "limit": DEFAULT_NEWS_LIMIT})
    topics = [_normalise_topic(item) for item in current.get("topics", []) if _normalise_topic(item)]
    if any(item.casefold() == topic.casefold() for item in topics):
        return False, topics
    topics.append(topic)
    current["topics"] = topics[-MAX_TOPICS_PER_CHAT:]
    current["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _save_subscription_state(state, path)
    return True, current["topics"]


def remove_subscription_topic(chat_id: int, topic: str, *, path: str | Path | None = None) -> tuple[int, list[str]]:
    topic = _normalise_topic(topic)
    state = _load_subscription_state(path)
    chats = state.setdefault("chats", {})
    current = chats.setdefault(str(chat_id), {"topics": [], "limit": DEFAULT_NEWS_LIMIT})
    topics = [_normalise_topic(item) for item in current.get("topics", []) if _normalise_topic(item)]
    if topic.casefold() in {"semua", "all", "*"}:
        removed = len(topics)
        topics = []
    else:
        before = len(topics)
        topics = [item for item in topics if item.casefold() != topic.casefold()]
        removed = before - len(topics)
    current["topics"] = topics
    current["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _save_subscription_state(state, path)
    return removed, topics


def set_subscription_limit(chat_id: int, limit: int, *, path: str | Path | None = None) -> int:
    limit = max(1, min(int(limit), 10))
    state = _load_subscription_state(path)
    current = state.setdefault("chats", {}).setdefault(str(chat_id), {"topics": [], "limit": DEFAULT_NEWS_LIMIT})
    current["limit"] = limit
    current["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _save_subscription_state(state, path)
    return limit


def format_article(article: dict[str, Any], index: int) -> str:
    title = _escape(_compact(article.get("title") or "Tanpa judul", 180))
    # Output Telegram memakai konten hasil scrape saja.
    # Deskripsi RSS/SERP tidak dijadikan isi utama agar bot tidak mengirim preview dangkal/iklan.
    scraped_info = article.get("scraped_info") or ""
    summary = _escape(
        _compact(
            scraped_info
            or "Konten artikel belum berhasil di-scrape. Buka link teks bersih/TXT atau buka link asli.",
            650,
        )
    )
    source = _escape(article.get("source") or "sumber tidak diketahui")
    published_at = _escape(article.get("published_at") or "waktu tidak diketahui")
    url = str(article.get("url") or "").strip()
    app_url = _telegram_text_reader_app_url()
    text_reader_url = build_text_only_reader_url(url, app_url) if app_url else ""
    safe_url = html.escape(url, quote=True)
    safe_text_url = html.escape(text_reader_url, quote=True)

    lines = [
        f"<b>{index}. {title}</b>",
        f"📝 Konten: {summary}",
        f"🏷️ {source} • {published_at}",
    ]
    validity = article.get("validity_status")
    validity_score = article.get("validity_score")
    if validity:
        lines.append(f"🔎 Validitas: {_escape(validity)}" + (f" ({_escape(validity_score)}/100)" if validity_score not in {None, ''} else ""))
    structured = article.get("structured_info")
    if isinstance(structured, dict) and structured.get("highlights"):
        highlights = "; ".join(str(item) for item in structured.get("highlights", [])[:3])
        lines.append(f"📌 Fakta: {_escape(_compact(highlights, 360))}")
    supporting = article.get("supporting_sources")
    if isinstance(supporting, list) and len(supporting) > 1:
        lines.append(f"🧾 Sumber terkait: {_escape(', '.join(map(str, supporting[:4])))}")
    if url.startswith(("http://", "https://")):
        if text_reader_url:
            lines.append(f'🧹 <a href="{safe_text_url}">Buka teks bersih (TXT)</a>')
        else:
            lines.append("🧹 Link TXT bersih belum aktif. Isi STREAMLIT_APP_URL atau TELEGRAM_TEXT_READER_APP_URL.")
        lines.append(f'🔗 <a href="{safe_url}">Buka berita asli</a>')
    return "\n".join(lines)


def build_news_messages(theme: str, articles: list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> list[str]:
    """Bangun satu atau beberapa pesan Telegram berisi judul, ringkasan, dan link."""
    metadata = metadata or {}
    theme_escaped = _escape(theme)
    if not articles:
        return [
            f"Belum menemukan artikel hari ini yang relevan untuk <b>{theme_escaped}</b>.\n\n"
            "Coba tema yang lebih spesifik, misalnya <code>harga telur ayam Jakarta</code> atau "
            "<code>mobil listrik subsidi</code>."
        ]

    header = f"📰 <b>Berita hari ini: {theme_escaped}</b>\n"
    scraped = metadata.get("article_scrape_success")
    attempted = metadata.get("article_scrape_attempted")
    if scraped is not None and attempted is not None:
        header += f"<i>Konten diambil dari isi artikel: {html.escape(str(scraped))}/{html.escape(str(attempted))}</i>\n"
    header += "\n"

    messages: list[str] = []
    current = header
    for index, article in enumerate(articles, start=1):
        block = format_article(article, index)
        separator = "\n\n"
        if len(current) + len(separator) + len(block) > SAFE_MESSAGE_LENGTH:
            messages.append(current.rstrip())
            current = block
        else:
            current += separator + block if current.strip() != header.strip() else block
    if current.strip():
        messages.append(current.rstrip())
    return messages




class TelegramUpdateDeduper:
    """Dedupe update/message Telegram agar restart/rerun tidak memproses pesan yang sama berkali-kali."""

    def __init__(self, path: str | Path = TELEGRAM_UPDATE_STATE_PATH, *, enabled: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self._lock = RLock()

    def _load(self) -> dict[str, Any]:
        payload = read_json(self.path, {"processed": []})
        if not isinstance(payload, dict):
            return {"processed": []}
        processed = payload.get("processed")
        if not isinstance(processed, list):
            processed = []
        return {"processed": [item for item in processed if isinstance(item, dict)]}

    def _save(self, payload: dict[str, Any]) -> None:
        payload["processed"] = payload.get("processed", [])[-MAX_STORED_TELEGRAM_UPDATES:]
        write_json(self.path, payload)

    @staticmethod
    def update_key(update: dict[str, Any]) -> str:
        update_id = update.get("update_id")
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        message_id = message.get("message_id")
        if chat_id is not None and message_id is not None:
            return f"message:{chat_id}:{message_id}"
        return f"update:{update_id}"

    def claim(self, update: dict[str, Any]) -> bool:
        """Return True bila update baru berhasil diklaim untuk diproses."""
        if not self.enabled:
            return True
        key = self.update_key(update)
        with self._lock:
            payload = self._load()
            if any(item.get("key") == key for item in payload.get("processed", [])):
                return False
            payload.setdefault("processed", []).append(
                {"key": key, "claimed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            )
            self._save(payload)
            return True


class TelegramNewsBot:
    def __init__(
        self,
        *,
        token: str,
        jina_api_key: str,
        allowed_chat_ids: set[int] | None = None,
        news_limit: int = DEFAULT_NEWS_LIMIT,
        request_timeout: int | None = None,
        max_search_rounds: int | None = None,
        session: requests.Session | None = None,
        dedupe_updates: bool = True,
        update_state_path: str | Path = TELEGRAM_UPDATE_STATE_PATH,
    ) -> None:
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN belum diatur.")
        self.token = token
        self.jina_api_key = jina_api_key
        self.allowed_chat_ids = allowed_chat_ids or set()
        self.news_limit = max(1, min(news_limit, 10))
        self.request_timeout = request_timeout
        self.max_search_rounds = max_search_rounds
        self.session = session or requests.Session()
        self.update_deduper = TelegramUpdateDeduper(update_state_path, enabled=dedupe_updates)

    def api_url(self, method: str) -> str:
        return TELEGRAM_API_BASE.format(token=self.token, method=method)

    def request(self, method: str, payload: dict[str, Any], *, timeout: int = 30) -> dict[str, Any]:
        try:
            response = self.session.post(self.api_url(method), json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as error:
            raise RuntimeError(_telegram_http_error_message(method, error)) from None
        except requests.RequestException as error:
            raise RuntimeError(redact_sensitive(f"Telegram API {method} gagal: {error}")) from None
        except ValueError:
            raise RuntimeError(f"Telegram API {method} mengembalikan respons yang tidak valid.") from None
        if not data.get("ok", False):
            raise RuntimeError(redact_sensitive(f"Telegram API error pada {method}: {data}"))
        return data

    def get_me(self) -> dict[str, Any]:
        """Validasi token dan ambil info bot tanpa menampilkan token."""
        return self.request("getMe", {}, timeout=10)

    def get_webhook_info(self) -> dict[str, Any]:
        """Cek apakah token masih tersambung ke webhook.

        Telegram hanya mengizinkan salah satu: webhook atau getUpdates. Jika webhook
        masih aktif dari deploy sebelumnya, long polling tidak akan menerima pesan.
        """
        return self.request("getWebhookInfo", {}, timeout=10)

    def delete_webhook(self, *, drop_pending_updates: bool = False) -> dict[str, Any]:
        """Matikan webhook supaya long polling/getUpdates bisa menerima pesan."""
        return self.request(
            "deleteWebhook",
            {"drop_pending_updates": bool(drop_pending_updates)},
            timeout=10,
        )

    def get_updates(self, offset: int | None, poll_timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": poll_timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        try:
            response = self.session.post(
                self.api_url("getUpdates"),
                json=payload,
                timeout=poll_timeout + 10,
            )
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as error:
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", None)
            message = _telegram_http_error_message("getUpdates", error)
            if status == 409:
                raise TelegramPollingConflict(message) from None
            raise RuntimeError(message) from None
        except requests.RequestException as error:
            raise RuntimeError(redact_sensitive(f"Telegram getUpdates gagal: {error}")) from None
        except ValueError:
            raise RuntimeError("Telegram getUpdates mengembalikan respons yang tidak valid.") from None
        if not data.get("ok", False):
            description = str(data.get("description") or "")
            if "conflict" in description.casefold() or data.get("error_code") == 409:
                raise TelegramPollingConflict(
                    "Polling Telegram dihentikan karena ada instance bot lain yang sedang aktif. "
                    "Matikan auto_start di salah satu deploy, hentikan worker/VPS lain, atau pastikan hanya satu proses yang menjalankan getUpdates."
                )
            raise RuntimeError(redact_sensitive(f"Telegram API error pada getUpdates: {data}"))
        return list(data.get("result") or [])

    def send_message(self, chat_id: int, text: str) -> None:
        # Telegram membatasi 4096 karakter. build_news_messages sudah menjaga ukuran,
        # tetapi potong defensif jika ada karakter tak terduga.
        chunks = [text[i:i + MAX_TELEGRAM_MESSAGE_LENGTH] for i in range(0, len(text), MAX_TELEGRAM_MESSAGE_LENGTH)] or [""]
        for chunk in chunks:
            self.request(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )

    def send_typing(self, chat_id: int) -> None:
        try:
            self.request("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=10)
        except Exception as error:  # pragma: no cover - non-kritis, jangan hentikan bot.
            LOGGER.debug("Gagal mengirim typing action: %s", error)

    def _search_and_send(self, chat_id: int, theme: str, *, header_theme: str | None = None, limit: int | None = None) -> None:
        self.send_typing(chat_id)
        try:
            articles, metadata = fetch_news(
                self.jina_api_key,
                query=theme,
                max_results=limit or self.news_limit,
                timeout=self.request_timeout,
                max_search_rounds=self.max_search_rounds,
            )
        except ValueError as error:
            self.send_message(
                chat_id,
                f"Konfigurasi belum lengkap: {_escape(error)}\n\n"
                "Atur <code>JINA_API_KEY</code> atau <code>JINA_API_KEYS</code> jika ingin fallback Jina Search dan scrape artikel aktif.",
            )
            return
        except requests.RequestException as error:
            self.send_message(chat_id, f"Gagal mengambil berita karena koneksi/API bermasalah: {_escape(error)}")
            return
        except Exception as error:  # pragma: no cover - perlindungan runtime.
            LOGGER.exception("Gagal memproses tema berita")
            self.send_message(chat_id, f"Gagal memproses berita untuk tema ini: {_escape(error)}")
            return

        effective_limit = limit or self.news_limit
        for message in build_news_messages(header_theme or theme, articles[:effective_limit], metadata):
            self.send_message(chat_id, message)

    def handle_text(self, chat_id: int, text: str) -> None:
        LOGGER.info("Pesan dari chat_id=%s: %s", chat_id, text)
        if not chat_is_allowed(chat_id, self.allowed_chat_ids):
            self.send_message(chat_id, "Maaf, chat ini belum diizinkan memakai bot berita ini.")
            return

        stripped = (text or "").strip()
        if re.match(r"^/(?:start|help)(?:@[A-Za-z0-9_]+)?$", stripped, re.IGNORECASE):
            self.send_message(chat_id, HELP_TEXT)
            return

        if re.match(r"^/status(?:@[A-Za-z0-9_]+)?$", stripped, re.IGNORECASE):
            subscription = get_chat_subscription(chat_id)
            topics = subscription.get("topics", [])
            txt_url = _telegram_text_reader_app_url()
            lines = [
                "✅ <b>Status Bot Berita</b>",
                f"Jina API: {'✅ ' + str(jina_api_key_count(self.jina_api_key)) + ' key tersedia' if jina_api_key_count(self.jina_api_key) else '⚠️ belum diatur'}",
                f"Link TXT bersih: {'✅ aktif' if txt_url else '⚠️ belum aktif'}",
                f"Limit berita/chat: {subscription.get('limit', self.news_limit)}",
                f"Topik langganan: {len(topics)}",
            ]
            if topics:
                lines.append("\n" + "\n".join(f"• {_escape(topic)}" for topic in topics))
            self.send_message(chat_id, "\n".join(lines))
            return

        topik_match = re.match(r"^/topik(?:@[A-Za-z0-9_]+)?\s+(.+)$", stripped, re.IGNORECASE)
        if topik_match:
            topic = normalise_theme(topik_match.group(1))
            added, topics = add_subscription_topic(chat_id, topic)
            status = "ditambahkan" if added else "sudah ada"
            self.send_message(chat_id, f"Topik <b>{_escape(topic)}</b> {status}.\n\nTopik aktif:\n" + "\n".join(f"• {_escape(item)}" for item in topics))
            return

        if re.match(r"^/topikku(?:@[A-Za-z0-9_]+)?$", stripped, re.IGNORECASE):
            subscription = get_chat_subscription(chat_id)
            topics = subscription.get("topics", [])
            if not topics:
                self.send_message(chat_id, "Belum ada topik langganan. Tambahkan dengan <code>/topik harga telur</code>.")
            else:
                self.send_message(chat_id, "📌 <b>Topik langganan</b>\n" + "\n".join(f"• {_escape(item)}" for item in topics))
            return

        hapus_match = re.match(r"^/hapus(?:@[A-Za-z0-9_]+)?\s+(.+)$", stripped, re.IGNORECASE)
        if hapus_match:
            topic = hapus_match.group(1).strip()
            removed, topics = remove_subscription_topic(chat_id, topic)
            if removed:
                suffix = "\n\nSisa topik:\n" + "\n".join(f"• {_escape(item)}" for item in topics) if topics else "\n\nTidak ada topik tersisa."
                self.send_message(chat_id, f"Berhasil menghapus {removed} topik.{suffix}")
            else:
                self.send_message(chat_id, "Topik tidak ditemukan. Cek daftar dengan <code>/topikku</code>.")
            return

        limit_match = re.match(r"^/limit(?:@[A-Za-z0-9_]+)?\s+(\d{1,2})$", stripped, re.IGNORECASE)
        if limit_match:
            value = set_subscription_limit(chat_id, int(limit_match.group(1)))
            self.send_message(chat_id, f"Limit berita untuk chat ini disetel ke <b>{value}</b> per topik.")
            return

        pagi_match = re.match(r"^/pagi(?:@[A-Za-z0-9_]+)?(?:\s+(.+))?$", stripped, re.IGNORECASE)
        if pagi_match:
            requested = normalise_theme(pagi_match.group(1) or "")
            subscription = get_chat_subscription(chat_id)
            topics = [requested] if requested else subscription.get("topics", [])
            limit = int(subscription.get("limit", self.news_limit) or self.news_limit)
            if not topics:
                self.send_message(chat_id, "Belum ada topik langganan. Tambahkan dulu, contoh: <code>/topik harga telur</code>, atau pakai <code>/pagi AI gambar</code>.")
                return
            for topic in topics[:MAX_TOPICS_PER_CHAT]:
                self._search_and_send(chat_id, topic, header_theme=f"Pagi ini - {topic}", limit=limit)
            return

        theme = normalise_theme(stripped)
        if not theme:
            self.send_message(chat_id, HELP_TEXT)
            return

        self._search_and_send(chat_id, theme)

    def handle_update(self, update: dict[str, Any]) -> bool:
        if not self.update_deduper.claim(update):
            LOGGER.info("Update Telegram dilewati karena sudah pernah diproses: %s", update.get("update_id"))
            return False
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = message.get("text") or ""
        if chat_id is None or not text:
            return False
        self.handle_text(int(chat_id), text)
        return True

    def run_polling(
        self,
        poll_timeout: int = DEFAULT_POLL_TIMEOUT,
        *,
        stop_event: Event | None = None,
        status_callback: Callable[[str, str], None] | None = None,
        delete_webhook_on_start: bool = True,
        drop_pending_updates: bool = False,
    ) -> None:
        """Jalankan long polling.

        `stop_event` dan `status_callback` membuat fungsi ini aman dipakai sebagai
        background thread di Streamlit, selain tetap bisa dijalankan langsung lewat
        `python telegram_bot.py`.
        """
        offset: int | None = None
        if delete_webhook_on_start:
            try:
                self.delete_webhook(drop_pending_updates=drop_pending_updates)
                if status_callback:
                    status_callback("webhook_deleted", "Webhook Telegram dimatikan; bot memakai long polling.")
            except Exception as error:
                LOGGER.warning("Gagal deleteWebhook: %s", error)
                if status_callback:
                    status_callback("warning", f"Gagal deleteWebhook: {error}")
        LOGGER.info("Telegram bot aktif. Menunggu pesan...")
        if status_callback:
            status_callback("running", "Bot aktif dan menunggu pesan Telegram.")
        while stop_event is None or not stop_event.is_set():
            try:
                updates = self.get_updates(offset, poll_timeout)
                if updates and status_callback:
                    status_callback("updates", f"Menerima {len(updates)} update dari Telegram.")
                for update in updates:
                    update_id = int(update.get("update_id", 0))
                    offset = update_id + 1
                    processed = self.handle_update(update)
                    if status_callback:
                        if processed:
                            status_callback("processed", f"Update {update_id} selesai diproses.")
                        else:
                            status_callback("skipped", f"Update {update_id} dilewati karena duplikat/kosong.")
            except KeyboardInterrupt:
                LOGGER.info("Telegram bot dihentikan.")
                return
            except TelegramPollingConflict as error:
                safe_message = redact_sensitive(error)
                LOGGER.warning("Polling Telegram konflik: %s", safe_message)
                if status_callback:
                    status_callback("conflict", safe_message)
                return
            except Exception as error:
                safe_message = redact_sensitive(error)
                LOGGER.error("Polling Telegram gagal: %s", safe_message)
                if status_callback:
                    status_callback("error", f"Polling Telegram gagal: {safe_message}")
                time.sleep(3)
        LOGGER.info("Telegram bot stop_event diterima.")
        if status_callback:
            status_callback("stopped", "Bot dihentikan dari aplikasi Streamlit.")


def create_bot_from_env() -> TelegramNewsBot:
    # Bisa membaca dari env, root-level Streamlit Secrets, atau section [telegram]/[jina]/[news].
    apply_secrets_to_environment()
    token = get_secret("TELEGRAM_BOT_TOKEN", "")
    jina_api_key = get_secret("JINA_API_KEY", "")
    allowed_chat_ids = parse_allowed_chat_ids(get_secret("TELEGRAM_ALLOWED_CHAT_IDS", ""))
    news_limit = get_secret_int("TELEGRAM_NEWS_LIMIT", DEFAULT_NEWS_LIMIT, minimum=1, maximum=10)
    request_timeout = get_secret_int("TELEGRAM_NEWS_TIMEOUT", 25, minimum=5, maximum=60)
    max_search_rounds_raw = get_secret("TELEGRAM_MAX_SEARCH_ROUNDS", "")
    if max_search_rounds_raw:
        max_search_rounds = get_secret_int("TELEGRAM_MAX_SEARCH_ROUNDS", 2, minimum=0, maximum=3)
    else:
        max_search_rounds = None
    dedupe_updates = get_secret_bool("TELEGRAM_DEDUPE_UPDATES", True)
    return TelegramNewsBot(
        token=token,
        jina_api_key=jina_api_key,
        allowed_chat_ids=allowed_chat_ids,
        news_limit=news_limit,
        request_timeout=request_timeout,
        max_search_rounds=max_search_rounds,
        dedupe_updates=dedupe_updates,
    )


def main() -> None:
    logging.basicConfig(level=get_secret("LOG_LEVEL", "INFO"), format="%(levelname)s: %(message)s")
    bot = create_bot_from_env()
    poll_timeout = get_secret_int("TELEGRAM_POLL_TIMEOUT", DEFAULT_POLL_TIMEOUT, minimum=5, maximum=50)
    delete_webhook_on_start = get_secret_bool("TELEGRAM_DELETE_WEBHOOK_ON_START", True)
    drop_pending_updates = get_secret_bool("TELEGRAM_DROP_PENDING_UPDATES", False)
    bot.run_polling(
        poll_timeout=poll_timeout,
        delete_webhook_on_start=delete_webhook_on_start,
        drop_pending_updates=drop_pending_updates,
    )


if __name__ == "__main__":
    main()
