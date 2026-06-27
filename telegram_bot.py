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
from news_service import build_jina_reader_url, build_text_only_reader_url, fetch_news
from storage import read_json, write_json

LOGGER = logging.getLogger(__name__)
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
SAFE_MESSAGE_LENGTH = 3800
DEFAULT_NEWS_LIMIT = 5
DEFAULT_POLL_TIMEOUT = 30
BASE_DIR = Path(__file__).resolve().parent
TELEGRAM_UPDATE_STATE_PATH = BASE_DIR / "data" / "telegram_updates_state.json"
MAX_STORED_TELEGRAM_UPDATES = 600


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
    app_url = get_secret("STREAMLIT_APP_URL", "") or get_secret("PUBLIC_APP_URL", "")
    text_reader_url = build_text_only_reader_url(url, app_url)
    jina_reader_url = build_jina_reader_url(url)
    safe_url = html.escape(url, quote=True)
    safe_text_url = html.escape(text_reader_url, quote=True)
    has_internal_text_reader = bool(app_url and text_reader_url and text_reader_url != jina_reader_url)

    lines = [
        f"<b>{index}. {title}</b>",
        f"📝 Konten: {summary}",
        f"🏷️ {source} • {published_at}",
    ]
    if url.startswith(("http://", "https://")):
        if text_reader_url:
            label = "Buka teks bersih (TXT)" if has_internal_text_reader else "Buka teks Jina"
            lines.append(f'🧹 <a href="{safe_text_url}">{label}</a>')
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
        response = self.session.post(self.api_url(method), json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok", False):
            raise RuntimeError(f"Telegram API error pada {method}: {data}")
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
        response = self.session.post(
            self.api_url("getUpdates"),
            json=payload,
            timeout=poll_timeout + 10,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok", False):
            raise RuntimeError(f"Telegram API error pada getUpdates: {data}")
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

    def handle_text(self, chat_id: int, text: str) -> None:
        LOGGER.info("Pesan dari chat_id=%s: %s", chat_id, text)
        if not chat_is_allowed(chat_id, self.allowed_chat_ids):
            self.send_message(chat_id, "Maaf, chat ini belum diizinkan memakai bot berita ini.")
            return

        stripped = (text or "").strip()
        if re.match(r"^/(?:start|help)(?:@[A-Za-z0-9_]+)?$", stripped, re.IGNORECASE):
            self.send_message(chat_id, HELP_TEXT)
            return

        theme = normalise_theme(stripped)
        if not theme:
            self.send_message(chat_id, HELP_TEXT)
            return

        self.send_typing(chat_id)
        try:
            articles, metadata = fetch_news(
                self.jina_api_key,
                query=theme,
                max_results=self.news_limit,
                timeout=self.request_timeout,
                max_search_rounds=self.max_search_rounds,
            )
        except ValueError as error:
            self.send_message(
                chat_id,
                f"Konfigurasi belum lengkap: {_escape(error)}\n\n"
                "Atur <code>JINA_API_KEY</code> jika ingin fallback Jina Search dan scrape artikel aktif.",
            )
            return
        except requests.RequestException as error:
            self.send_message(chat_id, f"Gagal mengambil berita karena koneksi/API bermasalah: {_escape(error)}")
            return
        except Exception as error:  # pragma: no cover - perlindungan runtime.
            LOGGER.exception("Gagal memproses tema berita")
            self.send_message(chat_id, f"Gagal memproses berita untuk tema ini: {_escape(error)}")
            return

        for message in build_news_messages(theme, articles[: self.news_limit], metadata):
            self.send_message(chat_id, message)

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
            except Exception as error:
                LOGGER.exception("Polling Telegram gagal: %s", error)
                if status_callback:
                    status_callback("error", f"Polling Telegram gagal: {error}")
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
