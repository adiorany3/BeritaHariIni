# Monitor Berita Hari Ini dengan Streamlit

Aplikasi ini mencari berita terbaru dengan pendekatan **RSS-first, Jina Search fallback, lalu scrape informasi artikel**. RSS penerbit resmi dicek lebih dulu karena biasanya lebih cepat, lebih bersih, dan langsung berisi URL artikel. Jika hasil RSS belum cukup, aplikasi baru memakai Jina Search (`s.jina.ai/?q=`) dengan kueri yang dibatasi ke domain media berita tepercaya dan diberi negative filter untuk sosial/video. Setelah artikel akhir dipilih, aplikasi memakai Jina Reader (`r.jina.ai/<url>`) untuk mengambil informasi utama dari isi artikel. Link asli tetap ditampilkan agar pengguna bisa membaca berita lengkap di sumbernya bila diperlukan.

Tujuan versi ini: menghasilkan berita yang **bermutu, relevan, informatif, dan bukan sekadar kumpulan link acak**.

Versi ini tidak lagi menampilkan hasil tersimpan dari workflow dan worker tidak mengirim pesan otomatis.

## Fitur utama

- **RSS penerbit resmi diprioritaskan** sebelum SERP umum, tetapi sekarang tetap mengikuti keyword search. Untuk keyword spesifik, RSS umum yang tidak cocok akan dibuang dan aplikasi lanjut ke Jina fallback.
- **Informasi utama artikel di-scrape otomatis** memakai Jina Reader setelah URL final lolos filter. Dashboard menampilkan inti isi artikel langsung di kartu berita, sekaligus tetap menyediakan tombol **Buka berita asli**.
- Query default tidak lagi menyebut platform sosial/video. Jina fallback memakai query `site:` ke domain berita, misalnya Kompas, Detik, CNN Indonesia, CNBC Indonesia, Tempo, Antara, Liputan6, Bisnis, Katadata, Kontan, Republika, Kumparan, Tirto, Suara, dan Okezone.
- Respons Jina tetap memakai mode cepat:
  - `Accept: application/json`
  - `X-Respond-With: no-content`
  - `X-Retain-Images: none`
  - `X-Md-Link-Style: discarded`
  - `X-Timeout`
- Parser mendukung JSON dan Markdown dari Jina, plus RSS/Atom XML dari publisher.
- Hanya artikel dengan marker waktu **hari ini** pada zona waktu Asia/Jakarta yang diprioritaskan.
- Marker waktu yang didukung:
  - `15 menit yang lalu`, `2 jam yang lalu`, `1 hari yang lalu`
  - `2 hours ago`, `4 days ago`
  - `27 Juni 2026`, `Jun 27, 2026`, `Sat, 27 Jun 2026 10:00:00 +0700`
  - timestamp ISO seperti `2026-06-27T12:00:00+07:00`
- Artikel bertanggal lama, `kemarin`, `yesterday`, `1 hari yang lalu`, atau `4 days ago` tidak dipromosikan sebagai berita hari ini.
- Skor kualitas menilai:
  - waktu publikasi hari ini,
  - domain editorial,
  - URL yang terlihat seperti artikel,
  - judul yang informatif,
  - ringkasan,
  - kategori,
  - relevansi terhadap kata kunci,
  - sinyal non-berita/clickbait.
- Untuk query spesifik di kolom search, relevansi sekarang menjadi **filter wajib**, bukan sekadar bonus skor. Kueri multi-kata seperti `harga telur` diperlakukan sebagai **frasa/intent utuh**, bukan pencarian longgar `harga` OR `telur`. Ini mencegah hasil RSS umum atau hasil yang hanya cocok sebagian tampil statis ketika pengguna mencari topik tertentu.
- Sosial/video **diblokir secara default**. Jika benar-benar ingin menerima konten sosial individual, aktifkan `NEWS_ALLOW_SOCIAL=1`, tetapi ini tidak disarankan untuk mode berita bermutu.
- Panel audit menampilkan sumber mentah RSS/Jina sebagai kode agar gambar, HTML, dan iklan tidak dimuat.
- Link asli tetap ditampilkan pada kartu sebagai tombol **Buka berita asli**, sehingga ringkasan berfungsi sebagai preview dan pengguna tetap bisa membuka sumber lengkap.

## Struktur proyek

```text
.
├── data/
├── tests/
├── app.py
├── news_service.py
├── storage.py
├── worker.py
└── requirements.txt
```

## Jalankan di komputer

```bash
git clone <URL_REPOSITORI_ANDA>
cd news_monitor_streamlit
python -m venv .venv
pip install -r requirements.txt
```

Ekspor environment variable:

```bash
export JINA_API_KEY="jina_kunci_anda"
# Default yang disarankan
export NEWS_ENABLE_RSS="1"
export NEWS_MAX_RSS_FEEDS="8"
export NEWS_RSS_TIMEOUT="4"
export NEWS_MAX_SEARCH_ROUNDS="2"
export NEWS_REQUEST_TIMEOUT="25"
export JINA_PAGE_TIMEOUT="12"
export JINA_RESPOND_WITH="no-content"
export NEWS_ENABLE_ARTICLE_SCRAPE="1"
export NEWS_MAX_ARTICLE_SCRAPES="5"
export NEWS_ARTICLE_SCRAPE_TIMEOUT="12"
export NEWS_ALLOW_SOCIAL="0"

python worker.py
```

Untuk dashboard lokal:

```bash
streamlit run app.py
```

## Deploy di Streamlit Community Cloud

1. Buat repository baru, lalu unggah isi proyek ini.
2. Di Streamlit Community Cloud, buat aplikasi dari repo ini dengan file utama `app.py`.
3. Pada **Settings > Secrets** Streamlit, masukkan minimal:

```toml
JINA_API_KEY = "jina_kunci_anda"
NEWS_ENABLE_RSS = "1"
NEWS_ENABLE_ARTICLE_SCRAPE = "1"
NEWS_ALLOW_SOCIAL = "0"
```

## Konfigurasi performa

| Variable | Default | Fungsi |
| --- | ---: | --- |
| `NEWS_ENABLE_RSS` | `1` | Cek RSS publisher resmi sebelum Jina. Matikan hanya untuk debug. |
| `NEWS_MAX_RSS_FEEDS` | `8` | Jumlah feed RSS yang dicek per siklus. |
| `NEWS_RSS_TIMEOUT` | `4` | Timeout per feed RSS. Dibuat pendek agar tidak menunggu sumber lambat. |
| `NEWS_MAX_SEARCH_ROUNDS` | `2` | Batas query Jina fallback per siklus. Isi `0` untuk mematikan Jina fallback saat debug. |
| `NEWS_REQUEST_TIMEOUT` | `25` | Timeout HTTP client untuk Jina. |
| `JINA_PAGE_TIMEOUT` | `12` | Header `X-Timeout` untuk Jina. |
| `JINA_RESPOND_WITH` | `no-content` | Mode cepat. Gunakan `markdown` hanya untuk audit lebih lengkap. |
| `NEWS_ENABLE_ARTICLE_SCRAPE` | `1` | Ambil informasi utama dari isi artikel final memakai Jina Reader. |
| `NEWS_MAX_ARTICLE_SCRAPES` | `5` | Jumlah artikel akhir yang di-scrape informasinya per pencarian. |
| `NEWS_ARTICLE_SCRAPE_TIMEOUT` | `12` | Timeout per artikel untuk Jina Reader. |
| `NEWS_ALLOW_SOCIAL` | `0` | Jika `1`, postingan sosial individual boleh lolos. Default `0` agar hasil tetap editorial. |

## Rekomendasi tuning

Mode paling cepat dan bersih:

```bash
export NEWS_ENABLE_RSS="1"
export NEWS_MAX_RSS_FEEDS="8"
export NEWS_RSS_TIMEOUT="4"
export NEWS_MAX_SEARCH_ROUNDS="1"
export JINA_RESPOND_WITH="no-content"
export NEWS_ENABLE_ARTICLE_SCRAPE="1"
export NEWS_MAX_ARTICLE_SCRAPES="5"
export NEWS_ALLOW_SOCIAL="0"
```

Mode recall lebih besar, tetapi lebih lambat:

```bash
export NEWS_ENABLE_RSS="1"
export NEWS_MAX_RSS_FEEDS="10"
export NEWS_MAX_SEARCH_ROUNDS="3"
export JINA_RESPOND_WITH="no-content"
export NEWS_MAX_ARTICLE_SCRAPES="5"
```

Mode audit isi lebih lengkap, tetapi paling lambat:

```bash
export JINA_RESPOND_WITH="markdown"
export NEWS_MAX_SEARCH_ROUNDS="2"
export NEWS_MAX_ARTICLE_SCRAPES="8"
```

## Pengujian

```bash
python -m unittest discover -s tests -v
```

## Catatan operasional

- RSS resmi bisa kosong, lambat, atau terlalu umum pada sebagian sumber; karena itu timeout dibuat pendek dan Jina dipakai sebagai fallback ketika RSS belum relevan dengan keyword search.
- Jina Search bukan mesin berita khusus. Tanpa `site:` dan negative filter, SERP dapat mengembalikan video, sosial, atau agregator. Versi ini sengaja mengunci fallback ke domain penerbit.
- Scrape isi artikel dilakukan hanya pada artikel yang sudah lolos filter dan jumlahnya dibatasi. Jika proses terasa lambat, turunkan `NEWS_MAX_ARTICLE_SCRAPES` atau matikan sementara dengan `NEWS_ENABLE_ARTICLE_SCRAPE=0`.
- Tanggal relatif dihitung terhadap waktu Jakarta. Contoh: pukul `00:30`, artikel `2 jam yang lalu` dianggap berasal dari hari sebelumnya dan dikeluarkan.
- Putar ulang token yang pernah dibagikan di chat, commit, screenshot, atau file publik.
