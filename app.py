from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from config import apply_secrets_to_environment, get_secret, get_secret_bool, has_secret
from news_service import CATEGORY_ORDER, build_text_only_reader_url, category_labels, default_query, fetch_article_text_document, fetch_news_with_raw, jina_api_key_count

BASE_DIR = Path(__file__).resolve().parent

st.set_page_config(page_title="Monitor Berita Hari Ini", page_icon="📰", layout="wide")


# Streamlit Community Cloud menyimpan secrets di panel Settings > Secrets.
# Salin ke environment supaya news_service tetap dapat membaca konfigurasi lama.
apply_secrets_to_environment()


def safe_display_error(error: Any) -> str:
    """Redaksi token Telegram/Jina dari pesan error sebelum tampil di Streamlit."""
    try:
        from telegram_bot import redact_sensitive

        return redact_sensitive(error)
    except Exception:
        return str(error or "")



def get_query_param(name: str) -> str:
    """Ambil query parameter Streamlit dengan kompatibilitas versi lama/baru."""
    try:
        value = st.query_params.get(name, "")
    except Exception:
        value = st.experimental_get_query_params().get(name, "")  # type: ignore[attr-defined]
    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def render_text_only_reader_page(source_url: str) -> None:
    """Halaman pembaca teks internal: ambil Jina Reader, bersihkan Markdown gambar, tampilkan TXT."""
    st.title("🧹 Baca berita teks saja")
    st.caption(
        "Halaman ini mengambil artikel lewat Jina Reader dengan header pembersih, lalu membuang "
        "Markdown gambar seperti `![Image ...]`, navigasi, iklan, dan elemen non-konten."
    )
    if not source_url.startswith(("http://", "https://")):
        st.error("URL artikel tidak valid.")
        return

    col_original, col_back = st.columns(2)
    with col_original:
        st.link_button("Buka berita asli", source_url, use_container_width=True)
    with col_back:
        st.link_button("Kembali ke dashboard", "./", use_container_width=True)

    try:
        with st.spinner("Mengambil teks artikel bersih..."):
            text, status = fetch_article_text_document(
                get_secret("JINA_API_KEY", ""),
                source_url,
                timeout=int(os.getenv("NEWS_ARTICLE_SCRAPE_TIMEOUT", "12") or "12"),
            )
    except requests.RequestException as error:
        st.error(f"Gagal mengambil teks dari Jina Reader: {safe_display_error(error)}")
        st.info("Coba buka link asli, atau ulangi beberapa saat lagi jika API sedang membatasi request.")
        return
    except Exception as error:
        st.error(f"Gagal menyiapkan teks berita: {safe_display_error(error)}")
        return

    st.success("Teks berita berhasil dibersihkan." if text else status)
    if text:
        st.text_area("Format TXT", text, height=620)
        st.download_button(
            "Unduh TXT",
            data=text,
            file_name="berita-teks-bersih.txt",
            mime="text/plain; charset=utf-8",
            use_container_width=True,
        )
    else:
        st.warning(status or "Tidak ada teks artikel yang cukup informatif.")


reader_source_url = get_query_param("reader")
if reader_source_url:
    render_text_only_reader_page(reader_source_url)
    st.stop()

st_autorefresh(interval=300_000, key="news_auto_refresh")


