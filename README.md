# Monitor Berita Hari Ini dengan Streamlit

Aplikasi ini mencari berita terbaru dengan pendekatan **RSS-first, Jina Search fallback, lalu scrape konten artikel**. RSS penerbit resmi dicek lebih dulu karena biasanya lebih cepat, lebih bersih, dan langsung berisi URL artikel. Jika hasil RSS belum cukup, aplikasi baru memakai Jina Search (`s.jina.ai/?q=`) dengan kueri sederhana per-domain media berita tepercaya. Sosial/video tetap diblokir di parser agar query tidak terlalu kompleks dan tidak memicu error 422 dari Jina. Setelah artikel akhir dipilih, aplikasi memakai Jina Reader (`r.jina.ai/<url>`) untuk mengambil konten utama dari isi artikel. Setiap kartu/pesan juga menyediakan link **Buka teks bersih (TXT)**. Jika `STREAMLIT_APP_URL` diisi, link ini membuka halaman pembaca internal Streamlit (`?reader=<url>`) yang mengambil Jina Reader dengan header pembersih dan membuang baris seperti `![Image ...]`, navigasi, iklan, serta elemen non-konten. Link **Buka berita asli** tetap ditampilkan agar pengguna bisa membaca sumber lengkap. Selain dashboard Streamlit, versi ini juga menyediakan **Telegram Bot interaktif** dan **worker broadcast pagi**: user bisa mengirim tema, atau GitHub Actions bisa mengirim digest berita terbaru setiap pagi ke chat Telegram.

Tujuan versi ini: menghasilkan berita yang **bermutu, relevan, informatif, dan bukan sekadar kumpulan link acak**.

Versi ini tidak lagi menampilkan hasil tersimpan dari workflow. Telegram mendukung dua mode: **interaktif** lewat `telegram_bot.py` saat user mengirim tema/keyword, dan **broadcast pagi terjadwal** lewat `worker.py` + GitHub Actions.

## Fitur utama

- **RSS penerbit resmi diprioritaskan** sebelum SERP umum, tetapi sekarang tetap mengikuti keyword search. Untuk keyword spesifik, RSS umum yang tidak cocok akan dibuang dan aplikasi lanjut ke Jina fallback.
- **Konten artikel di-scrape otomatis** memakai Jina Reader setelah URL final lolos filter. Dashboard menampilkan konten hasil scrape langsung di kartu berita, menyediakan tombol **Buka teks bersih (TXT)** yang menghapus `![Image ...]`, dan tetap menyediakan tombol **Buka berita asli**.
- Query default tidak lagi menyebut platform sosial/video. Jina fallback memakai query `site:` **satu domain per request** ke media berita seperti Kompas, Detik, CNN Indonesia, CNBC Indonesia, Tempo, Antara, Liputan6, Bisnis, Katadata, Kontan, Republika, Kumparan, Tirto, Suara, dan Okezone. Query sengaja tidak memakai `OR`, tanda kurung, quote frasa, atau rangkaian `-site:` panjang agar tidak ditolak `s.jina.ai` dengan 422.
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
- Link asli tetap ditampilkan pada kartu sebagai tombol **Buka berita asli**, sedangkan tombol **Buka teks bersih (TXT)** membuka halaman TXT internal aplikasi bila `STREAMLIT_APP_URL` tersedia. Halaman ini membersihkan output Jina Reader dari `![Image ...]`, daftar link, navigasi, iklan, dan boilerplate agar mudah dibaca. Konten hasil scrape berfungsi sebagai preview sehingga pengguna tidak perlu membuka semua berita hanya untuk mengetahui isinya.
- **Telegram Bot interaktif** tersedia lewat `telegram_bot.py`: kirim tema seperti `harga telur`, lalu bot membalas daftar judul, konten hasil scrape, link teks bersih TXT, dan link berita asli.
- **Broadcast pagi Telegram** tersedia lewat `worker.py` dan workflow `.github/workflows/morning-news.yml`: GitHub Actions menjalankan worker setiap pagi dan mengirim digest ke chat Telegram yang Anda tentukan.

