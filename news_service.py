"""Ambil, saring, kategorikan, dan normalisasi berita dari Jina Search.

Modul hanya menghasilkan tautan artikel penerbit atau tautan postingan sosial
individual. Gambar, profil, metrik engagement, iklan, menu, halaman kategori,
dan perantara seperti Google News dikeluarkan.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests

JAKARTA = ZoneInfo("Asia/Jakarta")
JINA_SEARCH_URL = "https://s.jina.ai/"
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
# Mesin pencari dan URL utilitas tidak boleh muncul sebagai hasil berita.
# Platform sosial tidak diblokir di sini karena postingan atau video individual dapat menjadi konten berita.
BLOCKED_HOSTS = {
    "google.com", "news.google.com", "googleusercontent.com", "jina.ai", "s.jina.ai",
    "bit.ly", "tinyurl.com",
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
    "t.me": "Telegram",
    "telegram.me": "Telegram",
    "pinterest.com": "Pinterest",
}
SOCIAL_HOSTS = frozenset(SOCIAL_SOURCE_LABELS)

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
QUALITY_TARGET_RESULTS = 8
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


HEADING_LINK_RE = re.compile(
    r"(?m)^\s{0,3}#{2,6}\s+\[([^\]\n]{3,300})\]\((https?://[^\s)]+)\)"
)
LINK_RE = re.compile(r"(?<![!\[])\[([^\]\n]{3,300})\]\((https?://[^\s)]+)\)")
RELATIVE_TIME_RE = re.compile(
    r"\b(\d{1,3})\s*(menit|jam|detik|hari)\s*(?:yang\s*)?lalu\b", re.IGNORECASE
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
}


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
        "teknologi edukasi otomotif ekonomi olahraga kesehatan konten berita YouTube Instagram TikTok X"
    )


def category_labels() -> list[str]:
    """Daftar kategori dalam urutan tampilan dashboard."""
    return [CATEGORY_LABELS[key] for key in CATEGORY_ORDER]


def _clean_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


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
    if host.endswith(("t.me", "telegram.me")):
        return len(segments) >= 2 and bool(re.fullmatch(r"\d+", segments[-1]))
    if host.endswith("pinterest.com"):
        return bool(re.match(r"^/pin/\d+", path))
    return False


def _looks_like_direct_article(title: str, url: str) -> bool:
    """Terima artikel penerbit atau konten sosial individual, bukan gambar maupun halaman navigasi."""
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
        return _is_social_content_url(url)

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

    # Postingan sosial individual tetap dipertahankan. Metrik seperti likes dan subscribers
    # hanya dihapus dari ringkasan, bukan dijadikan dasar penolakan konten.
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



def _query_terms(query: str) -> set[str]:
    """Ambil kata bermakna dari kueri untuk menilai relevansi hasil."""
    stopwords = {
        "berita", "terbaru", "hari", "ini", "indonesia", "dan", "atau", "yang",
        "untuk", "dengan", "dari", "pada", "dalam", "the", "a", "an", "of", "to",
        "januari", "februari", "maret", "april", "mei", "juni", "juli", "agustus",
        "september", "oktober", "november", "desember",
    }
    return {
        term for term in re.findall(r"[a-zA-ZÀ-ÿ0-9]{4,}", query.casefold())
        if term not in stopwords and not term.isdigit()
    }


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
        score -= 5
        reasons.append("ringkasan kosong")

    terms = _query_terms(query)
    if terms:
        matched_terms = {term for term in terms if term in combined}
        if matched_terms:
            score += min(14, 4 * len(matched_terms))
            reasons.append("relevan dengan kueri")
        # Kueri default luas sengaja tidak membuat hasil dihukum keras.
        elif len(terms) <= 8:
            score -= 12
            reasons.append("kurang relevan dengan kueri")

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
    filtered = [
        item for item in scored
        if (
            item.get("time_status") == "verified_today"
            and int(item.get("quality_score", 0)) >= MIN_VERIFIED_QUALITY_SCORE
        )
        or (
            item.get("time_status") == "needs_time_verification"
            and int(item.get("quality_score", 0)) >= MIN_UNVERIFIED_QUALITY_SCORE
        )
    ]
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


def fallback_queries(primary_query: str, now: datetime | None = None) -> list[str]:
    """Buat kueri cadangan yang lebih sederhana saat respons awal tidak menghasilkan artikel."""
    now = _as_jakarta(now)
    today = today_indonesia(now)
    candidates = [
        f"{primary_query.strip()} berita terbaru {today}",
        f"Berita nasional Indonesia terbaru hari ini {today}",
        f"Berita ekonomi bisnis Indonesia terbaru hari ini {today}",
        f"Berita teknologi pendidikan kesehatan terbaru Indonesia {today}",
        f"Berita olahraga otomotif hiburan terbaru Indonesia {today}",
        f"Berita dunia internasional terbaru hari ini {today}",
    ]
    unique: list[str] = []
    seen: set[str] = {primary_query.casefold().strip()}
    for candidate in candidates:
        candidate = _clean_text(candidate, 500)
        key = candidate.casefold()
        if candidate and key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def fetch_raw_markdown(
    api_key: str,
    query: str | None = None,
    timeout: int = 45,
    *,
    now: datetime | None = None,
) -> tuple[str, dict[str, str]]:
    """Ambil respons mentah dari Jina Search.

    Dokumentasi Jina menyarankan `s.jina.ai/?q=` untuk SERP dan `Accept: application/json`
    untuk hasil terstruktur berisi URL, judul, konten, dan timestamp bila tersedia.
    Parser tetap mendukung Markdown sebagai fallback bila endpoint mengembalikannya.
    """
    if not api_key:
        raise ValueError("JINA_API_KEY belum diatur.")

    current_now = _as_jakarta(now)
    query = (query or default_query(current_now)).strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "X-Respond-With": "markdown",
        "X-Retain-Images": "none",
        "User-Agent": "news-monitor-streamlit/4.0",
    }
    response = requests.get(
        JINA_SEARCH_URL,
        params={"q": query},
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()

    raw_markdown = response.text.strip()
    if not raw_markdown:
        raise ValueError("Jina tidak mengembalikan isi respons.")

    metadata = {
        "query": query,
        "fetched_at": current_now.isoformat(),
        "today_jakarta": today_indonesia(current_now),
        "content_type": response.headers.get("content-type", "tidak diketahui"),
        "response_format": "json_preferred",
        "quality_threshold_verified": str(MIN_VERIFIED_QUALITY_SCORE),
        "quality_threshold_unverified": str(MIN_UNVERIFIED_QUALITY_SCORE),
    }
    return raw_markdown, metadata


def _fetch_rounds(
    api_key: str,
    query: str | None,
    max_results: int,
    timeout: int,
    *,
    allow_unverified_fallback: bool,
) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """Jalankan pencarian utama lalu beberapa kueri cadangan sampai hasil berkualitas cukup."""
    now = jakarta_now()
    primary_query = (query or default_query(now)).strip()
    queries = [primary_query, *fallback_queries(primary_query, now)]
    raw_sections: list[str] = []
    parsed_rounds: list[tuple[list[dict[str, Any]], dict[str, int], str]] = []
    metadata: dict[str, str] | None = None
    target_results = min(max_results, QUALITY_TARGET_RESULTS)

    for index, search_query in enumerate(queries):
        raw_markdown, round_metadata = fetch_raw_markdown(
            api_key, query=search_query, timeout=timeout, now=now
        )
        metadata = metadata or dict(round_metadata)
        raw_sections.append(f"# Respons pencarian {index + 1}\n\n{raw_markdown}")
        verified, stats = parse_search_response_details(
            raw_markdown, round_metadata["fetched_at"], max_results
        )
        parsed_rounds.append((verified, stats, search_query))

        verified_items: list[dict[str, Any]] = []
        for items, _, item_query in parsed_rounds:
            verified_items.extend(_apply_quality_scores(items, item_query))
        if len(_rank_and_filter(verified_items, primary_query, max_results)) >= target_results:
            break

    assert metadata is not None
    verified_items = []
    for items, _, item_query in parsed_rounds:
        verified_items.extend(_apply_quality_scores(items, item_query))
    articles = _rank_and_filter(verified_items, primary_query, max_results)

    # Tampilan Streamlit tidak dibiarkan kosong apabila respons berisi tautan artikel
    # langsung tanpa marker waktu. Status dan kartu memperjelas bahwa waktu belum diverifikasi.
    used_unverified = False
    if not articles and allow_unverified_fallback:
        unverified_items: list[dict[str, Any]] = []
        for raw_section, (_, _, item_query) in zip(raw_sections, parsed_rounds):
            # Hilangkan heading audit buatan sebelum mem-parsing ulang.
            raw = raw_section.split("\n\n", 1)[1] if "\n\n" in raw_section else raw_section
            items, _ = parse_search_response_details(
                raw,
                metadata["fetched_at"],
                max_results,
                allow_unverified_fallback=True,
            )
            unverified_items.extend(_apply_quality_scores(items, item_query))
        articles = _rank_and_filter(unverified_items, primary_query, max_results)
        used_unverified = bool(articles)

    raw_candidates = sum(stats["raw_candidates"] for _, stats, _ in parsed_rounds)
    verified_count = sum(item.get("time_status") == "verified_today" for item in articles)
    unverified_count = sum(item.get("time_status") == "needs_time_verification" for item in articles)
    metadata.update(
        {
            "result_count": str(len(articles)),
            "raw_candidates": str(raw_candidates),
            "today_articles": str(verified_count),
            "unverified_articles": str(unverified_count),
            "search_rounds": str(len(parsed_rounds)),
            "fallback_search_used": "true" if len(parsed_rounds) > 1 else "false",
            "result_mode": "verified_today" if verified_count else (
                "needs_time_verification" if used_unverified else "none"
            ),
        }
    )
    return articles, metadata, "\n\n---\n\n".join(raw_sections)


def fetch_news(
    api_key: str,
    query: str | None = None,
    max_results: int = 20,
    timeout: int = 45,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Ambil berita terverifikasi, atau kandidat artikel langsung bila marker waktu tidak tersedia.

    Worker menyimpan kandidat fallback agar dashboard tidak kosong, tetapi worker harus
    memfilter `time_status` sebelum mengirim notifikasi Telegram.
    """
    articles, metadata, _ = _fetch_rounds(
        api_key,
        query,
        max_results,
        timeout,
        allow_unverified_fallback=True,
    )
    return articles, metadata


def fetch_news_with_raw(
    api_key: str,
    query: str | None = None,
    max_results: int = 20,
    timeout: int = 45,
) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """Varian Streamlit dengan pencarian cadangan dan respons Markdown untuk audit."""
    return _fetch_rounds(
        api_key,
        query,
        max_results,
        timeout,
        allow_unverified_fallback=True,
    )
