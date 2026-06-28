"""Runtime Telegram Bot untuk Streamlit Cloud.

Streamlit Community Cloud menjalankan `app.py`, bukan `telegram_bot.py`.
Modul ini menyalakan long-polling bot di background thread ketika app aktif.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, asdict
from typing import Any

from config import get_secret_bool, get_secret_int
from telegram_bot import DEFAULT_POLL_TIMEOUT, create_bot_from_env, redact_sensitive


@dataclass
class TelegramRuntimeStatus:
    running: bool = False
    started_at: float | None = None
    stopped_at: float | None = None
    last_event: str = "belum dimulai"
    last_error: str = ""
    updates_processed: int = 0
    thread_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.started_at:
            data["started_at_text"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started_at))
        else:
            data["started_at_text"] = "-"
        if self.stopped_at:
            data["stopped_at_text"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.stopped_at))
        else:
            data["stopped_at_text"] = "-"
        return data


class StreamlitTelegramRuntime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = TelegramRuntimeStatus()

    def status(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._status.running = True
            return self._status.to_dict()

    def _set_event(self, event: str, message: str) -> None:
        safe_message = redact_sensitive(message)
        with self._lock:
            self._status.last_event = safe_message or event
            if event == "error":
                self._status.last_error = safe_message
            elif event == "conflict":
                self._status.last_error = safe_message
            elif event in {"running", "webhook_deleted", "processed", "updates"}:
                # Jangan hapus warning/error lama sampai ada event sukses yang berarti.
                if event in {"processed", "running"}:
                    self._status.last_error = ""
            if event == "processed":
                self._status.updates_processed += 1

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._status.running = True
                return self._status.to_dict()
            self._stop_event.clear()
            self._status = TelegramRuntimeStatus(
                running=True,
                started_at=time.time(),
                stopped_at=None,
                last_event="menyiapkan bot Telegram...",
                last_error="",
                updates_processed=0,
                thread_name="telegram-news-bot",
            )
            self._thread = threading.Thread(
                target=self._run,
                name="telegram-news-bot",
                daemon=True,
            )
            self._thread.start()
            return self._status.to_dict()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_event.set()
            self._status.running = False
            self._status.stopped_at = time.time()
            self._status.last_event = "permintaan stop dikirim ke bot"
            return self._status.to_dict()

    def _run(self) -> None:
        try:
            bot = create_bot_from_env()
            poll_timeout = get_secret_int("TELEGRAM_POLL_TIMEOUT", DEFAULT_POLL_TIMEOUT, minimum=5, maximum=50)
            delete_webhook_on_start = get_secret_bool("TELEGRAM_DELETE_WEBHOOK_ON_START", True)
            drop_pending_updates = get_secret_bool("TELEGRAM_DROP_PENDING_UPDATES", False)
            bot.run_polling(
                poll_timeout=poll_timeout,
                stop_event=self._stop_event,
                status_callback=self._set_event,
                delete_webhook_on_start=delete_webhook_on_start,
                drop_pending_updates=drop_pending_updates,
            )
        except Exception as error:  # pragma: no cover - safety net runtime.
            self._set_event("error", f"Bot gagal start: {redact_sensitive(error)}")
        finally:
            with self._lock:
                self._status.running = False
                self._status.stopped_at = time.time()
                if not self._status.last_error and self._stop_event.is_set():
                    self._status.last_event = "bot berhenti"


_RUNTIME: StreamlitTelegramRuntime | None = None
_RUNTIME_LOCK = threading.Lock()


def get_runtime() -> StreamlitTelegramRuntime:
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            _RUNTIME = StreamlitTelegramRuntime()
        return _RUNTIME
