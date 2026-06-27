"""Ambil, saring, kategorikan, dan normalisasi berita dari Jina Search.

Modul ini sengaja hanya menghasilkan tautan artikel langsung. Tautan gambar,
iklan, menu, halaman kategori, dan perantara seperti Google News dikeluarkan.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import urlparse
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
# Platform sosial, profil, dan perantara tidak dianggap sebagai artikel berita.
BLOCKED_HOSTS = {
    "google.com", "news.google.com", "googleusercontent.com", "jina.ai", "s.jina.ai",
    "t.me", "telegram.me", "instagram.com", "youtube.com", "youtu.be", "facebook.com",
    "fb.com", "tiktok.com", "x.com", "twitter.com", "threads.net", "linkedin.com",
    "pinterest.com", "reddit.com", "whatsapp.com",
}
BLOCKED_URL_PARTS = {
    "search", "searchall", "tag", "tags", "topic", "topics", "kategori", "category",
    "categories", "indeks", "index", "login", "signin", "privacy", "kebijakan", "kontak",
    "contact", "about", "redaksi", "rss", "sitemap", "advert", "iklan", "subscribe",
    "channel", "channels", "user", "users", "profile", "profiles", "account", "accounts",
    "reel", "reels", "shorts", "watch", "podcast", "program", "live", "playlist",
}
BLOCKED_TITLE_PARTS = {
    "menu", "beranda", "home", "terpopuler", "lihat selengkapnya", "selengkapnya",
    "baca juga", "lainnya", "loading", "indeks berita", "rekomendasi untuk anda",
    "kebijakan privasi", "kontak kami", "masuk", "login", "download sekarang",
    "kelana kota", "podcast", "siaran langsung", "live streaming", "profil", "profile",
}
SOCIAL_METADATA_RE = re.compile(
    r"\b(?:\d+[\d.,]*[kmb]?\s*)?(?:followers?|pengikut|subscribers?|following)\b",
    re.IGNORECASE,
)
NON_ARTICLE_CONTEXT_RE = re.compile(
    r"\b(?:akun resmi|official account|subscribe|ikuti kami|follow us|kanal youtube|channel youtube)\b",
    re.IGNORECASE,
)
MIN_HEADLINE_LENGTH = 8

HEADING_LINK_RE = re.compile(
    r"(?m)^\s{0,3}#{2,6}\s+\[([^\]\n]{3,300})\]\((https?://[^\s)]+)\)"
)
LINK_RE = re.compile(r"(?<![!\[])\[([^\]\n]{3,300})\]\((https?://[^\s)]+)\)")
RELATIVE_TIME_RE = re.compile(
    r"\b(\d{1,3})\s*(menit|jam|detik)\s*(?:yang\s*)?lalu\b", re.IGNORECASE
)
DAY_MONTH_RE = re.compile(
    r"\b(?:senin|selasa|rabu|kamis|jumat|jum'at|sabtu|minggu)?\s*,?\s*"
    r"(\d{1,2})\s+(jan(?:uari)?|feb(?:ruari)?|mar(?:et)?|apr(?:il)?|mei|"
    r"jun(?:i)?|jul(?:i)?|agu(?:stus)?|sep(?:tember)?|okt(?:ober)?|"
    r"nov(?:ember)?|des(?:ember)?)(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
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
        "teknologi edukasi otomotif ekonomi olahraga kesehatan"
    )


def category_labels() -> list[str]:
    """Daftar kategori dalam urutan tampilan dashboard."""
    return [CATEGORY_LABELS[key] for key in CATEGORY_ORDER]


def _clean_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _valid_url(value: Any) -> str:
    value = str(value or "").strip().rstrip(".,;:!?")
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _article_id(url: str, title: str) -> str:
    return sha256(f"{url}|{title.lower()}".encode("utf-8")).hexdigest()[:20]


def _normalised_title(value: str) -> str:
    return re.sub(r"\W+", "", value.lower())


def _is_blocked_host(host: str) -> bool:
    return any(host == blocked or host.endswith(f".{blocked}") for blocked in BLOCKED_HOSTS)


def _looks_like_direct_article(title: str, url: str) -> bool:
    """Terima hanya URL artikel penerbit, bukan sosial, profil, kanal, atau navigasi."""
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
    """Tolak kandidat yang membawa metadata akun, pengikut, atau pelanggan."""
    context = " ".join(_clean_text(value, 1200) for value in values if value)
    return bool(SOCIAL_METADATA_RE.search(context) or NON_ARTICLE_CONTEXT_RE.search(context))


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
        else:
            published = now - timedelta(seconds=amount)
        return published.date() == now.date(), match.group(0)

    if re.search(r"\bhari\s+ini\b|\btoday\b", lower):
        return True, "Hari ini"
    return False, ""


def _extract_summary(context: str) -> str:
    """Ambil teks kecil di sekitar artikel, tanpa gambar atau deretan tautan navigasi."""
    useful: list[str] = []
    for line in context.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if RELATIVE_TIME_RE.search(line) or DAY_MONTH_RE.search(line) or NUMERIC_DATE_RE.search(line):
            continue
        # Hapus tautan Markdown agar menu dan URL panjang tidak menjadi ringkasan.
        line = re.sub(r"!?\[[^\]]+\]\([^)]*\)", "", line).strip(" -|:·")
        if len(line) < 35 or line.lower() in BLOCKED_TITLE_PARTS:
            continue
        useful.append(line)
        if len(" ".join(useful)) >= 400:
            break
    return _clean_text(" ".join(useful), 450)


def _normalise_item(
    raw: dict[str, Any],
    detected_at: str,
    now: datetime,
    *,
    publication_context: str = "",
) -> dict[str, Any] | None:
    title = _clean_text(raw.get("title") or raw.get("name") or raw.get("headline"), 300)
    url = _valid_url(raw.get("url") or raw.get("link") or raw.get("href"))
    if not _looks_like_direct_article(title, url):
        return None

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
        or raw.get("date")
        or raw.get("published")
        or raw.get("time"),
        150,
    )
    is_today, published_at = _is_today_from_text(
        f"{explicit_published}\n{publication_context}", now
    )
    if not is_today:
        return None
    if _looks_like_social_or_profile_context(title, description, publication_context, url):
        return None

    category_key, category = classify_category(title, description, url)
    return {
        "id": _article_id(url, title),
        "title": title,
        "url": url,
        "source": _host(url),
        "summary": description,
        "published_at": published_at or "Hari ini",
        "detected_at": detected_at,
        "category_key": category_key,
        "category": category,
    }


def _walk_json(value: Any, detected_at: str, now: datetime) -> list[dict[str, Any]]:
    """Dukung respons JSON tanpa mengunci ke satu skema Jina."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        item = _normalise_item(value, detected_at, now)
        if item:
            found.append(item)
        for child in value.values():
            found.extend(_walk_json(child, detected_at, now))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_json(child, detected_at, now))
    return found


