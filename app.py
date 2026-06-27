from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from news_service import default_query, fetch_news_with_raw
from storage import read_json

BASE_DIR = Path(__file__).resolve().parent
LOCAL_DATA_FILE = BASE_DIR / "data" / "latest_news.json"

st.set_page_config(page_title="Monitor Berita Hari Ini", page_icon="📰", layout="wide")
st_autorefresh(interval=300_000, key="news_auto_refresh")


def get_secret(name: str) -> str:
    value = os.getenv(name, "")
    if value:
        return value
    try:
        return str(st.secrets.get(name, ""))
    except FileNotFoundError:
        return ""


def load_dashboard_data() -> dict[str, Any]:
    """Baca data dari repo atau URL raw GitHub jika NEWS_DATA_URL dikonfigurasi."""
    data_url = get_secret("NEWS_DATA_URL")
    if data_url:
        try:
            response = requests.get(data_url, timeout=20)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            st.warning("Data remote belum dapat diambil. Menampilkan data lokal terakhir.")
    return read_json(LOCAL_DATA_FILE, {"metadata": {}, "articles": []})


def articles_frame(articles: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for article in articles:
        rows.append(
            {
                "Judul": article.get("title", ""),
                "Sumber": article.get("source", ""),
                "Dipublikasikan": article.get("published_at") or "Tidak tersedia",
                "Terdeteksi": article.get("detected_at", ""),
                "Tautan": article.get("url", ""),
            }
        )
    return pd.DataFrame(rows)


def display_raw_response(raw_markdown: str, metadata: dict[str, str]) -> None:
    """Perlihatkan respons Jina apa adanya tanpa merender gambar atau tautan eksternal."""
    if not raw_markdown:
        return

    st.divider()
    st.subheader("Respons Markdown mentah dari Jina")
    st.caption(
        "Ditampilkan apa adanya agar format Title, URL Source, deskripsi, tautan, "
        "dan isi hasil tetap terlihat. Panel ini tidak merender gambar atau iklan dari sumber."
    )
    first_line = raw_markdown.splitlines()[0] if raw_markdown.splitlines() else "-"
    left, middle, right = st.columns(3)
    left.metric("Baris respons", len(raw_markdown.splitlines()))
    middle.metric("Ukuran", f"{len(raw_markdown):,} karakter")
    right.metric("Content-Type", metadata.get("content_type", "-"))
    st.code(raw_markdown, language="markdown", wrap_lines=True)
    st.download_button(
        "Unduh respons Markdown",
        data=raw_markdown,
        file_name="respons-jina-berita.md",
        mime="text/markdown",
        use_container_width=False,
    )
    st.caption(f"Baris pertama: {first_line[:180]}")


st.title("📰 Monitor Berita Hari Ini")
st.caption("Data diperbarui oleh GitHub Actions. Halaman ini memuat ulang otomatis setiap 5 menit.")

with st.sidebar:
    st.header("Pengaturan")
    st.write("Status token Jina:", "✅ tersedia" if get_secret("JINA_API_KEY") else "⚠️ tidak tersedia")
    st.write("Notifikasi Telegram berjalan dari GitHub Actions, bukan dari halaman ini.")
    st.divider()
    st.caption("Pastikan setiap judul dibuka di sumber asli sebelum dipercaya atau dibagikan.")

payload = load_dashboard_data()
metadata = payload.get("metadata", {})
articles = payload.get("articles", [])

left, middle, right = st.columns(3)
left.metric("Artikel terdeteksi", len(articles))
middle.metric("Tanggal pencarian", metadata.get("today_jakarta", "Belum ada"))
right.metric("Pembaruan terakhir", metadata.get("fetched_at", "Belum ada"))

with st.expander("Cari langsung dari Jina Search", expanded=True):
    st.caption(
        "Pencarian langsung akan menampilkan tabel artikel dan respons Markdown Jina secara utuh. "
        "Notifikasi Telegram tetap dikelola oleh workflow GitHub."
    )
    query = st.text_input("Kata kunci", value=default_query())
    if st.button("Cari berita terbaru", type="primary"):
        api_key = get_secret("JINA_API_KEY")
        if not api_key:
            st.error("Atur JINA_API_KEY di Streamlit Secrets untuk menjalankan pencarian langsung.")
        else:
            try:
                with st.spinner("Mengambil respons terbaru dari Jina..."):
                    live_articles, live_metadata, raw_markdown = fetch_news_with_raw(
                        api_key, query=query, max_results=20
                    )
                st.session_state["live_articles"] = live_articles
                st.session_state["live_metadata"] = live_metadata
                st.session_state["live_raw_markdown"] = raw_markdown
                st.success(
                    f"Ditemukan {len(live_articles)} artikel. "
                    f"Waktu cek: {live_metadata['fetched_at']}"
                )
            except requests.RequestException as error:
                st.error(f"Permintaan ke Jina gagal: {error}")
            except ValueError as error:
                st.error(str(error))

    live_articles = st.session_state.get("live_articles", [])
    live_metadata = st.session_state.get("live_metadata", {})
    raw_markdown = st.session_state.get("live_raw_markdown", "")
    if live_articles:
        st.subheader("Artikel yang terdeteksi dari pencarian langsung")
        st.dataframe(
            articles_frame(live_articles),
            use_container_width=True,
            hide_index=True,
            column_config={"Tautan": st.column_config.LinkColumn("Tautan", display_text="Buka artikel")},
        )
    if raw_markdown:
        display_raw_response(raw_markdown, live_metadata)

st.subheader("Hasil terakhir dari GitHub Actions")
if not articles:
    st.info("Belum ada data. Jalankan workflow GitHub Actions secara manual atau tunggu jadwal pertama.")
else:
    st.dataframe(
        articles_frame(articles),
        use_container_width=True,
        hide_index=True,
        column_config={"Tautan": st.column_config.LinkColumn("Tautan", display_text="Buka artikel")},
    )
