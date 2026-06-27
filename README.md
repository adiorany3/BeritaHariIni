# Monitor Berita Hari Ini dengan Streamlit, GitHub Actions, dan Telegram

Aplikasi ini mencari berita melalui Jina Search dengan `X-Engine: direct`, menyaring artikel yang memiliki marker waktu **hari ini** pada zona waktu Asia/Jakarta, mengelompokkan artikel berdasarkan kategori, dan mengirim tautan artikel baru ke Telegram. GitHub Actions menjalankan pemeriksaan setiap 30 menit. Streamlit memuat ulang dashboard setiap 5 menit.

## Fitur

- Query otomatis menambahkan tanggal Jakarta dan kategori utama: teknologi, edukasi, otomotif, ekonomi, olahraga, serta kesehatan.
- Hanya menyimpan artikel yang memiliki marker publikasi hari ini, misalnya `15 menit yang lalu`, `2 jam yang lalu`, `Hari ini`, atau tanggal yang sama dengan tanggal Jakarta.
- Menolak artikel kemarin, tautan tanpa waktu, gambar, ikon, iklan, menu, halaman kategori, halaman pencarian, URL perantara seperti Google News, serta akun Instagram, YouTube, TikTok, Facebook, X, profil, kanal, program, pengikut, dan subscriber.
- Semua tombol **Buka artikel asli** memakai URL langsung dari situs penerbit. Aplikasi tidak menampilkan gambar hasil scraping maupun tautan media sosial.
- Kategori: Teknologi, Edukasi, Otomotif, Ekonomi & Bisnis, Olahraga, Kesehatan, Hiburan, Politik, Hukum & Kriminal, Internasional, Gaya Hidup & Perjalanan, Lingkungan & Cuaca, dan Lainnya.
- Filter kategori serta judul atau sumber tersedia untuk hasil pencarian langsung dan hasil GitHub Actions.
- Respons Markdown mentah Jina tersedia pada panel audit, tetapi ditampilkan sebagai kode agar gambar, HTML, dan iklan tidak dimuat.
- Telegram hanya menerima artikel langsung yang belum pernah dikirim. Pesan memuat kategori, sumber, waktu, dan URL asli.
- Token serta chat ID tidak tersimpan dalam source code.

## Struktur proyek

```text
.
├── .github/workflows/news-monitor.yml
├── .streamlit/
├── data/
├── tests/
├── app.py
├── news_service.py
├── storage.py
├── telegram.py
└── worker.py
```

## Jalankan di komputer

```bash
git clone <URL_REPOSITORI_ANDA>
cd news_monitor_streamlit
python -m venv .venv
```

Aktifkan virtual environment, lalu pasang dependensi:

```bash
pip install -r requirements.txt
```

Salin `.env.example` menjadi `.env`, isi nilainya, lalu ekspor sebagai environment variable. Contoh Bash:

```bash
export JINA_API_KEY="jina_kunci_anda"
export TELEGRAM_BOT_TOKEN="token_bot_anda"
export TELEGRAM_CHAT_ID="chat_id_anda"
python worker.py
```

Untuk dashboard lokal, salin `.streamlit/secrets.toml.example` menjadi `.streamlit/secrets.toml`, isi `JINA_API_KEY`, lalu jalankan:

```bash
streamlit run app.py
```

## Deploy di GitHub dan Streamlit Community Cloud

1. Buat repository GitHub baru, lalu unggah seluruh isi proyek ini.
2. Di GitHub, buka **Settings > Secrets and variables > Actions > New repository secret**. Tambahkan `JINA_API_KEY`, `TELEGRAM_BOT_TOKEN`, dan `TELEGRAM_CHAT_ID`.
3. Opsional, di **Settings > Secrets and variables > Actions > Variables**, buat `NEWS_QUERY` untuk mengganti kueri default.
4. Buka tab **Actions**, jalankan workflow **Pantau berita dan Telegram** dengan **Run workflow** satu kali untuk membuat data awal.
5. Di Streamlit Community Cloud, buat aplikasi baru dari repo ini dengan file utama `app.py`.
6. Pada **Settings > Secrets** Streamlit, masukkan:

```toml
JINA_API_KEY = "jina_kunci_anda"
# Opsional. Isi URL raw GitHub untuk data/latest_news.json.
NEWS_DATA_URL = ""
```

`NEWS_DATA_URL` bersifat opsional. Bila diisi URL raw GitHub, dashboard mengambil data terbaru tanpa perlu menunggu deployment ulang.

## Pengujian

```bash
python -m unittest discover -s tests -v
```

## Catatan operasional

- Tanggal dari sumber tidak selalu tersedia. Agar rentang waktu konsisten, tautan tanpa marker waktu sengaja tidak ditampilkan.
- Artikel dengan marker relatif dihitung terhadap waktu pemeriksaan Jakarta. Contoh: pada pukul 00:30, artikel `2 jam yang lalu` dianggap berasal dari hari sebelumnya dan dikeluarkan.
- GitHub Actions terjadwal dapat terlambat. Dashboard menunjukkan waktu pemeriksaan terakhir agar kondisi ini terlihat.
- Batasi `NOTIFICATION_LIMIT` agar Telegram tidak menerima terlalu banyak pesan pada pemeriksaan pertama.
- Putar ulang atau cabut token yang pernah dibagikan di chat, commit, screenshot, atau file publik.