def _parse_markdown(text: str, detected_at: str, now: datetime) -> tuple[list[dict[str, Any]], int]:
    """Ekstrak hanya heading artikel dan fallback link yang punya marker waktu hari ini."""
    items: list[dict[str, Any]] = []
    candidates = 0
    occupied_spans: list[tuple[int, int]] = []
    heading_matches = list(HEADING_LINK_RE.finditer(text))

    for index, match in enumerate(heading_matches):
        candidates += 1
        title, url = match.groups()
        next_start = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(text)
        context = text[match.end() : min(next_start, match.end() + 900)]
        item = _normalise_item(
            {"title": title, "url": url, "description": _extract_summary(context)},
            detected_at,
            now,
            publication_context=context,
        )
        if item:
            items.append(item)
        occupied_spans.append(match.span())

    # Sebagian mesin pencari menuliskan tautan artikel tanpa heading. Tautan itu hanya
    # diterima bila marker waktu hari ini berada dekat tautan tersebut.
    for match in LINK_RE.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in occupied_spans):
            continue
        candidates += 1
        title, url = match.groups()
        context = text[match.end() : match.end() + 500]
        item = _normalise_item(
            {"title": title, "url": url, "description": _extract_summary(context)},
            detected_at,
            now,
            publication_context=context,
        )
        if item:
            items.append(item)
    return items, candidates


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
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Ubah respons Jina menjadi artikel langsung yang dipublikasikan hari ini saja."""
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

    articles = _deduplicate(items, limit)
    return articles, {
        "raw_candidates": raw_candidates,
        "today_articles": len(articles),
    }


def parse_search_response(
    payload: str | dict[str, Any] | list[Any], detected_at: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Kompatibilitas publik untuk parser artikel hari ini."""
    articles, _ = parse_search_response_details(payload, detected_at, limit)
    return articles


def fetch_raw_markdown(
    api_key: str,
    query: str | None = None,
    timeout: int = 45,
) -> tuple[str, dict[str, str]]:
    """Ambil respons Markdown mentah dari Jina Search dengan mesin direct."""
    if not api_key:
        raise ValueError("JINA_API_KEY belum diatur.")

    now = jakarta_now()
    query = (query or default_query(now)).strip()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Engine": "direct",
        "Accept": "text/markdown, text/plain;q=0.9, application/json;q=0.8",
        "User-Agent": "news-monitor-streamlit/2.1",
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
        "fetched_at": now.isoformat(),
        "today_jakarta": today_indonesia(now),
        "content_type": response.headers.get("content-type", "tidak diketahui"),
    }
    return raw_markdown, metadata


def fetch_news(
    api_key: str,
    query: str | None = None,
    max_results: int = 20,
    timeout: int = 45,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Ambil artikel langsung yang memiliki marker publikasi hari ini."""
    raw_markdown, metadata = fetch_raw_markdown(api_key, query=query, timeout=timeout)
    articles, stats = parse_search_response_details(raw_markdown, metadata["fetched_at"], max_results)
    metadata["result_count"] = str(len(articles))
    metadata["raw_candidates"] = str(stats["raw_candidates"])
    metadata["today_articles"] = str(stats["today_articles"])
    return articles, metadata


def fetch_news_with_raw(
    api_key: str,
    query: str | None = None,
    max_results: int = 20,
    timeout: int = 45,
) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """Varian Streamlit: artikel terfilter beserta respons Markdown mentah untuk audit."""
    raw_markdown, metadata = fetch_raw_markdown(api_key, query=query, timeout=timeout)
    articles, stats = parse_search_response_details(raw_markdown, metadata["fetched_at"], max_results)
    metadata["result_count"] = str(len(articles))
    metadata["raw_candidates"] = str(stats["raw_candidates"])
    metadata["today_articles"] = str(stats["today_articles"])
    return articles, metadata, raw_markdown
