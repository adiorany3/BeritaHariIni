from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from news_service import CATEGORY_ORDER, category_labels, default_query, fetch_news_with_raw
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
    """Baca data commit GitHub atau URL raw GitHub bila dikonfigurasi."""
    data_url = get_secret("NEWS_DATA_URL")
    if data_url:
        try:
            response = requests.get(data_url, timeout=20)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            st.warning("Data remote belum dapat diambil. Menampilkan data lokal terakhir.")
    return read_json(LOCAL_DATA_FILE, {"metadata": {}, "articles": []})


def normalise_article(article: dict[str, Any]) -> dict[str, str]:
    """Beri nilai aman untuk data lama sebelum versi kategori tersedia."""
    value = dict(article)
    value.setdefault("category_key", "lainnya")
    value.setdefault("category", "Lainnya")
    value.setdefault("published_at", "Hari ini")
    value.setdefault("summary", "")
    value.setdefault("source", "Sumber tidak diketahui")
    value.setdefault("url", "")
    value.setdefault("title", "Tanpa judul")
    return {key: str(item) for key, item in value.items()}


def filter_articles(
    articles: list[dict[str, Any]], selected_categories: list[str], source_query: str
) -> list[dict[str, str]]:
    selected = set(selected_categories)
    source_query = source_query.strip().lower()
    filtered: list[dict[str, str]] = []
    for raw in articles:
        article = normalise_article(raw)
        if selected and article["category"] not in selected:
            continue
        searchable = f"{article['source']} {article['title']}".lower()
        if source_query and source_query not in searchable:
            continue
        filtered.append(article)
    return filtered


def render_article_card(article: dict[str, str]) -> None:
    """Kartu teks murni. Tidak pernah memuat atau merender gambar dari sumber."""
    with st.container(border=True):
        top_left, top_right = st.columns([4, 1])
        with top_left:
            st.caption(f"{article['category']}  •  {article['source']}")
        with top_right:
            st.caption(f"🕒 {article['published_at']}")
        st.markdown(f"**{article['title']}**")
        if article["summary"]:
            st.caption(article["summary"])
        if article["url"].startswith(("https://", "http://")):
            st.link_button("Buka artikel asli", article["url"], use_container_width=False)


def render_grouped_articles(articles: list[dict[str, str]], empty_message: str) -> None:
    if not articles:
        st.info(empty_message)
        return

    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for article in articles:
        groups[article["category"]].append(article)

    labels_by_order = category_labels()
    rendered_labels = [label for label in labels_by_order if groups.get(label)]
    # Data lama atau kategori kustom tetap dapat muncul.
    rendered_labels.extend(sorted(set(groups) - set(rendered_labels)))

    for label in rendered_labels:
        st.subheader(f"{label} ({len(groups[label])})")
        for article in groups[label]:
            render_article_card(article)


def display_raw_response(raw_markdown: str, metadata: dict[str, str]) -> None:
    """Audit respons mentah tanpa merender gambar, HTML, atau tautan sumber."""
    if not raw_markdown:
        return
    with st.expander("Audit respons mentah Jina", expanded=False):
        st.caption(
            "Panel ini hanya untuk audit parser. Isi ditampilkan sebagai teks kode, sehingga gambar, "
            "iklan, dan HTML dari sumber tidak dimuat."
        )
        col1, col2, col3 = st.columns(3)
        col1.metric("Kandidat tautan", metadata.get("raw_candidates", "-"))
        col2.metric("Artikel hari ini", metadata.get("today_articles", "-"))
        col3.metric("Baris respons", len(raw_markdown.splitlines()))
        st.code(raw_markdown, language="markdown", wrap_lines=True)
        st.download_button(
            "Unduh respons Markdown",
            data=raw_markdown,
            file_name="respons-jina-berita.md",
            mime="text/markdown",
        )


st.title("📰 Monitor Berita Hari Ini")
st.caption(
    "Hanya artikel dengan waktu publikasi yang terdeteksi pada hari ini, zona waktu Asia/Jakarta. "
    "Tampilan memuat judul dan tautan langsung ke artikel asli, tanpa gambar hasil scraping."
)

