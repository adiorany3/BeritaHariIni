from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from news_service import default_query, fetch_news
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

with st.expander("Cari langsung dari Jina Search", expanded=False):
    st.caption("Pencarian ini hanya menampilkan hasil di browser. Notifikasi Telegram tetap dikelola oleh workflow GitHub.")
    query = st.text_input("Kata kunci", value=default_query())
    if st.button("Cari berita terbaru", type="primary"):
        api_key = get_secret("JINA_API_KEY")
        if not api_key:
            st.error("Atur JINA_API_KEY di Streamlit Secrets untuk menjalankan pencarian langsung.")
        else:
            try:
                with st.spinner("Mengambil hasil terbaru..."):
                    live_articles, live_metadata = fetch_news(api_key, query=query, max_results=20)
                st.success(f"Ditemukan {len(live_articles)} artikel. Waktu cek: {live_metadata['fetched_at']}")
                st.dataframe(articles_frame(live_articles), use_container_width=True, hide_index=True)
            except requests.RequestException as error:
                st.error(f"Permintaan ke Jina gagal: {error}")
            except ValueError as error:
                st.error(str(error))

st.subheader("Hasil terakhir")
if not articles:
    st.info("Belum ada data. Jalankan workflow GitHub Actions secara manual atau tunggu jadwal pertama.")
else:
    st.dataframe(
        articles_frame(articles),
        use_container_width=True,
        hide_index=True,
        column_config={"Tautan": st.column_config.LinkColumn("Tautan", display_text="Buka artikel")},
    )