## Struktur proyek

```text
.
├── data/
├── tests/
├── .github/workflows/morning-news.yml
├── .streamlit/secrets.toml.example
├── app.py
├── config.py
├── news_service.py
├── storage.py
├── telegram_bot.py
├── telegram_chat_id.py
├── telegram_runtime.py
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


## Jalankan Telegram Bot

1. Buat bot lewat **@BotFather** di Telegram, lalu salin token bot.
2. Simpan token di environment variable atau di `.streamlit/secrets.toml` lokal yang tidak di-commit.
3. Jalankan worker bot:

```bash
python telegram_bot.py
```

Contoh environment variable bila tidak memakai `secrets.toml` lokal:

```bash
export TELEGRAM_BOT_TOKEN="token_bot_dari_botfather"
export JINA_API_KEY="jina_kunci_anda"
export NEWS_ENABLE_RSS="1"
export NEWS_ENABLE_ARTICLE_SCRAPE="1"
export NEWS_ALLOW_SOCIAL="0"
export TELEGRAM_NEWS_LIMIT="5"

python telegram_bot.py
```

Setelah bot aktif, kirim pesan seperti:

```text
harga telur
```

atau:

```text
/berita mobil listrik
```

Bot akan membalas:

```text
Judul berita
Konten hasil scrape
Link teks bersih TXT
Link berita asli
```

### Batasi akses bot ke chat tertentu

Opsional, setelah mengetahui `chat_id`, kunci bot agar hanya chat tertentu yang bisa memakai:

```bash
export TELEGRAM_ALLOWED_CHAT_IDS="123456789,987654321"
```

Jika `TELEGRAM_ALLOWED_CHAT_IDS` kosong, semua chat yang menemukan bot dapat mengirim tema.

### Konfigurasi Telegram

| Variable | Default | Fungsi |
| --- | ---: | --- |
| `TELEGRAM_BOT_TOKEN` | wajib | Token bot dari BotFather. |
| `TELEGRAM_ALLOWED_CHAT_IDS` | kosong | Daftar chat ID yang diizinkan, pisahkan dengan koma/spasi. Kosong berarti terbuka. |
| `TELEGRAM_NEWS_LIMIT` | `5` | Jumlah artikel maksimal yang dikirim per tema. Maksimal 10. |
| `TELEGRAM_NEWS_TIMEOUT` | `25` | Timeout pencarian berita untuk request dari Telegram. |
| `TELEGRAM_MAX_SEARCH_ROUNDS` | ikut `NEWS_MAX_SEARCH_ROUNDS` | Override jumlah fallback Jina khusus Telegram. |
| `TELEGRAM_POLL_TIMEOUT` | `30` | Timeout long polling Telegram. |
| `TELEGRAM_AUTO_START` | `0` | Jika `1`, bot polling otomatis start saat `app.py` aktif di Streamlit. |
| `TELEGRAM_DELETE_WEBHOOK_ON_START` | `1` | Matikan webhook saat polling start. Penting karena Telegram tidak mengirim update ke polling bila webhook masih aktif. |
| `TELEGRAM_DROP_PENDING_UPDATES` | `0` | Jika `1`, update lama di antrean Telegram dibuang saat deleteWebhook. |
| `TELEGRAM_DEDUPE_UPDATES` | `1` | Cegah update/message Telegram yang sama diproses ulang saat polling restart/rerun. |

### Broadcast pagi via GitHub Actions

Workflow `.github/workflows/morning-news.yml` menjalankan `python worker.py` setiap hari pukul **07:15 Asia/Jakarta**. Worker akan:

1. mengambil berita terbaru hari ini,
2. membuat konten hasil scrape,
3. mengirim judul + konten hasil scrape + link teks bersih TXT + link asli ke Telegram.

Secret GitHub yang wajib dibuat:

| Secret | Isi |
| --- | --- |
| `JINA_API_KEY` | API key Jina Reader/Search. |
| `STREAMLIT_APP_URL` | URL publik app Streamlit, contoh `https://nama-app.streamlit.app`. Dipakai supaya link Telegram membuka halaman TXT internal yang menghapus `![Image ...]`. |
| `TELEGRAM_BOT_TOKEN` | Token bot dari @BotFather. |
| `TELEGRAM_BROADCAST_CHAT_IDS` | Satu atau beberapa chat ID tujuan, contoh `123456789` atau `123456789,-100987654321`. |


