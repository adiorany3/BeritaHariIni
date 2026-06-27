"""Tampilkan chat_id Telegram yang pernah mengirim pesan ke bot.

Cara pakai:
1. Kirim /start ke bot dari akun/grup tujuan.
2. Jalankan: TELEGRAM_BOT_TOKEN=... python telegram_chat_id.py
3. Salin chat_id ke TELEGRAM_BROADCAST_CHAT_IDS di GitHub Secrets.
"""
from __future__ import annotations

from config import apply_secrets_to_environment, get_secret
from telegram_bot import TelegramNewsBot


def main() -> None:
    apply_secrets_to_environment()
    token = get_secret("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN belum diatur.")

    bot = TelegramNewsBot(token=token, jina_api_key="")
    updates = bot.get_updates(offset=None, poll_timeout=1)
    seen: set[int] = set()
    if not updates:
        print("Belum ada update. Kirim /start atau pesan apa pun ke bot, lalu jalankan lagi.")
        return
    for update in updates:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None or int(chat_id) in seen:
            continue
        seen.add(int(chat_id))
        title = chat.get("title") or " ".join(
            part for part in [chat.get("first_name"), chat.get("last_name")] if part
        ) or chat.get("username") or "tanpa nama"
        print(f"chat_id={chat_id} | type={chat.get('type', 'unknown')} | name={title}")


if __name__ == "__main__":
    main()