def format_reason_text(value: Any) -> str:
    """Ubah alasan/skor berbentuk list/dict/string menjadi teks aman untuk Streamlit.

    Data lama atau hasil enrich baru bisa menyimpan reasons sebagai list.
    Streamlit sebelumnya membandingkan list dengan set string dan memicu
    `TypeError: unhashable type: 'list'`. Helper ini membuat rendering tahan
    terhadap semua bentuk umum.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(parts)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if item in (None, ""):
                continue
            parts.append(f"{key}: {item}")
        return ", ".join(parts)
    text = str(value).strip()
    if text in {"", "[]", "{}", "None", "null"}:
        return ""
    return text.strip("[]").replace("'", "")


def normalise_article(article: dict[str, Any]) -> dict[str, Any]:
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
    value.setdefault("context_score", 0)
    value.setdefault("context_level", "")
    value.setdefault("context_reasons", [])
    value.setdefault("context_matched_tokens", [])
    value.setdefault("validity_score", 0)
    value.setdefault("validity_status", "")
    value.setdefault("validity_reasons", [])
    value.setdefault("supporting_source_count", 1)
    value.setdefault("supporting_sources", [])
    value.setdefault("structured_info", {})
    value.setdefault("summary", "")
    value.setdefault("scraped_info", "")
    value.setdefault("scrape_status", "")
    value.setdefault("source", "Sumber tidak diketahui")
    value.setdefault("url", "")
    value.setdefault("title", "Tanpa judul")
    return value


def filter_articles(
    articles: list[dict[str, Any]], selected_categories: list[str], source_query: str
) -> list[dict[str, Any]]:
    selected = set(selected_categories)
    source_query = source_query.strip().lower()
    filtered: list[dict[str, Any]] = []
    for raw in articles:
        article = normalise_article(raw)
        if selected and article["category"] not in selected:
            continue
        searchable = f"{article['source']} {article['title']} {article['summary']} {article.get('scraped_info', '')}".lower()
        if source_query and source_query not in searchable:
            continue
        filtered.append(article)
    return filtered


def render_article_card(article: dict[str, Any]) -> None:
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
            if article.get("validity_score"):
                source_line += f"  •  Validitas {article.get('validity_score')}/100"
            if article.get("context_score"):
                source_line += f"  •  Konteks {article.get('context_score')}/100"
            st.caption(source_line)
        with top_right:
            if article.get("time_status") == "needs_time_verification":
                st.caption("🕒 Perlu cek waktu")
            else:
                st.caption(f"🕒 {article['published_at']}")
        st.markdown(f"**{article['title']}**")
        if article.get("validity_status"):
            st.caption(f"{article.get('validity_status')}  •  {article.get('supporting_source_count', 1)} sumber terkait")
        structured = article.get("structured_info")
        if isinstance(structured, dict) and structured.get("highlights"):
            st.markdown(f"**Fakta terstruktur — {structured.get('label', 'Umum')}:**")
            for highlight in structured.get("highlights", [])[:5]:
                st.write(f"• {highlight}")
        info = article.get("scraped_info") or article.get("summary", "")
        if info:
            st.markdown("**Konten berita (hasil scrape):**")
            st.write(info)
        else:
            st.info("Konten artikel belum berhasil di-scrape. Gunakan link teks Jina untuk membaca versi teks, atau buka link asli.")
        reasons = format_reason_text(article.get("quality_reasons"))
        if reasons:
            st.caption(f"Alasan lolos: {reasons}")
        context_reasons = format_reason_text(article.get("context_reasons"))
        if context_reasons:
            st.caption(f"Alasan konteks: {context_reasons}")
        validity_reasons = format_reason_text(article.get("validity_reasons"))
        if validity_reasons:
            st.caption(f"Alasan validitas: {validity_reasons}")
        if isinstance(article.get("supporting_sources"), list) and len(article.get("supporting_sources", [])) > 1:
            st.caption("Sumber terkait: " + ", ".join(article.get("supporting_sources", [])[:5]))
        if article.get("time_status") == "needs_time_verification":
            st.caption("Waktu publikasi belum ada pada respons pencarian. Periksa waktu di sumber asli.")
        if article.get("scrape_status") and not article.get("scraped_info"):
            st.caption(f"Info scrape: {article['scrape_status']}")
        original_url = article.get("url", "").strip()
        text_reader_url = f"?reader={quote(original_url, safe='')}" if original_url.startswith(("http://", "https://")) else ""
        if original_url.startswith(("http://", "https://")):
            link_left, link_right = st.columns([1, 1])
            with link_left:
                st.link_button("Buka teks bersih (TXT)", text_reader_url, use_container_width=True)
            with link_right:
                st.link_button("Buka berita asli", original_url, use_container_width=True)


def render_grouped_articles(articles: list[dict[str, Any]], empty_message: str) -> None:
    if not articles:
        st.info(empty_message)
        return

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
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




def render_telegram_controls() -> None:
    """Kontrol bot Telegram dari Streamlit Cloud.

    Streamlit Cloud hanya menjalankan `app.py`; karena itu polling bot perlu
    dinyalakan dari aplikasi ini atau lewat worker eksternal.
    """
    st.subheader("Telegram Bot")
    token_ready = has_secret("TELEGRAM_BOT_TOKEN")
    jina_key_total = jina_api_key_count(get_secret("JINA_API_KEY", ""))
    jina_ready = jina_key_total > 0
    st.write("Token bot:", "✅ tersedia" if token_ready else "⚠️ belum diatur")
    st.write("Token Jina:", f"✅ {jina_key_total} key tersedia" if jina_ready else "⚠️ belum diatur")

    if not token_ready:
        st.caption("Isi [telegram].bot_token di Streamlit Secrets agar bot bisa merespons pesan.")
        return

    from telegram_runtime import get_runtime

    runtime = get_runtime()
    auto_start = get_secret_bool("TELEGRAM_AUTO_START", False)
    if auto_start:
        runtime.start()
    status = runtime.status()
    st.write("Polling:", "🟢 aktif" if status.get("running") else "⚪ nonaktif")
    st.caption(f"Event terakhir: {safe_display_error(status.get('last_event', '-'))}")
    if status.get("last_error"):
        st.error(safe_display_error(status["last_error"]))
    if status.get("updates_processed"):
        st.caption(f"Update diproses: {status['updates_processed']}")

    col_start, col_stop = st.columns(2)
    if col_start.button("Mulai bot", key="telegram_start", use_container_width=True):
        runtime.start()
        st.rerun()
    if col_stop.button("Stop bot", key="telegram_stop", use_container_width=True):
        runtime.stop()
        st.rerun()

    if st.button("Tes token & webhook", key="telegram_test", use_container_width=True):
        try:
            from telegram_bot import create_bot_from_env

            bot = create_bot_from_env()
            me = (bot.get_me() or {}).get("result", {})
            webhook = (bot.get_webhook_info() or {}).get("result", {})
            username = me.get("username") or me.get("first_name") or "bot"
            st.success(f"Token Telegram valid untuk @{username}.")
            webhook_url = str(webhook.get("url") or "").strip()
            if webhook_url:
                st.warning("Webhook masih aktif. Klik Mulai bot atau set delete_webhook_on_start=true agar polling bisa menerima pesan.")
            else:
                st.caption("Webhook kosong; mode long polling/getUpdates bisa menerima pesan.")
        except Exception as error:
            st.error(f"Tes Telegram gagal: {safe_display_error(error)}")

    if not jina_ready:
        st.warning("Bot bisa menjawab /start, tapi pencarian berita butuh JINA_API_KEY.")
    st.caption("Di Streamlit Cloud, bot aktif selama aplikasi/server Streamlit tetap hidup. Untuk bot 24/7 paling stabil, jalankan telegram_bot.py di worker/VPS.")


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
        if metadata.get("jina_key_count"):
            st.caption(
                f"Jina failover: {metadata.get('jina_key_count')} key tersedia, "
                f"dipakai {metadata.get('jina_key_used', '-')} "
                f"({metadata.get('jina_key_failovers', '0')} failover)."
            )
            if metadata.get("jina_key_failover_events"):
                st.caption(f"Event failover: {metadata.get('jina_key_failover_events')}")
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
    _jina_key_total = jina_api_key_count(get_secret("JINA_API_KEY", ""))
    st.write("Token Jina:", f"✅ {_jina_key_total} key tersedia" if _jina_key_total else "⚠️ belum diatur")
    st.write("Pembaruan dashboard:", "otomatis setiap 5 menit")
    st.write("RSS penerbit:", "✅ aktif" if os.getenv("NEWS_ENABLE_RSS", "1") not in {"0", "false", "False"} else "nonaktif")
    st.write("Mode Jina:", os.getenv("JINA_RESPOND_WITH", "no-content"))
    st.write("Maks. pencarian Jina/siklus:", os.getenv("NEWS_MAX_SEARCH_ROUNDS", "2"))
    st.write("Scrape isi artikel:", "✅ aktif" if os.getenv("NEWS_ENABLE_ARTICLE_SCRAPE", "1") not in {"0", "false", "False"} else "nonaktif")
    st.divider()
    render_telegram_controls()
    st.divider()
    st.caption("Kartu berita menampilkan konten hasil scrape. Link teks bersih membuka halaman TXT internal tanpa `![Image ...]`; link asli tetap tersedia sebagai sumber lengkap.")

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
        "Hasil akhir diperkaya dengan informasi utama dari isi artikel, lalu link asli tetap tersedia bila ingin membaca lengkap."
    )
    query = st.text_input("Kata kunci", value=default_query())
    if st.button("Cari berita terbaru hari ini", type="primary"):
        api_key = get_secret("JINA_API_KEY")
        if not jina_api_key_count(api_key):
            st.error("Atur JINA_API_KEY atau JINA_API_KEYS di Streamlit Secrets untuk menjalankan pencarian langsung. Jangan commit token ke GitHub.")
        else:
            try:
                with st.spinner("Mengambil, menyaring, dan men-scrape konten berita..."):
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