Cara mendapatkan chat ID:

1. Kirim `/start` atau pesan apa pun ke bot dari akun/grup tujuan.
2. Jalankan lokal:

```bash
export TELEGRAM_BOT_TOKEN="token_bot_dari_botfather"
python telegram_chat_id.py
```

3. Salin nilai `chat_id=...` ke GitHub Secret `TELEGRAM_BROADCAST_CHAT_IDS`.

Repository Variables opsional:

| Variable | Contoh | Fungsi |
| --- | --- | --- |
| `NEWS_QUERY` | kosong / `ekonomi indonesia` | Tema harian. Kosong berarti berita terbaru umum. |
| `WORKER_TELEGRAM_TITLE` | `Berita terbaru pagi ini` | Judul header pesan Telegram. |
| `TELEGRAM_NEWS_LIMIT` | `5` | Jumlah artikel dalam pesan pagi. |
| `NEWS_MAX_SEARCH_ROUNDS` | `2` | Batas fallback Jina. |
| `MAX_RESULTS` | `10` | Jumlah kandidat artikel yang diproses worker. |
| `WORKER_DEDUPE_TELEGRAM` | `1` | Cegah digest pagi yang sama terkirim berkali-kali di hari yang sama. |
| `WORKER_FORCE_SEND` | `0` | Set `1` hanya kalau ingin mengirim ulang manual dari tab Actions. |

Untuk mengubah jam, edit bagian workflow. GitHub Actions memakai cron UTC, jadi contoh default 07:15 WIB ditulis sebagai 00:15 UTC:

```yaml
schedule:
  - cron: "15 0 * * *"
```

Cara tes langsung tanpa menunggu besok: buka tab **Actions** → pilih **Morning News Telegram** → klik **Run workflow**.

Konfigurasi worker terkait Telegram:

| Variable | Default | Fungsi |
| --- | ---: | --- |
| `TELEGRAM_BROADCAST_CHAT_IDS` | kosong | Chat ID tujuan broadcast pagi. Fallback ke `TELEGRAM_ALLOWED_CHAT_IDS` jika kosong. |
| `WORKER_SEND_TELEGRAM` | otomatis | `1` untuk paksa kirim Telegram; `0` untuk hanya menyimpan JSON. |
| `WORKER_REQUIRE_TELEGRAM` | `0` | Jika `1`, workflow gagal bila token/chat ID belum diatur. Workflow GitHub default memakai `1`. |
| `WORKER_TELEGRAM_TITLE` | query / `Berita terbaru pagi ini` | Header pesan digest Telegram. |
| `WORKER_DEDUPE_TELEGRAM` | `1` | Kunci pengiriman per tanggal + chat ID + judul agar tidak spam. |
| `WORKER_FORCE_SEND` | `0` | Bypass dedupe untuk kirim ulang manual. Jangan aktifkan permanen. |
| `WORKER_DEDUPE_TIMEZONE` | `Asia/Jakarta` | Zona waktu tanggal dedupe. |

Workflow juga memakai `concurrency` sehingga dua run `Morning News Telegram` tidak berjalan bersamaan. State dedupe disimpan di `data/telegram_digest_state.json` dan workflow akan commit file ini setelah pengiriman. Jika file state gagal tersimpan, run berikutnya tidak tahu bahwa digest sudah pernah dikirim dan berisiko mengirim ulang.


## Deploy di Streamlit Community Cloud

