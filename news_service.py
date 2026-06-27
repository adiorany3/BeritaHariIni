"""Ambil, saring, kategorikan, dan normalisasi berita dari RSS penerbit + Jina Search.

Modul memprioritaskan tautan artikel penerbit resmi. Platform sosial/video, gambar,
profil, metrik engagement, iklan, menu, halaman kategori, dan perantara seperti
Google News dikeluarkan secara default.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
import json
import os
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

JAKARTA = ZoneInfo("Asia/Jakarta")
JINA_SEARCH_URL = "https://s.jina.ai/"
JINA_READER_URL = "https://r.jina.ai/"
MONTHS_ID = (
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)
MONTH_NUMBERS = {
    "jan": 1, "januari": 1,
    "feb": 2, "februari": 2,
    "mar": 3, "maret": 3,
    "apr": 4, "april": 4,
    "mei": 5,
    "jun": 6, "juni": 6,
    "jul": 7, "juli": 7,
    "agu": 8, "agustus": 8,
    "sep": 9, "september": 9,
    "okt": 10, "oktober": 10,
    "nov": 11, "november": 11,
    "des": 12, "desember": 12,
}

CATEGORY_LABELS = {
    "teknologi": "Teknologi",
    "edukasi": "Edukasi",
    "otomotif": "Otomotif",
    "ekonomi": "Ekonomi & Bisnis",
    "olahraga": "Olahraga",
    "kesehatan": "Kesehatan",
    "hiburan": "Hiburan",
    "politik": "Politik",
    "hukum": "Hukum & Kriminal",
    "internasional": "Internasional",
    "gaya_hidup": "Gaya Hidup & Perjalanan",
    "lingkungan": "Lingkungan & Cuaca",
    "lainnya": "Lainnya",
}
CATEGORY_ORDER = tuple(CATEGORY_LABELS)

# Kata kunci bersifat transparan dan mudah disesuaikan. Skor tertinggi menjadi kategori artikel.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "teknologi": (
        "teknologi", "tech", "digital", "gadget", "smartphone", "ponsel", "laptop",
        "software", "aplikasi", "internet", "siber", "cyber", "kecerdasan buatan",
        "artificial intelligence", "robot", "startup", "telekomunikasi", "komputasi",
    ),
    "edukasi": (
        "edukasi", "pendidikan", "sekolah", "kampus", "universitas", "mahasiswa",
        "siswa", "guru", "snbt", "snbp", "beasiswa", "kurikulum", "ujian",
        "peserta didik", "kemendikdasmen", "kemendiktisaintek",
    ),
    "otomotif": (
        "otomotif", "mobil", "motor", "kendaraan", "sepeda motor", "roda empat",
        "roda dua", "baterai kendaraan", "mobil listrik", "motor listrik", "ev",
    ),
    "ekonomi": (
        "ekonomi", "bisnis", "keuangan", "finansial", "saham", "rupiah", "bank",
        "investasi", "pasar modal", "perdagangan", "pajak", "umkm", "inflasi",
    ),
    "olahraga": (
        "olahraga", "sport", "sepak bola", "bola", "liga", "pertandingan", "atlet",
        "badminton", "bulutangkis", "tenis", "formula 1", "motogp", "piala dunia",
    ),
    "kesehatan": (
        "kesehatan", "medis", "rumah sakit", "vaksin", "penyakit", "dokter", "pasien",
        "obat", "bpjs kesehatan", "kemenkes", "wabah",
    ),
    "hiburan": (
        "hiburan", "selebritas", "seleb", "artis", "musik", "film", "drama", "konser",
        "perfilman", "album", "aktor", "aktris",
    ),
    "politik": (
        "politik", "presiden", "wakil presiden", "dpr", "menteri", "gubernur", "bupati",
        "pilkada", "pemilu", "partai", "kabinet", "istana", "kebijakan pemerintah",
    ),
    "hukum": (
        "hukum", "polisi", "kejaksaan", "pengadilan", "tersangka", "kriminal", "korupsi",
        "penangkapan", "ditangkap", "pidana", "sidang", "vonis", "penjara",
    ),
    "internasional": (
        "internasional", "dunia", "global", "amerika serikat", "iran", "china",
        "tiongkok", "rusia", "ukraina", "eropa", "jepang", "korea", "timur tengah",
        "pbb", "nato", "gaza", "israel", "palestina",
    ),
    "gaya_hidup": (
        "gaya hidup", "lifestyle", "wisata", "travel", "kuliner", "makanan", "hotel",
        "fashion", "kecantikan", "liburan", "resep",
    ),
    "lingkungan": (
        "lingkungan", "cuaca", "iklim", "banjir", "longsor", "gempa", "bencana", "bmkg",
        "hujan", "sampah", "energi terbarukan", "karhutla",
    ),
}
SOURCE_CATEGORY_HINTS: dict[str, str] = {
    "inet.detik.com": "teknologi",
    "tekno.kompas.com": "teknologi",
    "oto.detik.com": "otomotif",
    "otomotif.kompas.com": "otomotif",
    "edu.detik.com": "edukasi",
    "edukasi.kompas.com": "edukasi",
    "sport.detik.com": "olahraga",
    "bola.com": "olahraga",
    "health.detik.com": "kesehatan",
    "hot.detik.com": "hiburan",
    "travel.detik.com": "gaya_hidup",
    "food.detik.com": "gaya_hidup",
    "finance.detik.com": "ekonomi",
}

IMAGE_SUFFIXES = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif", ".bmp", ".ico",
)
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "igshid", "si", "spm",
    "ocid", "cmpid", "ito", "ref", "ref_src", "feature", "app", "from",
}
# Mesin pencari, URL utilitas, dan platform sosial tidak boleh muncul sebagai hasil berita
# default. Tujuan aplikasi ini adalah tautan artikel penerbit, bukan video/postingan acak.
BLOCKED_HOSTS = {
    "google.com", "news.google.com", "googleusercontent.com", "jina.ai", "s.jina.ai",
    "bit.ly", "tinyurl.com", "t.me", "telegram.me",
}
SOCIAL_SOURCE_LABELS = {
    "instagram.com": "Instagram",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "tiktok.com": "TikTok",
    "facebook.com": "Facebook",
    "fb.com": "Facebook",
    "x.com": "X",
    "twitter.com": "X",
    "threads.net": "Threads",
    "linkedin.com": "LinkedIn",
    "reddit.com": "Reddit",
    "pinterest.com": "Pinterest",
}
SOCIAL_HOSTS = frozenset(SOCIAL_SOURCE_LABELS)
SOCIAL_NEGATIVE_QUERY = (
    "-site:youtube.com -site:youtu.be -site:instagram.com -site:tiktok.com "
    "-site:facebook.com -site:x.com -site:twitter.com -site:threads.net "
    "-site:linkedin.com -site:reddit.com -site:t.me -site:telegram.me -site:news.google.com"
)
# Catatan penting: parser tetap memblokir sosial/video, tetapi kueri Jina sengaja
# dibuat sederhana. `s.jina.ai` dapat mengembalikan 422 saat menerima query terlalu
# kompleks seperti `(site:a OR site:b) "frasa" -site:x ...`. Karena itu operator
# OR, tanda kurung, dan rangkaian negative-site tidak lagi dipakai pada request.
JINA_QUERY_OPERATOR_RE = re.compile(r"\bOR\b|[()\[\]{}]", re.IGNORECASE)

# Sumber tepercaya diberi bobot lebih tinggi, tetapi daftar ini bukan allow-list keras.
# Tujuannya mendorong hasil editorial yang jelas tanpa mematikan sumber lokal yang valid.
TRUSTED_NEWS_HOSTS = {
    "kompas.com", "detik.com", "cnnindonesia.com", "cnbcindonesia.com",
    "tempo.co", "antaranews.com", "republika.co.id", "liputan6.com",
    "bisnis.com", "kontan.co.id", "katadata.co.id", "kumparan.com",
    "tirto.id", "viva.co.id", "okezone.com", "sindonews.com",
    "suara.com", "jpnn.com", "jawapos.com", "idntimes.com",
    "thejakartapost.com", "voaindonesia.com", "bbc.com", "reuters.com",
    "apnews.com", "aljazeera.com", "theguardian.com", "nytimes.com",
    "bloomberg.com", "channelnewsasia.com", "straitstimes.com",
}
PREFERRED_SEARCH_DOMAINS = (
    "kompas.com", "detik.com", "cnnindonesia.com", "cnbcindonesia.com", "tempo.co",
    "antaranews.com", "liputan6.com", "bisnis.com", "katadata.co.id", "kontan.co.id",
    "republika.co.id", "kumparan.com", "tirto.id", "suara.com", "okezone.com",
)
PUBLISHER_SEARCH_GROUPS = (
    ("kompas.com", "detik.com", "cnnindonesia.com", "cnbcindonesia.com", "tempo.co"),
    ("antaranews.com", "liputan6.com", "bisnis.com", "katadata.co.id", "kontan.co.id"),
    ("republika.co.id", "kumparan.com", "tirto.id", "suara.com", "okezone.com"),
)
RSS_FEEDS = (
    {"source": "detik.com", "url": "https://rss.detik.com/index.php/detikcom"},
    {"source": "kompas.com", "url": "https://www.kompas.com/rss"},
    {"source": "cnnindonesia.com", "url": "https://www.cnnindonesia.com/nasional/rss"},
    {"source": "cnbcindonesia.com", "url": "https://www.cnbcindonesia.com/news/rss"},
    {"source": "tempo.co", "url": "https://rss.tempo.co/nasional"},
    {"source": "antaranews.com", "url": "https://www.antaranews.com/rss/terkini.xml"},
    {"source": "liputan6.com", "url": "https://www.liputan6.com/feed/rss"},
    {"source": "bisnis.com", "url": "https://www.bisnis.com/rss"},
    {"source": "republika.co.id", "url": "https://www.republika.co.id/rss"},
    {"source": "suara.com", "url": "https://www.suara.com/rss/news"},
)
KNOWN_NEWS_PATH_HINTS = {
    "news", "berita", "read", "artikel", "nasional", "regional", "internasional",
    "ekonomi", "bisnis", "tekno", "teknologi", "otomotif", "edukasi", "health",
    "kesehatan", "sport", "bola", "sepakbola", "finance", "politik", "hukum",
}
LOW_QUALITY_TITLE_RE = re.compile(
    r"\b(?:terpopuler|recommended|rekomendasi|indeks|jadwal tv|live streaming|"
    r"cek fakta tanpa konteks|download|profil lengkap|biodata|link nonton|"
    r"harga terbaru|spesifikasi lengkap)\b",
    re.IGNORECASE,
)
CLICKBAIT_TITLE_RE = re.compile(
    r"\b(?:viral|heboh|bikin geger|netizen ramai|auto|simak|jangan kaget|"
    r"ternyata|terungkap|ini dia|wajib tahu)\b",
    re.IGNORECASE,
)
NEWS_VERB_RE = re.compile(
    r"\b(?:rilis|umumkan|sebut|jelaskan|dorong|gelar|tetapkan|naik|turun|"
    r"menang|kalah|tangkap|periksa|gugat|vonis|resmikan|luncurkan|"
    r"investigasi|laporkan|minta|duga|temukan|prediksi|peringatkan)\b",
    re.IGNORECASE,
)
# Jina Search mode umumnya mengembalikan 5 hasil teratas per request.
# Target yang terlalu tinggi membuat aplikasi menjalankan banyak fallback berurutan.
QUALITY_TARGET_RESULTS = 5
DEFAULT_MAX_SEARCH_ROUNDS = 2
DEFAULT_REQUEST_TIMEOUT = 25
DEFAULT_JINA_PAGE_TIMEOUT = 12
DEFAULT_JINA_RESPOND_WITH = "no-content"
DEFAULT_RSS_TIMEOUT = 4
DEFAULT_MAX_RSS_FEEDS = 8
DEFAULT_ENABLE_RSS = True
DEFAULT_ALLOW_SOCIAL = False
DEFAULT_ENABLE_ARTICLE_SCRAPE = True
DEFAULT_ARTICLE_SCRAPE_TIMEOUT = 12
DEFAULT_MAX_ARTICLE_SCRAPES = 5
MIN_VERIFIED_QUALITY_SCORE = 58
MIN_UNVERIFIED_QUALITY_SCORE = 72

# Navigasi dan profil tetap tidak dianggap artikel. Kata seperti watch, reels, dan shorts
# sengaja tidak diblokir secara global karena dapat merupakan URL konten sosial individual.
BLOCKED_URL_PARTS = {
    "search", "searchall", "tag", "tags", "topic", "topics", "kategori", "category",
    "categories", "indeks", "index", "login", "signin", "privacy", "kebijakan", "kontak",
    "contact", "about", "redaksi", "rss", "sitemap", "advert", "iklan", "subscribe",
    "channel", "channels", "user", "users", "profile", "profiles", "account", "accounts",
    "settings", "explore", "hashtag", "trending", "author", "authors", "penulis",
    "video", "foto", "photo", "gallery", "galeri", "infografik", "quiz",
}
BLOCKED_TITLE_PARTS = {
    "menu", "beranda", "home", "terpopuler", "lihat selengkapnya", "selengkapnya",
    "baca juga", "lainnya", "loading", "indeks berita", "rekomendasi untuk anda",
    "kebijakan privasi", "kontak kami", "masuk", "login", "download sekarang",
    "kelana kota", "podcast", "siaran langsung", "live streaming", "profil", "profile",
    "newsletter", "advertorial", "sponsored", "foto", "galeri",
}
# Metrik akun atau engagement bukan isi berita. Baris tersebut dihapus dari ringkasan.
SOCIAL_ENGAGEMENT_RE = re.compile(
    r"\b(?:\d+[\d.,]*[kmb]?\s*)?(?:followers?|pengikut|subscribers?|following|"
    r"likes?|suka|komentar|comments?|views?|tayangan|dibaca|reposts?|shares?|bagikan)\b",
    re.IGNORECASE,
)
NON_ARTICLE_CONTEXT_RE = re.compile(
    r"\b(?:akun resmi|official account|subscribe|ikuti kami|follow us|kanal youtube|"
    r"channel youtube|halaman profil|profile page)\b",
    re.IGNORECASE,
)
MIN_HEADLINE_LENGTH = 8

# Kata yang membuat kueri terlalu umum. Setelah kata-kata ini dibuang, sisa term
# dipakai sebagai niat pencarian spesifik pengguna. Ini mencegah RSS umum
# dianggap cocok hanya karena sama-sama berlabel "berita hari ini".
GENERIC_QUERY_TERMS = {
    "berita", "terbaru", "terkini", "hari", "ini", "today", "indonesia",
    "artikel", "media", "nasional", "penerbit", "resmi", "langsung",
    "update", "kabar", "headline", "headlines", "news", "terpercaya",
}
CATEGORY_SEED_TERMS = {
    "teknologi", "edukasi", "otomotif", "ekonomi", "bisnis", "olahraga",
    "kesehatan", "hiburan", "politik", "hukum", "kriminal", "internasional",
    "lingkungan", "cuaca", "travel", "wisata", "kuliner", "lifestyle",
}
QUERY_STOPWORDS = {
    "berita", "terbaru", "terkini", "hari", "ini", "indonesia", "dan", "atau",
    "yang", "untuk", "dengan", "dari", "pada", "dalam", "ke", "di", "akan",
    "the", "a", "an", "of", "to", "today", "artikel", "kabar", "update",
    "januari", "februari", "maret", "april", "mei", "juni", "juli", "agustus",
    "september", "oktober", "november", "desember",
}


HEADING_LINK_RE = re.compile(
    r"(?m)^\s{0,3}#{2,6}\s+\[([^\]\n]{3,300})\]\((https?://[^\s)]+)\)"
)
LINK_RE = re.compile(r"(?<![!\[])\[([^\]\n]{3,300})\]\((https?://[^\s)]+)\)")
RELATIVE_TIME_RE = re.compile(
    r"\b(\d{1,3})\s*(menit|jam|detik|hari)\s*(?:yang\s*)?lalu\b", re.IGNORECASE
)
EN_RELATIVE_TIME_RE = re.compile(
    r"\b(\d{1,3})\s*(seconds?|minutes?|hours?|days?)\s+ago\b", re.IGNORECASE
)
DAY_MONTH_RE = re.compile(
    r"\b(?:senin|selasa|rabu|kamis|jumat|jum'at|sabtu|minggu)?\s*,?\s*"
    r"(\d{1,2})\s+(jan(?:uari)?|feb(?:ruari)?|mar(?:et)?|apr(?:il)?|mei|"
    r"jun(?:i)?|jul(?:i)?|agu(?:stus)?|sep(?:tember)?|okt(?:ober)?|"
    r"nov(?:ember)?|des(?:ember)?)(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}:\d{2}(?::\d{2})?)?)?")
ENGLISH_DAY_MONTH_RE = re.compile(
    r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+(\d{4})\b",
    re.IGNORECASE,
)
ENGLISH_DATE_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)
ENGLISH_MONTH_NUMBERS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
RFC_LIKE_DATE_RE = re.compile(
    r"\b(?:mon|tue|wed|thu|fri|sat|sun),?\s+\d{1,2}\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{4}",
    re.IGNORECASE,
)


def jakarta_now() -> datetime:
    return datetime.now(JAKARTA)


def _as_jakarta(value: str | datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        current = value
    elif value:
        try:
            current = datetime.fromisoformat(value)
        except ValueError:
            current = jakarta_now()
    else:
        current = jakarta_now()
    if current.tzinfo is None:
        return current.replace(tzinfo=JAKARTA)
    return current.astimezone(JAKARTA)


def today_indonesia(now: datetime | None = None) -> str:
    now = _as_jakarta(now)
    return f"{now.day} {MONTHS_ID[now.month - 1]} {now.year}"


def default_query(now: datetime | None = None) -> str:
    """Buat kueri luas dengan konteks tanggal Jakarta dan kategori utama."""
    return (
        f"Berita Indonesia terbaru hari ini {today_indonesia(now)} "
        "teknologi edukasi otomotif ekonomi olahraga kesehatan politik hukum internasional "
        "artikel media nasional"
    )


def category_labels() -> list[str]:
    """Daftar kategori dalam urutan tampilan dashboard."""
    return [CATEGORY_LABELS[key] for key in CATEGORY_ORDER]


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    """Ambil konfigurasi integer dari environment dengan batas aman."""
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def configured_max_search_rounds() -> int:
    """Jumlah pencarian Jina maksimal per siklus. Default dibuat rendah agar respons cepat."""
    return _env_int("NEWS_MAX_SEARCH_ROUNDS", DEFAULT_MAX_SEARCH_ROUNDS, minimum=0, maximum=6)


def configured_enable_rss() -> bool:
    """RSS penerbit resmi aktif secara default karena lebih cepat dan lebih bersih dari SERP umum."""
    return _env_bool("NEWS_ENABLE_RSS", DEFAULT_ENABLE_RSS)


def configured_allow_social() -> bool:
    """Konten sosial dinonaktifkan default agar hasil tidak kacau oleh video/postingan."""
    return _env_bool("NEWS_ALLOW_SOCIAL", DEFAULT_ALLOW_SOCIAL)


def configured_rss_timeout(default: int = DEFAULT_RSS_TIMEOUT) -> int:
    """Timeout pendek untuk setiap feed RSS agar tidak memperlambat keseluruhan proses."""
    return _env_int("NEWS_RSS_TIMEOUT", default, minimum=3, maximum=20)


def configured_max_rss_feeds() -> int:
    """Batas feed RSS yang dicek per siklus."""
    return _env_int("NEWS_MAX_RSS_FEEDS", DEFAULT_MAX_RSS_FEEDS, minimum=0, maximum=len(RSS_FEEDS))


def configured_enable_article_scrape() -> bool:
    """Scrape informasi artikel aktif default agar user tidak perlu membuka situs asli."""
    return _env_bool("NEWS_ENABLE_ARTICLE_SCRAPE", DEFAULT_ENABLE_ARTICLE_SCRAPE)


def configured_article_scrape_timeout(default: int = DEFAULT_ARTICLE_SCRAPE_TIMEOUT) -> int:
    """Timeout pendek untuk Jina Reader per artikel agar proses tetap masuk akal."""
    return _env_int("NEWS_ARTICLE_SCRAPE_TIMEOUT", default, minimum=5, maximum=45)


def configured_max_article_scrapes() -> int:
    """Jumlah artikel akhir yang diperkaya dengan isi scrape."""
    return _env_int("NEWS_MAX_ARTICLE_SCRAPES", DEFAULT_MAX_ARTICLE_SCRAPES, minimum=0, maximum=20)


def configured_request_timeout(default: int = DEFAULT_REQUEST_TIMEOUT) -> int:
    """Timeout HTTP client. Dapat dioverride dengan NEWS_REQUEST_TIMEOUT."""
    return _env_int("NEWS_REQUEST_TIMEOUT", default, minimum=8, maximum=90)


def configured_jina_page_timeout(default: int = DEFAULT_JINA_PAGE_TIMEOUT) -> int:
    """Batas waktu page load di sisi Jina Reader/Search melalui header X-Timeout."""
    return _env_int("JINA_PAGE_TIMEOUT", default, minimum=5, maximum=45)


def configured_jina_respond_with() -> str:
    """Mode respons Jina. no-content lebih cepat; markdown dapat dipakai untuk audit mendalam."""
    value = os.getenv("JINA_RESPOND_WITH", DEFAULT_JINA_RESPOND_WITH).strip().lower()
    return value if value in {"no-content", "markdown", "html", "text"} else DEFAULT_JINA_RESPOND_WITH


def _clean_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _strip_html(value: Any, limit: int = 700) -> str:
    """Ringkas teks dari RSS/HTML tanpa membawa tag, gambar, atau entities."""
    text = str(value or "")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return _clean_text(text, limit)


def _plain_markdown_text(value: Any, limit: int = 5_000) -> str:
    """Ubah markdown/HTML dari Reader menjadi teks bersih tanpa gambar dan daftar link."""
    text = str(value or "")
    if not text:
        return ""
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    # Jaga teks tautan, buang URL-nya agar kartu tidak berubah menjadi daftar link.
    def replace_markdown_link(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        if any(part in label.casefold() for part in BLOCKED_TITLE_PARTS):
            return " "
        return label

    text = re.sub(r"\[([^\]\n]{1,220})\]\([^)]*\)", replace_markdown_link, text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"(?m)^\s*(?:Title|URL Source|Markdown Content|Published Time):\s*", " ", text)
    text = re.sub(r"[`*_>#|~]+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _sentence_candidates(text: str) -> list[str]:
    """Pecah teks menjadi kandidat kalimat yang cukup informatif."""
    cleaned = _plain_markdown_text(text, 8_000)
    if not cleaned:
        return []
    raw_sentences = re.split(r"(?<=[.!?])\s+|\s+[•·]\s+", cleaned)
    sentences: list[str] = []
    seen: set[str] = set()
    for sentence in raw_sentences:
        sentence = _clean_text(sentence.strip(" -–—:;"), 320)
        if len(sentence) < 45:
            continue
        lower = sentence.casefold()
        if any(part in lower for part in BLOCKED_TITLE_PARTS):
            continue
        if SOCIAL_ENGAGEMENT_RE.search(sentence) or NON_ARTICLE_CONTEXT_RE.search(sentence):
            continue
        key = _normalise_search_text(sentence)
        if key in seen:
            continue
        sentences.append(sentence)
        seen.add(key)
    return sentences


def extract_article_information(content: str, *, title: str = "", query: str = "", limit: int = 850) -> str:
    """Ambil informasi utama dari isi artikel, bukan artikel penuh mentah.

    Untuk menjaga tampilan tetap ringkas dan tidak menyalin seluruh artikel, fungsi ini
    memilih beberapa kalimat paling relevan dengan query/judul, lalu membatasinya.
    """
    sentences = _sentence_candidates(content)
    if not sentences:
        return ""

    query_tokens = _specific_query_token_list(query)
    title_tokens = _specific_query_token_list(title)
    phrase = _specific_query_phrase(query)

    def score(sentence: str, index: int) -> int:
        normalised = _normalise_search_text(sentence)
        words = set(normalised.split())
        value = max(0, 40 - index)  # paragraf awal biasanya memuat lead berita
        if phrase and phrase in normalised:
            value += 40
        if query_tokens:
            value += 12 * sum(token in words or token in normalised for token in query_tokens)
        if title_tokens:
            value += 4 * sum(token in words or token in normalised for token in title_tokens[:8])
        if re.search(r"(?:\brp\s*\d[\d.,]*\b|\b\d+(?:[.,]\d+)?\s*(?:%|persen|rupiah|ribu|juta|miliar|triliun|kg|ton)\b)", sentence, re.IGNORECASE):
            value += 10
        if NEWS_VERB_RE.search(sentence):
            value += 6
        return value

    ranked = sorted(enumerate(sentences[:18]), key=lambda pair: score(pair[1], pair[0]), reverse=True)
    selected_indexes = sorted(index for index, _ in ranked[:3])
    selected = [sentences[index] for index in selected_indexes]
    info = _clean_text(" ".join(selected), limit)
    # Hindari potongan yang terputus di tengah kata/kalimat terlalu jauh.
    if len(info) >= limit - 1:
        cut = max(info.rfind(". ", 0, limit), info.rfind("; ", 0, limit), info.rfind(", ", 0, limit))
        if cut > 250:
            info = info[: cut + 1].strip()
    return info


def _rfc_datetime_to_iso(value: str, now: datetime | None = None) -> str:
    """Ubah tanggal RFC 2822/RSS ke ISO Jakarta bila bisa."""
    text = _clean_text(value, 200)
    if not text:
        return ""
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JAKARTA)
    return parsed.astimezone(JAKARTA).isoformat()


def _valid_url(value: Any) -> str:
    """Validasi dan kanonisasi URL agar deduplikasi tidak kalah oleh parameter tracking."""
    value = str(value or "").strip().rstrip(".,;:!?")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""

    kept_query: list[tuple[str, str]] = []
    for key, val in parse_qsl(parsed.query, keep_blank_values=False):
        key_lower = key.lower()
        if key_lower in TRACKING_QUERY_KEYS or any(
            key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES
        ):
            continue
        kept_query.append((key, val))

    normalised = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=urlencode(kept_query, doseq=True),
        fragment="",
    )
    return urlunparse(normalised)


def build_jina_reader_url(url: Any) -> str:
    """Bangun link baca versi bersih lewat Jina Reader tanpa menghilangkan URL asli.

    Format yang dipakai: https://r.jina.ai/https://example.com/artikel
    Link ini berguna sebagai opsi baca minim iklan/menu, sementara link asli tetap
    disimpan dan ditampilkan untuk membuka sumber penuh.
    """
    clean_url = _valid_url(url)
    if not clean_url:
        return ""
    parsed = urlparse(clean_url)
    if parsed.netloc.lower().removeprefix("www.") == "r.jina.ai":
        return clean_url
    return f"{JINA_READER_URL}{clean_url}"


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _article_id(url: str, title: str) -> str:
    return sha256(f"{url}|{title.lower()}".encode("utf-8")).hexdigest()[:20]


def _normalised_title(value: str) -> str:
    return re.sub(r"\W+", "", value.lower())


def _is_blocked_host(host: str) -> bool:
    return any(host == blocked or host.endswith(f".{blocked}") for blocked in BLOCKED_HOSTS)


def _is_social_host(host: str) -> bool:
    return any(host == social or host.endswith(f".{social}") for social in SOCIAL_HOSTS)


def _matches_known_host(host: str, domains: set[str]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _is_trusted_news_host(host: str) -> bool:
    return _matches_known_host(host, TRUSTED_NEWS_HOSTS)


def _social_label(host: str) -> str:
    for domain, label in SOCIAL_SOURCE_LABELS.items():
        if host == domain or host.endswith(f".{domain}"):
            return label
    return host


def _is_social_content_url(url: str) -> bool:
    """Terima postingan atau video individual, tolak halaman profil dan kanal sosial."""
    parsed = urlparse(url)
    host = _host(url)
    path = parsed.path.lower().rstrip("/")
    segments = [part for part in path.split("/") if part]
    query = parsed.query.lower()

    if host.endswith("instagram.com"):
        return bool(re.match(r"^/(?:p|reel|reels|tv)/[^/]+", path))
    if host.endswith(("youtube.com", "youtu.be")):
        return (
            (path == "/watch" and "v=" in query)
            or bool(re.match(r"^/(?:shorts|live|embed)/[^/]+", path))
            or (host.endswith("youtu.be") and len(segments) == 1 and len(segments[0]) >= 6)
        )
    if host.endswith("tiktok.com"):
        return bool(re.match(r"^/(?:@[^/]+/(?:video|photo)|video)/[^/]+", path))
    if host.endswith(("x.com", "twitter.com")):
        return bool(re.match(r"^/[^/]+/status/\d+", path))
    if host.endswith("threads.net"):
        return bool(re.match(r"^/(?:@[^/]+/(?:post|t)|t)/[^/]+", path))
    if host.endswith(("facebook.com", "fb.com")):
        return (
            bool(re.match(r"^/(?:reel|watch|share/(?:v|r)|[^/]+/posts)/", path))
            or (path == "/watch" and "v=" in query)
        )
    if host.endswith("linkedin.com"):
        return path.startswith("/posts/") or path.startswith("/feed/update/")
    if host.endswith("reddit.com"):
        return bool(re.match(r"^/r/[^/]+/comments/[^/]+", path))
    if host.endswith("pinterest.com"):
        return bool(re.match(r"^/pin/\d+", path))
    return False


def _looks_like_direct_article(title: str, url: str) -> bool:
    """Terima artikel penerbit. Konten sosial hanya boleh bila NEWS_ALLOW_SOCIAL=1."""
    title = _clean_text(title, 300)
    if len(title) < MIN_HEADLINE_LENGTH or not url:
        return False
    title_lower = title.casefold().strip()
    if title_lower.startswith(("image ", "gambar ", "logo ", "icon ", "img-alt")):
        return False
    if any(part in title_lower for part in BLOCKED_TITLE_PARTS):
        return False
    if any(part in title_lower for part in ("copyright", "iklan", "advertisement", "followers", "subscriber")):
        return False

    parsed = urlparse(url)
    host = _host(url)
    path = parsed.path.lower().rstrip("/")
    if _is_blocked_host(host) or not path:
        return False
    if path.endswith(IMAGE_SUFFIXES) or "/images/" in path or "/image/" in path:
        return False

    if _is_social_host(host):
        return configured_allow_social() and _is_social_content_url(url)

    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return False
    if any(segment in BLOCKED_URL_PARTS for segment in segments):
        return False
    # Halaman depan dan URL utility hampir selalu tidak menunjuk ke artikel.
    if len(segments) == 1:
        slug = segments[0]
        if slug in {"berita", "news", "home", "latest", "terkini"}:
            return False
        # Tautan satu-segmen yang pendek lazimnya merupakan kanal/program, bukan artikel.
        if len(slug) < 15:
            return False
    return True


def _looks_like_social_or_profile_context(*values: str) -> bool:
    """Tolak metadata akun untuk hasil non-sosial. Postingan sosial disaring menurut URL kontennya."""
    context = " ".join(_clean_text(value, 1200) for value in values if value)
    return bool(SOCIAL_ENGAGEMENT_RE.search(context) or NON_ARTICLE_CONTEXT_RE.search(context))


def _strip_social_metrics(value: str) -> str:
    """Hapus metrik akun atau engagement tanpa menghapus isi utama postingan."""
    retained: list[str] = []
    for line in str(value or "").splitlines():
        compact = _clean_text(line, 600)
        if not compact:
            continue
        if SOCIAL_ENGAGEMENT_RE.search(compact) or NON_ARTICLE_CONTEXT_RE.search(compact):
            continue
        retained.append(compact)
    return _clean_text(" ".join(retained), 600)


def _contains_keyword(text: str, keyword: str) -> bool:
    """Cocokkan kata atau frasa utuh agar `ai` tidak cocok dengan bagian kata lain."""
    pattern = rf"(?<!\w){re.escape(keyword.lower())}(?!\w)"
    return re.search(pattern, text.lower()) is not None


def classify_category(title: str, summary: str, url: str) -> tuple[str, str]:
    """Klasifikasikan dengan kata kunci judul, ringkasan, URL, dan domain sumber."""
    title_lower = title.lower()
    body_lower = f"{summary.lower()} {url.lower()}"
    host = _host(url)
    scores = {key: 0 for key in CATEGORY_ORDER}

    source_hint = SOURCE_CATEGORY_HINTS.get(host)
    if source_hint:
        scores[source_hint] += 6

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if _contains_keyword(title_lower, keyword):
                scores[category] += 4
            if _contains_keyword(body_lower, keyword):
                scores[category] += 1

    best_key = max(CATEGORY_ORDER, key=lambda key: scores[key])
    if scores[best_key] <= 0:
        best_key = "lainnya"
    return best_key, CATEGORY_LABELS[best_key]


def _is_today_from_text(value: str, now: datetime) -> tuple[bool, str]:
    """Tentukan apakah marker waktu berada pada tanggal Jakarta yang sama."""
    text = _clean_text(value, 1200)
    if not text:
        return False, ""
    lower = text.lower()
    if "kemarin" in lower or "yesterday" in lower or "hari lalu" in lower:
        return False, ""

    rfc_iso = _rfc_datetime_to_iso(text, now)
    if rfc_iso:
        parsed_dt = _as_jakarta(rfc_iso)
        return parsed_dt.date() == now.date(), parsed_dt.strftime("%Y-%m-%dT%H:%M:%S")

    # Tanggal eksplisit selalu lebih kuat daripada marker relatif.
    match = DAY_MONTH_RE.search(text)
    if match:
        day = int(match.group(1))
        month = MONTH_NUMBERS.get(match.group(2).lower(), 0)
        year = int(match.group(3) or now.year)
        try:
            parsed_day = date(year, month, day)
        except ValueError:
            return False, ""
        return parsed_day == now.date(), match.group(0).strip()

    match = NUMERIC_DATE_RE.search(text)
    if match:
        try:
            parsed_day = date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except ValueError:
            return False, ""
        return parsed_day == now.date(), match.group(0)

    match = ISO_DATE_RE.search(text)
    if match:
        try:
            parsed_day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return False, ""
        return parsed_day == now.date(), match.group(0)

    match = ENGLISH_DAY_MONTH_RE.search(text)
    if match:
        try:
            parsed_day = date(
                int(match.group(3)), ENGLISH_MONTH_NUMBERS[match.group(2).lower()], int(match.group(1))
            )
        except ValueError:
            return False, ""
        return parsed_day == now.date(), match.group(0)

    match = ENGLISH_DATE_RE.search(text)
    if match:
        try:
            parsed_day = date(
                int(match.group(3)), ENGLISH_MONTH_NUMBERS[match.group(1).lower()], int(match.group(2))
            )
        except ValueError:
            return False, ""
        return parsed_day == now.date(), match.group(0)

    match = RELATIVE_TIME_RE.search(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit == "jam":
            published = now - timedelta(hours=amount)
        elif unit == "menit":
            published = now - timedelta(minutes=amount)
        elif unit == "detik":
            published = now - timedelta(seconds=amount)
        else:
            published = now - timedelta(days=amount)
        return published.date() == now.date(), match.group(0)

    if re.search(r"\bhari\s+ini\b|\btoday\b", lower):
        return True, "Hari ini"
    return False, ""


def _extract_summary(context: str) -> str:
    """Ambil teks di sekitar artikel dan buang gambar, navigasi, serta metrik sosial."""
    useful: list[str] = []
    for line in context.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if RELATIVE_TIME_RE.search(line) or DAY_MONTH_RE.search(line) or NUMERIC_DATE_RE.search(line):
            continue
        # Hapus tautan Markdown agar menu dan URL panjang tidak menjadi ringkasan.
        line = re.sub(r"!?\[[^\]]+\]\([^)]*\)", "", line).strip(" -|:·")
        if SOCIAL_ENGAGEMENT_RE.search(line) or NON_ARTICLE_CONTEXT_RE.search(line):
            continue
        if len(line) < 35 or line.lower() in BLOCKED_TITLE_PARTS:
            continue
        useful.append(line)
        if len(" ".join(useful)) >= 400:
            break
    return _clean_text(" ".join(useful), 450)


def _has_publication_signal(value: str) -> bool:
    """True saat konteks memuat tanggal atau marker waktu publikasi apa pun."""
    text = _clean_text(value, 1400)
    lower = text.lower()
    return bool(
        RELATIVE_TIME_RE.search(text)
        or EN_RELATIVE_TIME_RE.search(text)
        or DAY_MONTH_RE.search(text)
        or NUMERIC_DATE_RE.search(text)
        or ISO_DATE_RE.search(text)
        or ENGLISH_DAY_MONTH_RE.search(text)
        or ENGLISH_DATE_RE.search(text)
        or re.search(r"\b(?:hari\s+ini|today|kemarin|yesterday)\b", lower)
    )


def _normalise_item(
    raw: dict[str, Any],
    detected_at: str,
    now: datetime,
    *,
    publication_context: str = "",
    allow_unverified: bool = False,
) -> dict[str, Any] | None:
    """Normalisasi tautan langsung, dengan fallback kandidat tanpa marker waktu.

    `allow_unverified` hanya digunakan sebagai lapisan terakhir di dashboard. Tautan
    dengan marker tanggal lama tetap ditolak. Kandidat tanpa marker waktu diberi status
    terpisah agar tidak keliru disebut berita hari ini dan tidak dapat dinotifikasi.
    """
    title = _clean_text(raw.get("title") or raw.get("name") or raw.get("headline"), 300)
    url = _valid_url(raw.get("url") or raw.get("link") or raw.get("href"))
    if not _looks_like_direct_article(title, url):
        return None

    host = _host(url)
    is_social = _is_social_host(host)
    description = _clean_text(
        raw.get("description")
        or raw.get("snippet")
        or raw.get("content")
        or raw.get("text")
        or raw.get("body"),
        600,
    )
    explicit_published = _clean_text(
        raw.get("published_at")
        or raw.get("publishedDate")
        or raw.get("datePublished")
        or raw.get("dateModified")
        or raw.get("timestamp")
        or raw.get("lastUpdated")
        or raw.get("created_at")
        or raw.get("date")
        or raw.get("pubDate")
        or raw.get("updated")
        or raw.get("published")
        or raw.get("time"),
        150,
    )
    time_context = f"{explicit_published}\n{publication_context}"
    is_today, published_at = _is_today_from_text(time_context, now)

    if is_today:
        time_status = "verified_today"
        time_note = "Waktu publikasi terdeteksi untuk hari ini."
    else:
        # Jangan pernah meloloskan artikel kemarin atau artikel bertanggal lama. Hanya
        # tautan tanpa marker waktu sama sekali yang boleh muncul sebagai kandidat audit.
        if not allow_unverified or _has_publication_signal(time_context):
            return None
        time_status = "needs_time_verification"
        published_at = "Waktu belum terdeteksi"
        time_note = "Waktu publikasi belum ditemukan di respons pencarian. Periksa waktu pada sumber asli."

    # Postingan sosial hanya bisa sampai sini bila NEWS_ALLOW_SOCIAL=1. Metrik seperti
    # likes dan subscribers tetap dibuang dari ringkasan.
    if is_social:
        description = _strip_social_metrics(description)
    elif _looks_like_social_or_profile_context(title, description, publication_context, url):
        return None

    category_key, category = classify_category(title, description, url)
    quality_score, quality_reasons = score_article_quality(
        title=title,
        summary=description,
        url=url,
        time_status=time_status,
        category_key=category_key,
        query="",
    )
    return {
        "id": _article_id(url, title),
        "title": title,
        "url": url,
        "source": _social_label(host) if is_social else host,
        "source_type": "social" if is_social else "publisher",
        "summary": description,
        "published_at": published_at or "Hari ini",
        "time_status": time_status,
        "time_note": time_note,
        "detected_at": detected_at,
        "category_key": category_key,
        "category": category,
        "quality_score": quality_score,
        "quality_reasons": quality_reasons,
    }


def _count_json_candidates(value: Any) -> int:
    """Hitung item JSON yang minimal punya judul dan URL untuk metrik audit."""
    if isinstance(value, dict):
        current = 1 if (
            (value.get("title") or value.get("name") or value.get("headline"))
            and (value.get("url") or value.get("link") or value.get("href"))
        ) else 0
        return current + sum(_count_json_candidates(child) for child in value.values())
    if isinstance(value, list):
        return sum(_count_json_candidates(child) for child in value)
    return 0


def _walk_json(
    value: Any,
    detected_at: str,
    now: datetime,
    *,
    allow_unverified: bool = False,
) -> list[dict[str, Any]]:
    """Dukung respons JSON tanpa mengunci ke satu skema Jina."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        publication_context = "\n".join(
            _clean_text(value.get(key), 1000)
            for key in ("content", "description", "snippet", "text", "body")
            if value.get(key)
        )
        item = _normalise_item(
            value,
            detected_at,
            now,
            publication_context=publication_context,
            allow_unverified=allow_unverified,
        )
        if item:
            found.append(item)
        for child in value.values():
            found.extend(
                _walk_json(child, detected_at, now, allow_unverified=allow_unverified)
            )
    elif isinstance(value, list):
        for child in value:
            found.extend(
                _walk_json(child, detected_at, now, allow_unverified=allow_unverified)
            )
    return found


