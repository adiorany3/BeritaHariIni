from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from news_service import CATEGORY_ORDER, category_labels, default_query, fetch_news_with_raw

BASE_DIR = Path(__file__).resolve().parent

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


def apply_runtime_config_from_secrets() -> None:
    """Izinkan konfigurasi performa dari Streamlit Secrets selain environment variable."""
    for name in (
        "NEWS_MAX_SEARCH_ROUNDS", "NEWS_REQUEST_TIMEOUT", "JINA_PAGE_TIMEOUT",
        "JINA_RESPOND_WITH", "NEWS_ENABLE_RSS", "NEWS_RSS_TIMEOUT",
        "NEWS_MAX_RSS_FEEDS", "NEWS_ALLOW_SOCIAL", "NEWS_ENABLE_ARTICLE_SCRAPE",
        "NEWS_ARTICLE_SCRAPE_TIMEOUT", "NEWS_MAX_ARTICLE_SCRAPES",
    ):
        if os.getenv(name):
            continue
        value = get_secret(name)
        if value:
            os.environ[name] = value


apply_runtime_config_from_secrets()



def normalise_article(article: dict[str, Any]) -> dict[str, str]:
    """Beri nilai aman untuk data lama sebelum versi kategori tersedia."""
    value = dict(article)
    value.setdefault("category_key", "lainnya")
    value.setdefault("category", "Lainnya")
    value.setdefault("source_type", "publisher")
    value.setdefault("published_at", "Hari ini")
    value.setdefault("time_status", "verified_today")
    value.setdefault("time_note", "")
    value.setdefault("quality_score", "0")
    value.setdefault("quality_reasons", [])
    value.setdefault("summary", "")
    value.setdefault("scraped_info", "")
    value.setdefault("scrape_status", "")
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
        searchable = f"{article['source']} {article['title']} {article['summary']} {article.get('scraped_info', '')}".lower()
        if source_query and source_query not in searchable:
            continue
        filtered.append(article)
    return filtered


def render_article_card(article: dict[str, str]) -> None:
    """Kartu teks murni. Tidak pernah memuat atau merender gambar dari sumber."""
    with st.container(border=True):
        top_left, top_right = st.columns([4, 1])
        with top_left:
            source_line = f"{article['category']}  •  {article['source']}"
            if article.get("source_type") == "social":
                source_line += "  •  Konten sosial"
            if article.get("time_status") == "needs_time_verification":
                source_line += "  •  Kandidat artikel"
            if article.get("quality_score") and article.get("quality_score") != "0":
                source_line += f"  •  Skor kualitas {article['quality_score']}"
            st.caption(source_line)
        with top_right:
            if article.get("time_status") == "needs_time_verification":
                st.caption("🕒 Perlu cek waktu")
            else:
                st.caption(f"🕒 {article['published_at']}")
        st.markdown(f"**{article['title']}**")
        info = article.get("scraped_info") or article.get("summary", "")
        if info:
            st.markdown("**Informasi utama:**")
            st.write(info)
        elif article.get("summary"):
            st.caption(article["summary"])
        if article.get("quality_reasons") not in {"", "[]"}:
            reasons = str(article.get("quality_reasons", "")).strip("[]").replace("'", "")
            if reasons:
                st.caption(f"Alasan lolos: {reasons}")
        if article.get("time_status") == "needs_time_verification":
            st.caption("Waktu publikasi belum ada pada respons pencarian. Periksa waktu di sumber asli.")
        if article.get("scrape_status") and not article.get("scraped_info"):
            st.caption(f"Info scrape: {article['scrape_status']}")


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
    with st.expander("Audit respons mentah sumber", expanded=False):
        st.caption(
            "Panel ini hanya untuk audit parser. Isi ditampilkan sebagai teks kode, sehingga gambar, "
            "iklan, dan HTML dari sumber tidak dimuat."
        )
        if metadata.get("strict_query_relevance") == "true":
            st.caption(f"Mode relevansi ketat aktif untuk term: {metadata.get('query_terms', '-')}")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Kandidat tautan", metadata.get("raw_candidates", "-"))
        col2.metric("Waktu terverifikasi", metadata.get("today_articles", "-"))
        col3.metric("RSS dicek", metadata.get("rss_feeds_checked", "0"))
        col4.metric("Pencarian Jina", metadata.get("search_rounds", "0"))
        col5.metric("Scrape berhasil", f"{metadata.get('article_scrape_success', '0')}/{metadata.get('article_scrape_attempted', '0')}")
        st.code(raw_markdown, language="json", wrap_lines=True)
        st.download_button(
            "Unduh respons sumber",
            data=raw_markdown,
            file_name="respons-sumber-berita.txt",
            mime="text/plain",
        )