1. Buat repository baru, lalu unggah isi proyek ini.
2. Di Streamlit Community Cloud, buat aplikasi dari repo ini dengan file utama `app.py`.
3. Buka **App > Settings > Secrets**, lalu tempel konfigurasi TOML. Jangan menaruh token/API key di kode, README publik, atau GitHub Actions log.
4. File `.streamlit/secrets.toml.example` hanya template. File asli `.streamlit/secrets.toml` sudah masuk `.gitignore` dan tidak boleh di-commit.

Contoh aman untuk **Streamlit Secrets**:

```toml
JINA_API_KEY = "jina_kunci_anda"

[news]
enable_rss = "1"
max_rss_feeds = "8"
rss_timeout = "4"
max_search_rounds = "2"
request_timeout = "25"
allow_social = "0"
enable_article_scrape = "1"
max_article_scrapes = "5"
article_scrape_timeout = "12"

[jina]
respond_with = "no-content"
page_timeout = "12"

[telegram]
bot_token = "token_bot_dari_botfather"
allowed_chat_ids = [123456789]
# Dipakai untuk broadcast pagi via worker/GitHub Actions.
broadcast_chat_ids = [123456789]
news_limit = 5
news_timeout = 25
max_search_rounds = 2
poll_timeout = 30
# Agar bot ikut hidup dari app.py di Streamlit Cloud.
auto_start = true
# Wajib untuk long polling jika token pernah dipasang webhook.
delete_webhook_on_start = true
drop_pending_updates = false
dedupe_updates = true

[worker]
send_telegram = true
require_telegram = true
telegram_title = "Berita terbaru pagi ini"
dedupe_telegram = true
dedupe_timezone = "Asia/Jakarta"
force_send = false
```

Aplikasi juga masih mendukung format root-level lama seperti `NEWS_ENABLE_RSS = "1"` atau `TELEGRAM_BOT_TOKEN = "..."`. Namun format sectioned `[news]`, `[jina]`, dan `[telegram]` lebih rapi untuk Streamlit Cloud.

### Telegram di Streamlit Cloud

Streamlit Community Cloud menjalankan `app.py`. Karena itu versi ini menambahkan `telegram_runtime.py` agar bot Telegram bisa dinyalakan dari dashboard Streamlit melalui background polling thread.

Langkah pakai di Streamlit Cloud:

1. Isi secret `[telegram].bot_token` dan `JINA_API_KEY`.
2. Set `auto_start = true` bila ingin bot start otomatis saat aplikasi aktif.
3. Deploy/reboot app, lalu buka sidebar **Telegram Bot**.
4. Klik **Tes token & webhook** untuk memastikan token valid dan webhook kosong.
5. Bila `auto_start` belum aktif, klik **Mulai bot**.

Jika token pernah dipakai webhook di platform lain, polling bisa diam. Set berikut agar app otomatis memanggil `deleteWebhook` saat start:

```toml
[telegram]
delete_webhook_on_start = true
drop_pending_updates = false
```

Catatan: background thread di Streamlit Cloud aktif selama server/app Streamlit hidup. Untuk bot yang harus respons 24/7 tanpa bergantung app tidur/rerun, jalankan worker terpisah di VPS/Render/Railway dengan:

```bash
python telegram_bot.py
```