def _context_near_link(text: str, start: int, end: int, following_limit: int = 900) -> str:
    """Ambil konteks sempit di kiri dan kanan tautan agar marker waktu tidak mudah terlewat."""
    before = text[max(0, start - 220):start]
    after = text[end:min(len(text), end + following_limit)]
    # Jika beberapa heading lain berada sebelum tautan, hanya simpan bagian setelah heading terakhir.
    heading_cut = max(before.rfind("\n#"), before.rfind("\n##"))
    if heading_cut >= 0:
        before = before[heading_cut:]
    return f"{before}\n{after}"


def _parse_markdown(
    text: str,
    detected_at: str,
    now: datetime,
    *,
    allow_unverified: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Ekstrak heading dan tautan Markdown yang mengarah ke artikel langsung."""
    items: list[dict[str, Any]] = []
    candidates = 0
    occupied_spans: list[tuple[int, int]] = []
    heading_matches = list(HEADING_LINK_RE.finditer(text))

    for index, match in enumerate(heading_matches):
        candidates += 1
        title, url = match.groups()
        next_start = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(text)
        after_context = text[match.end():min(next_start, match.end() + 1_100)]
        # Gunakan hanya blok setelah heading ini. Konteks lintas heading dapat mencampur
        # timestamp artikel berikutnya atau sebelumnya dengan artikel saat ini.
        publication_context = after_context
        item = _normalise_item(
            {"title": title, "url": url, "description": _extract_summary(after_context)},
            detected_at,
            now,
            publication_context=publication_context,
            allow_unverified=allow_unverified,
        )
        if item:
            items.append(item)
        occupied_spans.append(match.span())

    # Sebagian respons menuliskan tautan artikel tanpa heading. Tautan tersebut tetap
    # dapat diambil karena validasi URL dan konteks publikasi dijalankan terpisah.
    for match in LINK_RE.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in occupied_spans):
            continue
        candidates += 1
        title, url = match.groups()
        next_heading = text.find("\n#", match.end())
        end_context = next_heading if next_heading >= 0 else min(len(text), match.end() + 650)
        after_context = text[match.end():end_context]
        # Tautan inline umumnya diikuti marker waktu. Hindari menggabungkan blok heading lain.
        publication_context = after_context
        item = _normalise_item(
            {"title": title, "url": url, "description": _extract_summary(after_context)},
            detected_at,
            now,
            publication_context=publication_context,
            allow_unverified=allow_unverified,
        )
        if item:
            items.append(item)
    return items, candidates



def _normalise_search_text(text: str) -> str:
    """Samakan teks agar pencocokan frasa tidak mudah rusak oleh tanda baca."""
    lowered = text.casefold()
    lowered = re.sub(r"[^a-zA-ZÀ-ÿ0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _meaningful_query_tokens(query: str) -> list[str]:
    """Token kueri dalam urutan asli, bukan set.

    Ini penting untuk kueri seperti "harga telur": frasa tersebut adalah intent utuh,
    bukan dua pencarian longgar "harga" OR "telur".
    """
    cleaned = _strip_query_noise(query)
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]{2,}", cleaned.casefold())
    return [
        token for token in tokens
        if token not in QUERY_STOPWORDS
        and token not in GENERIC_QUERY_TERMS
        and not token.isdigit()
        and not re.fullmatch(r"20\d{2}", token)
        and token not in {month.casefold() for month in MONTHS_ID}
    ]


def _specific_query_token_list(query: str) -> list[str]:
    """Token niat pencarian yang benar-benar berasal dari input pengguna."""
    tokens = _meaningful_query_tokens(query)
    if len(set(tokens) & CATEGORY_SEED_TERMS) >= 6:
        return []
    unique: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token not in seen:
            unique.append(token)
            seen.add(token)
    return unique


def _query_terms(query: str) -> set[str]:
    """Ambil kata bermakna dari kueri untuk menilai relevansi hasil."""
    return set(_specific_query_token_list(query))


def _specific_query_terms(query: str) -> set[str]:
    """Term niat pencarian yang benar-benar berasal dari input pengguna.

    Kueri default berisi banyak kategori agar dashboard awal tetap luas. Untuk kolom
    search, term seperti "berita", "hari ini", tanggal, dan daftar kategori default
    tidak boleh membuat RSS umum terlihat relevan secara palsu.
    """
    return set(_specific_query_token_list(query))


def _specific_query_phrase(query: str) -> str:
    """Frasa pencarian utama, misalnya "harga telur".

    Frasa ini dipakai sebagai sinyal utama untuk SERP dan scoring. Token individual
    hanya menjadi pendukung setelah semua term cocok, bukan syarat OR yang longgar.
    """
    tokens = _specific_query_token_list(query)
    if len(tokens) < 2:
        return ""
    return " ".join(tokens)


def _query_is_specific(query: str) -> bool:
    return bool(_specific_query_terms(query))


def _query_match_level(text: str, query: str) -> str:
    """Kembalikan level kecocokan intent: exact_phrase, all_terms, partial, none."""
    tokens = _specific_query_token_list(query)
    if not tokens:
        return "none"

    normalised_text = _normalise_search_text(text)
    if not normalised_text:
        return "none"

    phrase = _specific_query_phrase(query)
    if phrase and phrase in normalised_text:
        return "exact_phrase"

    words = set(normalised_text.split())
    matched = [token for token in tokens if token in words or token in normalised_text]
    if len(matched) == len(tokens):
        return "all_terms"
    if matched:
        return "partial"
    return "none"


def _matches_query_intent(item: dict[str, Any], query: str) -> bool:
    """True bila artikel sesuai niat search; kueri umum tidak difilter ketat.

    Untuk kueri multi-kata, semua term harus cocok, dan frasa utuh diberi prioritas.
    Contoh: "harga telur" tidak boleh lolos hanya karena judul berisi "harga" saja
    atau "telur" saja.
    """
    if not _query_is_specific(query):
        return True
    combined = " ".join(
        str(item.get(key, ""))
        for key in ("title", "summary", "url", "source", "category", "category_key")
    )
    return _query_match_level(combined, query) in {"exact_phrase", "all_terms"}


def _path_article_score(url: str) -> tuple[int, list[str]]:
    parsed = urlparse(url)
    path = parsed.path.lower().strip("/")
    segments = [segment for segment in path.split("/") if segment]
    score = 0
    reasons: list[str] = []

    if re.search(r"/(?:20\d{2})/(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])(?:/|$)", f"/{path}/"):
        score += 12
        reasons.append("URL memuat pola tanggal artikel")
    if any(segment in KNOWN_NEWS_PATH_HINTS for segment in segments):
        score += 8
        reasons.append("URL berada pada kanal berita")
    if segments:
        slug = segments[-1]
        hyphen_words = [part for part in re.split(r"[-_]", slug) if len(part) >= 3]
        if len(hyphen_words) >= 4 or len(slug) >= 32:
            score += 10
            reasons.append("slug terlihat seperti judul artikel")
        elif len(slug) < 16 and not slug.isdigit():
            score -= 12
            reasons.append("slug terlalu pendek untuk artikel")
    return score, reasons


def score_article_quality(
    *,
    title: str,
    summary: str,
    url: str,
    time_status: str,
    category_key: str,
    query: str = "",
) -> tuple[int, list[str]]:
    """Skor heuristik agar hasil SERP tidak asal direct link.

    Parser tetap transparan dan deterministic: artikel dengan waktu hari ini, sumber editorial,
    judul informatif, URL artikel, serta relevansi kueri mendapat prioritas tinggi.
    """
    score = 0
    reasons: list[str] = []
    title_clean = _clean_text(title, 300)
    summary_clean = _clean_text(summary, 900)
    title_lower = title_clean.casefold()
    combined = f"{title_clean} {summary_clean} {url}".casefold()
    host = _host(url)
    is_social = _is_social_host(host)

    if time_status == "verified_today":
        score += 42
        reasons.append("waktu publikasi terverifikasi hari ini")
    else:
        score += 8
        reasons.append("waktu publikasi belum terverifikasi")

    if _is_trusted_news_host(host):
        score += 14
        reasons.append("domain editorial tepercaya")
    elif is_social:
        score -= 12
        reasons.append("konten sosial perlu verifikasi ekstra")
    else:
        score += 4
        reasons.append("domain penerbit langsung")

    path_score, path_reasons = _path_article_score(url)
    score += path_score
    reasons.extend(path_reasons)

    title_len = len(title_clean)
    if 35 <= title_len <= 160:
        score += 12
        reasons.append("judul cukup informatif")
    elif title_len < 25:
        score -= 15
        reasons.append("judul terlalu pendek/generik")

    if NEWS_VERB_RE.search(title_clean):
        score += 5
        reasons.append("judul berisi aksi/peristiwa berita")
    if LOW_QUALITY_TITLE_RE.search(title_clean):
        score -= 22
        reasons.append("judul mengandung sinyal non-berita")
    if CLICKBAIT_TITLE_RE.search(title_clean):
        score -= 7
        reasons.append("judul mengandung sinyal clickbait")

    if summary_clean:
        if len(summary_clean) >= 90:
            score += 6
            reasons.append("ringkasan cukup kaya")
        else:
            score += 2
    else:
        # Mode cepat `X-Respond-With: no-content` dari Jina sering tidak membawa isi penuh.
        # Jangan hukum terlalu keras bila artikel sudah punya judul, URL, dan waktu valid.
        if time_status == "verified_today":
            score -= 1
        else:
            score -= 5
            reasons.append("ringkasan kosong")

    terms = _specific_query_terms(query)
    if terms:
        match_level = _query_match_level(combined, query)
        if match_level == "exact_phrase":
            score += 20
            reasons.append("frasa search cocok")
        elif match_level == "all_terms":
            score += 12
            reasons.append("semua kata kunci search cocok")
        elif match_level == "partial":
            score -= 18
            reasons.append("hanya cocok sebagian dengan search")
        else:
            score -= 32
            reasons.append("tidak sesuai kata kunci search")

    if category_key == "lainnya":
        score -= 4
        reasons.append("kategori belum kuat")
    else:
        score += 4

    return max(0, min(score, 100)), reasons[:6]


def _apply_quality_scores(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for item in items:
        quality_score, quality_reasons = score_article_quality(
            title=str(item.get("title", "")),
            summary=str(item.get("summary", "")),
            url=str(item.get("url", "")),
            time_status=str(item.get("time_status", "")),
            category_key=str(item.get("category_key", "lainnya")),
            query=query,
        )
        enriched = dict(item)
        enriched["quality_score"] = quality_score
        enriched["quality_reasons"] = quality_reasons
        scored.append(enriched)
    return scored


def _rank_and_filter(items: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
    """Urutkan dan tahan hasil berkualitas rendah agar dashboard tidak sekadar daftar link."""
    scored = _apply_quality_scores(items, query)
    strict_relevance = _query_is_specific(query)
    filtered = []
    for item in scored:
        if strict_relevance and not _matches_query_intent(item, query):
            continue
        if (
            item.get("time_status") == "verified_today"
            and int(item.get("quality_score", 0)) >= MIN_VERIFIED_QUALITY_SCORE
        ) or (
            item.get("time_status") == "needs_time_verification"
            and int(item.get("quality_score", 0)) >= MIN_UNVERIFIED_QUALITY_SCORE
        ):
            filtered.append(item)
    filtered.sort(
        key=lambda item: (
            item.get("time_status") == "verified_today",
            int(item.get("quality_score", 0)),
            item.get("source_type") == "publisher",
        ),
        reverse=True,
    )
    return _deduplicate(filtered, limit)


def _deduplicate(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for item in items:
        url_key = item["url"].rstrip("/").lower()
        title_key = _normalised_title(item["title"])
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def parse_search_response_details(
    payload: str | dict[str, Any] | list[Any],
    detected_at: str,
    limit: int = 20,
    *,
    allow_unverified_fallback: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Ubah respons Jina menjadi artikel hari ini dan kandidat audit bila diperlukan."""
    now = _as_jakarta(detected_at)
    parsed: Any = payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = None

    raw_candidates = 0
    if parsed is not None:
        raw_candidates = _count_json_candidates(parsed)
        items = _walk_json(parsed, detected_at, now)
    elif isinstance(payload, str):
        items, raw_candidates = _parse_markdown(payload, detected_at, now)
    else:
        items = []

    verified_articles = _deduplicate(items, limit)
    used_unverified_fallback = False
    if not verified_articles and allow_unverified_fallback:
        if parsed is not None:
            fallback_items = _walk_json(parsed, detected_at, now, allow_unverified=True)
        elif isinstance(payload, str):
            fallback_items, fallback_candidates = _parse_markdown(
                payload, detected_at, now, allow_unverified=True
            )
            raw_candidates = max(raw_candidates, fallback_candidates)
        else:
            fallback_items = []
        items = fallback_items
        used_unverified_fallback = bool(items)
    else:
        items = verified_articles

    articles = _deduplicate(items, limit)
    verified_count = sum(item.get("time_status") == "verified_today" for item in articles)
    return articles, {
        "raw_candidates": raw_candidates,
        "today_articles": verified_count,
        "unverified_articles": sum(item.get("time_status") == "needs_time_verification" for item in articles),
        "used_unverified_fallback": int(used_unverified_fallback),
    }


def parse_search_response(
    payload: str | dict[str, Any] | list[Any], detected_at: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Kompatibilitas publik untuk parser artikel yang waktu publikasinya terverifikasi hari ini."""
    articles, _ = parse_search_response_details(payload, detected_at, limit)
    return articles



def _domain_filter_query(domains: tuple[str, ...] | list[str] | str | None) -> str:
    """Kembalikan filter satu domain untuk Jina.

    Versi sebelumnya membuat `(site:a OR site:b) ... -site:x ...`. Query seperti itu
    memang valid untuk sebagian mesin pencari, tetapi pada `s.jina.ai` bisa ditolak
    sebagai 422. Karena itu Jina sekarang dipanggil dengan query pendek per-domain.
    """
    if isinstance(domains, str):
        domain = domains
    else:
        domain = next(iter(domains or PUBLISHER_SEARCH_GROUPS[0]), "")
    domain = re.sub(r"[^a-z0-9_.-]", "", str(domain).casefold()).strip(".-")
    return f"site:{domain}" if domain else ""


def _strip_query_noise(query: str) -> str:
    """Buang operator/istilah yang membuat SERP lari ke sosial atau invalid."""
    cleaned = re.sub(
        r"\b(?:youtube|instagram|tiktok|facebook|twitter|threads|x\.com|google news|news\.google\.com)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"-site:\S+", " ", cleaned)
    cleaned = re.sub(r"\bsite:\S+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = JINA_QUERY_OPERATOR_RE.sub(" ", cleaned)
    cleaned = cleaned.replace('"', " ").replace("'", " ")
    return _clean_text(cleaned, 240)


def _serp_query_intent(primary_query: str, now: datetime | None = None) -> str:
    """Bentuk intent untuk SERP tanpa memecah frasa input user.

    Frasa tetap dijaga dari sisi token berurutan, tetapi tidak dibungkus quote agar
    request Jina tidak berubah menjadi query kompleks yang rawan 422.
    """
    now = _as_jakarta(now)
    base = _strip_query_noise(primary_query) or default_query(now)
    phrase = _specific_query_phrase(base)
    if phrase:
        return phrase
    tokens = _specific_query_token_list(base)
    if tokens:
        return " ".join(tokens[:6])
    return base


def source_scoped_query(primary_query: str, now: datetime | None = None, domains: tuple[str, ...] | list[str] | str | None = None) -> str:
    """Buat query Jina yang sederhana dan aman dari 422.

    Setiap request hanya memakai satu `site:domain`. Filter negatif sosial/video tidak
    dikirim ke Jina; pemblokiran dilakukan deterministic di parser. Ini membuat bot
    Telegram tidak gagal hanya karena Jina menolak sintaks query yang terlalu ramai.
    """
    now = _as_jakarta(now)
    today = today_indonesia(now)
    base = _serp_query_intent(primary_query, now)
    domain_filter = _domain_filter_query(domains or PUBLISHER_SEARCH_GROUPS[0][0])
    parts = [domain_filter, base, "berita", "hari ini", today]
    return _jina_safe_query(" ".join(part for part in parts if part))


def _jina_safe_query(query: str, *, limit: int = 260) -> str:
    """Sanitasi defensif sebelum dikirim ke `s.jina.ai`.

    Jina Search menerima query teks biasa. Operator kompleks, quote, kurung, dan
    negative-site panjang tidak diperlukan karena validasi artikel sudah dilakukan
    setelah respons diterima.
    """
    text = str(query or "")
    text = re.sub(r"-site:\S+", " ", text)
    text = JINA_QUERY_OPERATOR_RE.sub(" ", text)
    text = text.replace('"', " ").replace("'", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].strip() or text[:limit].strip()
    return text


def _jina_retry_query(query: str, now: datetime | None = None) -> str:
    """Query fallback saat Jina menolak request pertama dengan 422."""
    now = _as_jakarta(now)
    intent = _serp_query_intent(query, now)
    # Hilangkan semua site: agar retry memakai query umum yang pendek.
    intent = re.sub(r"\bsite:\S+", " ", intent, flags=re.IGNORECASE)
    return _jina_safe_query(f"{intent} berita Indonesia {today_indonesia(now)}", limit=180)


def fallback_queries(primary_query: str, now: datetime | None = None) -> list[str]:
    """Buat kueri cadangan per-domain agar Jina tidak menerima OR/kurung kompleks."""
    now = _as_jakarta(now)
    base = _strip_query_noise(primary_query)
    # Interleave domain besar dan domain spesifik agar max_search_rounds kecil tetap layak.
    domains = (
        "kompas.com", "detik.com", "cnnindonesia.com", "cnbcindonesia.com", "tempo.co",
        "antaranews.com", "liputan6.com", "bisnis.com", "katadata.co.id", "kontan.co.id",
        "republika.co.id", "kumparan.com", "tirto.id", "suara.com", "okezone.com",
    )
    candidates = [source_scoped_query(base, now, domain) for domain in domains]
    # Cadangan umum tetap sederhana, tanpa operator OR/negative-site. Parser akan
    # membuang sosial/video/Google News kalau muncul.
    candidates.append(_jina_safe_query(f"{_serp_query_intent(base, now)} berita Indonesia hari ini {today_indonesia(now)}"))
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = _jina_safe_query(candidate)
        key = candidate.casefold()
        if candidate and key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _xml_text(element: ElementTree.Element, *names: str) -> str:
    for name in names:
        found = element.find(name)
        if found is not None and found.text:
            return found.text.strip()
        for child in list(element):
            tag = child.tag.split("}")[-1].lower()
            if tag == name.lower() and child.text:
                return child.text.strip()
    return ""


def _xml_link(element: ElementTree.Element) -> str:
    link = _xml_text(element, "link")
    if link:
        return link
    for child in list(element):
        tag = child.tag.split("}")[-1].lower()
        if tag == "link":
            href = child.attrib.get("href", "").strip()
            rel = child.attrib.get("rel", "alternate")
            if href and rel in {"alternate", ""}:
                return href
    return ""


def _rss_items_from_xml(xml_text: str, *, feed_source: str, detected_at: str, now: datetime) -> list[dict[str, Any]]:
    """Parse RSS/Atom penerbit resmi menjadi item artikel."""
    try:
        root = ElementTree.fromstring(xml_text.encode("utf-8"))
    except ElementTree.ParseError:
        return []

    nodes = list(root.findall(".//item"))
    if not nodes:
        nodes = [node for node in root.findall(".//{*}entry")]

    articles: list[dict[str, Any]] = []
    for node in nodes[:30]:
        title = _strip_html(_xml_text(node, "title"), 300)
        url = _valid_url(_xml_link(node))
        pub_raw = (
            _xml_text(node, "pubDate")
            or _xml_text(node, "published")
            or _xml_text(node, "updated")
            or _xml_text(node, "date")
        )
        pub_iso = _rfc_datetime_to_iso(pub_raw, now) or pub_raw
        summary = _strip_html(
            _xml_text(node, "description")
            or _xml_text(node, "summary")
            or _xml_text(node, "content")
            or _xml_text(node, "encoded"),
            600,
        )
        item = _normalise_item(
            {
                "title": title,
                "url": url,
                "description": summary,
                "timestamp": pub_iso,
                "source": feed_source,
            },
            detected_at,
            now,
            publication_context=pub_iso,
        )
        if item:
            # RSS berasal dari feed penerbit, jadi tampilkan root/domain penerbit sebagai sumber.
            item["source"] = _host(url) or feed_source
            item["source_type"] = "publisher"
            articles.append(item)
    return articles


def _fetch_one_rss(feed: dict[str, str], *, detected_at: str, now: datetime, timeout: int) -> tuple[list[dict[str, Any]], str]:
    url = feed["url"]
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "news-monitor-streamlit/5.0-rss-first"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        return [], f"## RSS {feed.get('source', url)}\nERROR: {error}"
    items = _rss_items_from_xml(
        response.text,
        feed_source=feed.get("source", ""),
        detected_at=detected_at,
        now=now,
    )
    preview = response.text[:2_000].strip()
    return items, f"## RSS {feed.get('source', url)}\nURL: {url}\nArtikel hari ini terdeteksi: {len(items)}\n\n{preview}"


def fetch_rss_articles(
    query: str,
    max_results: int,
    *,
    now: datetime,
    timeout: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """Ambil artikel dari RSS penerbit resmi sebelum memakai Jina SERP umum."""
    detected_at = now.isoformat()
    metadata = {
        "rss_enabled": str(configured_enable_rss()).lower(),
        "rss_articles": "0",
        "rss_feeds_checked": "0",
        "rss_timeout_seconds": str(configured_rss_timeout(timeout or DEFAULT_RSS_TIMEOUT)),
    }
    if not configured_enable_rss():
        return [], metadata, ""

    feed_limit = configured_max_rss_feeds()
    feeds = list(RSS_FEEDS[:feed_limit])
    if not feeds:
        return [], metadata, ""

    per_feed_timeout = configured_rss_timeout(timeout or DEFAULT_RSS_TIMEOUT)
    all_items: list[dict[str, Any]] = []
    raw_sections: list[str] = []
    workers = min(6, len(feeds))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_fetch_one_rss, feed, detected_at=detected_at, now=now, timeout=per_feed_timeout)
            for feed in feeds
        ]
        for future in as_completed(futures):
            items, raw = future.result()
            all_items.extend(items)
            if raw:
                raw_sections.append(raw)

    ranked = _rank_and_filter(all_items, query, max_results)
    metadata.update(
        {
            "rss_articles": str(len(ranked)),
            "rss_feeds_checked": str(len(feeds)),
        }
    )
    return ranked, metadata, "\n\n---\n\n".join(raw_sections)


def fetch_raw_markdown(
    api_key: str,
    query: str | None = None,
    timeout: int | None = None,
    *,
    now: datetime | None = None,
    respond_with: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Ambil respons mentah dari Jina Search.

    Dokumentasi Jina menyarankan `s.jina.ai/?q=` untuk SERP dan `Accept: application/json`
    untuk hasil terstruktur berisi URL, judul, konten, dan timestamp bila tersedia.
    Parser tetap mendukung Markdown sebagai fallback bila endpoint mengembalikannya.
    """
    if not api_key:
        raise ValueError("JINA_API_KEY belum diatur.")

    current_now = _as_jakarta(now)
    query = (query or source_scoped_query(default_query(current_now), current_now)).strip()
    request_timeout = configured_request_timeout(timeout or DEFAULT_REQUEST_TIMEOUT)
    page_timeout = configured_jina_page_timeout(min(request_timeout, DEFAULT_JINA_PAGE_TIMEOUT))
    response_mode = (respond_with or configured_jina_respond_with()).strip().lower()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "X-Respond-With": response_mode,
        "X-Retain-Images": "none",
        "X-Md-Link-Style": "discarded",
        "X-Timeout": str(page_timeout),
        "User-Agent": "news-monitor-streamlit/4.1-fast",
    }
    query = _jina_safe_query(query)

    def do_request(search_query: str) -> requests.Response:
        return requests.get(
            JINA_SEARCH_URL,
            params={"q": search_query},
            headers=headers,
            timeout=request_timeout,
        )

    response = do_request(query)
    retried_after_422 = False
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        status_code = getattr(error.response, "status_code", None) if error.response is not None else None
        if status_code != 422:
            raise
        retry_query = _jina_retry_query(query, current_now)
        if not retry_query or retry_query == query:
            raise
        response = do_request(retry_query)
        response.raise_for_status()
        query = retry_query
        retried_after_422 = True

    raw_markdown = response.text.strip()
    if not raw_markdown:
        raise ValueError("Jina tidak mengembalikan isi respons.")

    metadata = {
        "query": query,
        "fetched_at": current_now.isoformat(),
        "today_jakarta": today_indonesia(current_now),
        "content_type": response.headers.get("content-type", "tidak diketahui"),
        "response_format": "json_preferred",
        "jina_retried_after_422": str(retried_after_422).lower(),
        "jina_respond_with": response_mode,
        "request_timeout_seconds": str(request_timeout),
        "jina_page_timeout_seconds": str(page_timeout),
        "quality_threshold_verified": str(MIN_VERIFIED_QUALITY_SCORE),
        "quality_threshold_unverified": str(MIN_UNVERIFIED_QUALITY_SCORE),
    }
    return raw_markdown, metadata


def _reader_content_from_payload(payload: str) -> str:
    """Ambil field konten dari respons Jina Reader JSON/markdown secara fleksibel."""
    text = str(payload or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text

    def first_content(value: Any) -> str:
        if isinstance(value, dict):
            for key in ("content", "text", "markdown", "description", "snippet", "body"):
                current = value.get(key)
                if isinstance(current, str) and current.strip():
                    return current
            for key in ("data", "result", "article"):
                current = first_content(value.get(key))
                if current:
                    return current
            for child in value.values():
                current = first_content(child)
                if current:
                    return current
        elif isinstance(value, list):
            for child in value:
                current = first_content(child)
                if current:
                    return current
        return ""

    return first_content(parsed)


def fetch_article_information(
    api_key: str,
    article: dict[str, Any],
    *,
    query: str = "",
    timeout: int | None = None,
) -> tuple[str, str]:
    """Scrape satu artikel dengan Jina Reader dan kembalikan informasi utamanya.

    Endpoint Reader mengubah URL artikel menjadi teks ramah LLM, sehingga aplikasi dapat
    menampilkan inti informasi tanpa user harus membuka website sumber.
    """
    url = _valid_url(article.get("url"))
    if not url:
        return "", "URL artikel tidak valid"

    request_timeout = configured_article_scrape_timeout(timeout or DEFAULT_ARTICLE_SCRAPE_TIMEOUT)
    headers = {
        "Accept": "application/json",
        "X-Retain-Images": "none",
        "X-Md-Link-Style": "discarded",
        "X-Timeout": str(request_timeout),
        "User-Agent": "news-monitor-streamlit/6.0-info-scrape",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    response = requests.get(
        f"{JINA_READER_URL}{url}",
        headers=headers,
        timeout=request_timeout + 3,
    )
    response.raise_for_status()
    content = _reader_content_from_payload(response.text)
    info = extract_article_information(
        content,
        title=str(article.get("title", "")),
        query=query,
    )
    if not info:
        return "", "Reader tidak menemukan isi artikel yang cukup informatif"
    return info, "scraped_with_jina_reader"


def enrich_articles_with_scraped_info(
    api_key: str,
    articles: list[dict[str, Any]],
    *,
    query: str = "",
    timeout: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Perkaya artikel akhir dengan informasi utama hasil scrape secara paralel."""
    metadata = {
        "article_scrape_enabled": str(configured_enable_article_scrape()).lower(),
        "article_scrape_attempted": "0",
        "article_scrape_success": "0",
        "article_scrape_timeout_seconds": str(configured_article_scrape_timeout(timeout or DEFAULT_ARTICLE_SCRAPE_TIMEOUT)),
    }
    if not articles or not configured_enable_article_scrape():
        return articles, metadata

    scrape_limit = min(configured_max_article_scrapes(), len(articles))
    metadata["article_scrape_limit"] = str(scrape_limit)
    if scrape_limit <= 0:
        return articles, metadata

    enriched = [dict(item) for item in articles]
    workers = min(5, scrape_limit)
    attempted = 0
    success = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                fetch_article_information,
                api_key,
                enriched[index],
                query=query,
                timeout=timeout,
            ): index
            for index in range(scrape_limit)
        }
        attempted = len(futures)
        for future in as_completed(futures):
            index = futures[future]
            try:
                info, status = future.result()
            except requests.RequestException as error:
                enriched[index]["scrape_status"] = f"reader_error: {error}"
                continue
            if info:
                enriched[index]["scraped_info"] = info
                enriched[index]["summary"] = info
                enriched[index]["scrape_status"] = status
                success += 1
            else:
                enriched[index]["scrape_status"] = status

    metadata.update(
        {
            "article_scrape_attempted": str(attempted),
            "article_scrape_success": str(success),
        }
    )
    return enriched, metadata


def _fetch_rounds(
    api_key: str,
    query: str | None,
    max_results: int,
    timeout: int | None,
    *,
    allow_unverified_fallback: bool,
    max_search_rounds: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """RSS penerbit resmi dulu, lalu Jina Search source-scoped bila hasil belum cukup."""
    now = jakarta_now()
    primary_query = (query or default_query(now)).strip()
    target_results = min(max_results, QUALITY_TARGET_RESULTS)
    raw_sections: list[str] = []
    metadata: dict[str, str] = {
        "query": primary_query,
        "fetched_at": now.isoformat(),
        "today_jakarta": today_indonesia(now),
        "content_type": "mixed/rss+jina",
        "response_format": "rss_first_json_preferred",
        "jina_respond_with": configured_jina_respond_with(),
        "request_timeout_seconds": str(configured_request_timeout(timeout or DEFAULT_REQUEST_TIMEOUT)),
        "jina_page_timeout_seconds": str(configured_jina_page_timeout(min(timeout or DEFAULT_REQUEST_TIMEOUT, DEFAULT_JINA_PAGE_TIMEOUT))),
        "quality_threshold_verified": str(MIN_VERIFIED_QUALITY_SCORE),
        "quality_threshold_unverified": str(MIN_UNVERIFIED_QUALITY_SCORE),
    }

    rss_items, rss_metadata, rss_raw = fetch_rss_articles(primary_query, max_results, now=now)
    metadata.update(rss_metadata)
    if rss_raw:
        raw_sections.append(f"# Respons RSS penerbit resmi\n\n{rss_raw}")

    articles = _rank_and_filter(rss_items, primary_query, max_results)
    parsed_rounds: list[tuple[list[dict[str, Any]], dict[str, int], str]] = []

    # Bila RSS resmi sudah cukup, jangan panggil Jina sama sekali. Ini jauh lebih cepat dan
    # menghindari SERP sosial/video yang kurang relevan.
    configured_round_limit = configured_max_search_rounds() if max_search_rounds is None else max_search_rounds
    round_limit = max(0, min(configured_round_limit, len(PUBLISHER_SEARCH_GROUPS)))
    if len(articles) < target_results and round_limit > 0:
        if not api_key:
            raise ValueError("JINA_API_KEY belum diatur dan hasil RSS belum cukup.")
        all_queries = fallback_queries(primary_query, now)
        queries = all_queries[:round_limit]
        for index, search_query in enumerate(queries):
            try:
                raw_markdown, round_metadata = fetch_raw_markdown(
                    api_key, query=search_query, timeout=timeout, now=now
                )
            except requests.HTTPError as error:
                status_code = getattr(error.response, "status_code", None) if error.response is not None else None
                if status_code in {401, 403}:
                    raise
                metadata["last_jina_error"] = str(error)
                raw_sections.append(
                    f"# Respons pencarian Jina {index + 1}\n\nQuery: {search_query}\n\nERROR: {error}"
                )
                continue
            except requests.RequestException as error:
                metadata["last_jina_error"] = str(error)
                raw_sections.append(
                    f"# Respons pencarian Jina {index + 1}\n\nQuery: {search_query}\n\nERROR: {error}"
                )
                continue
            metadata.update({
                "content_type": round_metadata.get("content_type", metadata.get("content_type", "")),
                "response_format": round_metadata.get("response_format", metadata.get("response_format", "")),
                "jina_retried_after_422": round_metadata.get("jina_retried_after_422", metadata.get("jina_retried_after_422", "false")),
                "jina_respond_with": round_metadata.get("jina_respond_with", metadata.get("jina_respond_with", "")),
                "request_timeout_seconds": round_metadata.get("request_timeout_seconds", metadata.get("request_timeout_seconds", "")),
                "jina_page_timeout_seconds": round_metadata.get("jina_page_timeout_seconds", metadata.get("jina_page_timeout_seconds", "")),
            })
            actual_query = round_metadata.get("query", search_query)
            raw_sections.append(f"# Respons pencarian Jina {index + 1}\n\nQuery: {actual_query}\n\n{raw_markdown}")
            verified, stats = parse_search_response_details(
                raw_markdown, round_metadata["fetched_at"], max_results
            )
            parsed_rounds.append((verified, stats, actual_query))

            combined_verified: list[dict[str, Any]] = [*_apply_quality_scores(rss_items, primary_query)]
            for items, _, item_query in parsed_rounds:
                combined_verified.extend(_apply_quality_scores(items, item_query))
            articles = _rank_and_filter(combined_verified, primary_query, max_results)
            if len(articles) >= target_results:
                break

    used_unverified = False
    if not articles and allow_unverified_fallback and parsed_rounds:
        unverified_items: list[dict[str, Any]] = []
        for raw_section, (_, _, item_query) in zip(raw_sections, parsed_rounds):
            raw = raw_section.split("\n\n", 2)[-1] if "\n\n" in raw_section else raw_section
            items, _ = parse_search_response_details(
                raw,
                metadata["fetched_at"],
                max_results,
                allow_unverified_fallback=True,
            )
            unverified_items.extend(_apply_quality_scores(items, item_query))
        articles = _rank_and_filter(unverified_items, primary_query, max_results)
        used_unverified = bool(articles)

    articles, scrape_metadata = enrich_articles_with_scraped_info(
        api_key,
        articles,
        query=primary_query,
        timeout=timeout,
    )

    raw_candidates = sum(stats["raw_candidates"] for _, stats, _ in parsed_rounds)
    raw_candidates += len(rss_items)
    verified_count = sum(item.get("time_status") == "verified_today" for item in articles)
    unverified_count = sum(item.get("time_status") == "needs_time_verification" for item in articles)
    metadata.update(
        {
            "result_count": str(len(articles)),
            "raw_candidates": str(raw_candidates),
            "today_articles": str(verified_count),
            "unverified_articles": str(unverified_count),
            "search_rounds": str(len(parsed_rounds)),
            "fallback_search_used": "true" if parsed_rounds else "false",
            "max_search_rounds": str(round_limit),
            "target_results_for_fast_stop": str(target_results),
            "strict_query_relevance": "true" if _query_is_specific(primary_query) else "false",
            "query_terms": ", ".join(_specific_query_token_list(primary_query)),
            "query_phrase": _specific_query_phrase(primary_query),
            "result_mode": "verified_today" if verified_count else (
                "needs_time_verification" if used_unverified else "none"
            ),
        }
    )
    metadata.update(scrape_metadata)
    return articles, metadata, "\n\n---\n\n".join(raw_sections)


def fetch_news(
    api_key: str,
    query: str | None = None,
    max_results: int = 20,
    timeout: int | None = None,
    max_search_rounds: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Ambil berita terverifikasi dari RSS/Jina, atau kandidat audit bila waktu tidak tersedia."""
    articles, metadata, _ = _fetch_rounds(
        api_key,
        query,
        max_results,
        timeout,
        allow_unverified_fallback=True,
        max_search_rounds=max_search_rounds,
    )
    return articles, metadata


def fetch_news_with_raw(
    api_key: str,
    query: str | None = None,
    max_results: int = 20,
    timeout: int | None = None,
    max_search_rounds: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """Varian Streamlit dengan RSS/Jina mentah untuk audit."""
    return _fetch_rounds(
        api_key,
        query,
        max_results,
        timeout,
        allow_unverified_fallback=True,
        max_search_rounds=max_search_rounds,
    )