with st.sidebar:
    st.header("Status")
    st.write("Token Jina:", "✅ tersedia" if get_secret("JINA_API_KEY") else "⚠️ belum diatur")
    st.write("Pembaruan dashboard:", "otomatis setiap 5 menit")
    st.write("Notifikasi Telegram:", "dikirim oleh GitHub Actions")
    st.divider()
    st.caption("Buka sumber asli untuk memeriksa isi, konteks, dan waktu publikasi artikel.")

payload = load_dashboard_data()
metadata = payload.get("metadata", {})
stored_articles = payload.get("articles", [])

metric_left, metric_middle, metric_right, metric_last = st.columns(4)
metric_left.metric("Artikel hari ini", len(stored_articles))
metric_middle.metric("Kategori", len({item.get("category", "Lainnya") for item in stored_articles}))
metric_right.metric("Tanggal pencarian", metadata.get("today_jakarta", "Belum ada"))
metric_last.metric("Pembaruan terakhir", metadata.get("fetched_at", "Belum ada"))

with st.expander("Cari langsung dari Jina Search", expanded=True):
    st.caption(
        "Sistem akan membuang gambar, menu, halaman kategori, URL perantara, artikel kemarin, dan "
        "tautan tanpa marker waktu. Hasil yang lolos diarahkan langsung ke situs penerbit."
    )
    query = st.text_input("Kata kunci", value=default_query())
    if st.button("Cari berita terbaru hari ini", type="primary"):
        api_key = get_secret("JINA_API_KEY")
        if not api_key:
            st.error("Atur JINA_API_KEY di Streamlit Secrets untuk menjalankan pencarian langsung.")
        else:
            try:
                with st.spinner("Mengambil dan menyaring artikel hari ini..."):
                    live_articles, live_metadata, raw_markdown = fetch_news_with_raw(
                        api_key, query=query, max_results=30
                    )
                st.session_state["live_articles"] = live_articles
                st.session_state["live_metadata"] = live_metadata
                st.session_state["live_raw_markdown"] = raw_markdown
                st.success(
                    f"{len(live_articles)} artikel hari ini terdeteksi dari "
                    f"{live_metadata.get('raw_candidates', '0')} kandidat tautan."
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
        live_options = [
            label for label in category_labels()
            if any(normalise_article(item)["category"] == label for item in live_articles)
        ]
        selected_live = st.multiselect(
            "Tampilkan kategori", options=live_options, default=live_options, key="live_categories"
        )
        source_live = st.text_input("Saring judul atau sumber", key="live_source_filter")
        filtered_live = filter_articles(live_articles, selected_live, source_live)
        st.caption(f"Menampilkan {len(filtered_live)} artikel yang sesuai filter.")
        render_grouped_articles(filtered_live, "Tidak ada artikel yang sesuai filter kategori atau sumber.")
    elif raw_markdown:
        st.info("Respons diterima, tetapi tidak ada tautan artikel hari ini yang memenuhi aturan penyaringan.")
    if raw_markdown:
        display_raw_response(raw_markdown, live_metadata)

st.divider()
st.subheader("Hasil terakhir dari GitHub Actions")
if not stored_articles:
    st.info("Belum ada data. Jalankan workflow GitHub Actions secara manual atau tunggu jadwal pertama.")
else:
    stored_options = [
        label for label in category_labels()
        if any(normalise_article(item)["category"] == label for item in stored_articles)
    ]
    selected_stored = st.multiselect(
        "Kategori hasil tersimpan", options=stored_options, default=stored_options, key="stored_categories"
    )
    source_stored = st.text_input("Saring judul atau sumber hasil tersimpan", key="stored_source_filter")
    filtered_stored = filter_articles(stored_articles, selected_stored, source_stored)
    st.caption(f"Menampilkan {len(filtered_stored)} artikel yang sesuai filter.")
    render_grouped_articles(filtered_stored, "Tidak ada artikel tersimpan yang sesuai filter.")