Worker eksternal tetap bisa memakai environment variable atau file lokal `.streamlit/secrets.toml` dengan isi yang sama seperti panel Streamlit Secrets.

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
| `NEWS_TEXT_ONLY_MAX_CHARS` | `4000` | Batas karakter halaman TXT internal. |
| `NEWS_ALLOW_SOCIAL` | `0` | Jika `1`, postingan sosial individual boleh lolos. Default `0` agar hasil tetap editorial. |
| `TELEGRAM_BOT_TOKEN` | kosong | Token bot Telegram untuk mode interaktif. Wajib bila menjalankan `telegram_bot.py`. |
| `TELEGRAM_NEWS_LIMIT` | `5` | Batas artikel yang dikirim bot Telegram per tema. |
| `TELEGRAM_ALLOWED_CHAT_IDS` | kosong | Kunci akses bot ke chat ID tertentu. |
| `TELEGRAM_AUTO_START` | `0` | Start bot otomatis dari Streamlit app. |
| `TELEGRAM_DELETE_WEBHOOK_ON_START` | `1` | Hapus webhook supaya long polling menerima pesan. |
| `TELEGRAM_DROP_PENDING_UPDATES` | `0` | Buang update lama saat deleteWebhook bila diperlukan. |
| `TELEGRAM_DEDUPE_UPDATES` | `1` | Cegah pesan yang sama diproses ulang saat Streamlit rerun/restart. |
| `TELEGRAM_BROADCAST_CHAT_IDS` | kosong | Tujuan broadcast worker pagi. |
| `WORKER_SEND_TELEGRAM` | otomatis | Aktifkan/nonaktifkan pengiriman Telegram dari `worker.py`. |
| `WORKER_REQUIRE_TELEGRAM` | `0` | Jadikan missing token/chat ID sebagai error. |
| `WORKER_TELEGRAM_TITLE` | otomatis | Header pesan Telegram pagi. |
| `WORKER_DEDUPE_TELEGRAM` | `1` | Cegah digest pagi dikirim ulang pada tanggal/chat/judul yang sama. |
| `WORKER_FORCE_SEND` | `0` | Paksa kirim ulang digest manual bila benar-benar diperlukan. |

## Jika Telegram mengirim berkali-kali

Cek tiga hal ini dulu:

1. Pastikan hanya satu mode aktif. Untuk broadcast pagi GitHub Actions, Streamlit bot interaktif boleh dimatikan dengan `auto_start = false` jika tidak diperlukan.
2. Pastikan workflow punya permission `contents: write`, karena file `data/telegram_digest_state.json` perlu di-commit agar run berikutnya tahu digest hari itu sudah terkirim.
3. Jangan set `WORKER_FORCE_SEND=1` permanen. Itu memang memaksa kirim ulang dan mengabaikan dedupe.

Untuk mengirim ulang secara sadar dari tab Actions, set variable `WORKER_FORCE_SEND=1`, jalankan workflow manual, lalu kembalikan ke `0`.

## Keamanan secrets

- Jangan commit `.streamlit/secrets.toml`; repository hanya menyertakan `.streamlit/secrets.toml.example`.
- Untuk Streamlit Cloud, isi secret lewat **Settings > Secrets** dalam format TOML.
- Dashboard hanya menampilkan status token tersedia/tidak, tidak pernah mencetak nilai token.
- Panel Telegram di sidebar menyediakan tombol tes token/webhook tanpa menampilkan token.
- `config.py` membaca prioritas: environment variable → Streamlit Secrets root-level → Streamlit Secrets sectioned.
- Jika token pernah terlanjur muncul di commit, chat, screenshot, atau log, segera rotate token di BotFather/Jina.

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
- Jina Search bukan mesin berita khusus. Query fallback dikunci ke domain penerbit dengan `site:` satu domain per request, sedangkan sosial/video/agregator diblokir setelah respons diterima. Cara ini lebih stabil daripada mengirim query panjang berisi `OR` dan banyak `-site:` yang dapat memicu 422.
- Scrape isi artikel dilakukan hanya pada artikel yang sudah lolos filter dan jumlahnya dibatasi. Jika proses terasa lambat, turunkan `NEWS_MAX_ARTICLE_SCRAPES` atau matikan sementara dengan `NEWS_ENABLE_ARTICLE_SCRAPE=0`.
- Telegram Bot interaktif memakai long polling. Pastikan proses `python telegram_bot.py` tetap berjalan di server/VPS/hosting yang mendukung worker background. Untuk broadcast pagi, GitHub Actions cukup menjalankan `worker.py` sesuai jadwal dan tidak perlu proses always-on.
- Tanggal relatif dihitung terhadap waktu Jakarta. Contoh: pukul `00:30`, artikel `2 jam yang lalu` dianggap berasal dari hari sebelumnya dan dikeluarkan.
- Putar ulang token yang pernah dibagikan di chat, commit, screenshot, atau file publik.