st.title("📰 Monitor Berita Hari Ini")
st.caption(
    "Artikel penerbit dari sumber berita resmi dengan informasi utama hasil scrape. "
    "RSS penerbit dicek lebih dulu agar cepat dan bersih; Jina Search dipakai sebagai fallback yang dibatasi ke domain berita."
)

with st.sidebar:
    st.header("Status")
    st.write("Token Jina:", "✅ tersedia" if get_secret("JINA_API_KEY") else "⚠️ belum diatur")
    st.write("Pembaruan dashboard:", "otomatis setiap 5 menit")
    st.write("RSS penerbit:", "✅ aktif" if os.getenv("NEWS_ENABLE_RSS", "1") not in {"0", "false", "False"} else "nonaktif")
    st.write("Mode Jina:", os.getenv("JINA_RESPOND_WITH", "no-content"))
    st.write("Maks. pencarian Jina/siklus:", os.getenv("NEWS_MAX_SEARCH_ROUNDS", "2"))
    st.write("Scrape isi artikel:", "✅ aktif" if os.getenv("NEWS_ENABLE_ARTICLE_SCRAPE", "1") not in {"0", "false", "False"} else "nonaktif")
    st.divider()
    st.caption("Kartu berita menampilkan informasi utama hasil scrape; URL asli hanya disimpan untuk audit internal.")

metric_left, metric_middle, metric_right, metric_extra = st.columns(4)
metric_left.metric("Mode", "Pencarian langsung")
metric_middle.metric("RSS penerbit", "Aktif" if os.getenv("NEWS_ENABLE_RSS", "1") not in {"0", "false", "False"} else "Nonaktif")
metric_right.metric("Maks. pencarian Jina", os.getenv("NEWS_MAX_SEARCH_ROUNDS", "2"))
metric_extra.metric("Scrape artikel", "Aktif" if os.getenv("NEWS_ENABLE_ARTICLE_SCRAPE", "1") not in {"0", "false", "False"} else "Nonaktif")

with st.expander("Cari berita langsung", expanded=True):
    st.caption(
        "Masukkan topik/keyword. Untuk keyword spesifik, RSS hanya dipakai bila artikelnya cocok; "
        "kalau tidak, sistem lanjut ke Jina Search yang dibatasi ke domain media berita. "
        "Sosial/video, Google News, gambar, menu, kanal, metrik engagement, dan artikel lama dibuang. "
        "Hasil akhir diperkaya dengan informasi utama dari isi artikel agar tidak perlu membuka website sumber."
    )
    query = st.text_input("Kata kunci", value=default_query())
    if st.button("Cari berita terbaru hari ini", type="primary"):
        api_key = get_secret("JINA_API_KEY")
        if not api_key:
            st.error("Atur JINA_API_KEY di Streamlit Secrets untuk menjalankan pencarian langsung.")
        else:
            try:
                with st.spinner("Mengambil, menyaring, dan men-scrape informasi utama artikel..."):
                    live_articles, live_metadata, raw_markdown = fetch_news_with_raw(
                        api_key, query=query, max_results=30
                    )
                st.session_state["live_articles"] = live_articles
                st.session_state["live_metadata"] = live_metadata
                st.session_state["live_raw_markdown"] = raw_markdown
                verified_count = live_metadata.get("today_articles", "0")
                unverified_count = live_metadata.get("unverified_articles", "0")
                rounds = live_metadata.get("search_rounds", "1")
                if live_metadata.get("result_mode") == "needs_time_verification":
                    st.warning(
                        f"Menampilkan {unverified_count} kandidat artikel langsung dari {rounds} pencarian. "
                        "Waktu publikasi belum terdeteksi, jadi periksa waktu di sumber asli."
                    )
                elif live_metadata.get("result_mode") == "none":
                    st.warning(
                        "Belum ada artikel yang cocok dengan kata kunci search dan terverifikasi hari ini. "
                        f"RSS dicek: {live_metadata.get('rss_feeds_checked', '0')}, Jina: {rounds} pencarian. "
                        f"Relevansi ketat: {live_metadata.get('strict_query_relevance', 'false')}."
                    )
                else:
                    st.success(
                        f"{verified_count} artikel dengan waktu hari ini terdeteksi dari "
                        f"{live_metadata.get('raw_candidates', '0')} kandidat tautan. "
                        f"RSS dicek: {live_metadata.get('rss_feeds_checked', '0')}, Jina: {rounds} pencarian. "
                        f"Scrape isi: {live_metadata.get('article_scrape_success', '0')}/{live_metadata.get('article_scrape_attempted', '0')}. "
                        f"Relevansi ketat: {live_metadata.get('strict_query_relevance', 'false')}."
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
        st.warning(
            "Belum ditemukan artikel penerbit yang cocok dengan kata kunci dan punya marker waktu hari ini. "
            "Panel audit memperlihatkan RSS/pencarian yang dicek serta tautan yang ditolak."
        )
    if raw_markdown:
        display_raw_response(raw_markdown, live_metadata)

