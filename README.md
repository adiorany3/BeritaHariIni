# Monitor Berita Hari Ini dengan Streamlit, GitHub Actions, dan Telegram

Aplikasi ini mencari berita melalui Jina Search dengan `X-Engine: direct`, menyaring artikel yang memiliki marker waktu **hari ini** pada zona waktu Asia/Jakarta, mengelompokkan artikel berdasarkan kategori, dan mengirim tautan artikel baru ke Telegram. GitHub Actions menjalankan pemeriksaan setiap 30 menit. Streamlit memuat ulang dashboard setiap 5 menit.

## Fitur

- Query otomatis menambahkan tanggal Jakarta dan kategori utama: teknologi, edukasi, otomotif, ekonomi, olahraga, serta kesehatan.
- Memprioritaskan artikel yang memiliki marker publikasi hari ini, misalnya `15 menit yang lalu`, `2 jam yang lalu`, `Hari ini`, atau tanggal yang sama dengan tanggal Jakarta.
- Bila pencarian utama tidak menghasilkan artikel bertanda waktu, aplikasi menjalankan hingga tiga kueri cadangan. Jika sumber tetap tidak memuat waktu, aplikasi menampilkan tautan artikel langsung sebagai **kandidat artikel** dengan label “Perlu cek waktu”. Kandidat tidak disebut berita hari ini dan tidak dikirim ke Telegram.
- Menolak artikel kemarin, gambar, ikon, iklan, menu, halaman kategori, halaman pencarian, URL perantara seperti Google News, serta profil, kanal, program, pengikut, subscriber, likes, komentar, dan metrik akun.
- Menerima konten sosial individual yang memiliki URL postingan atau video langsung, misalnya Instagram Post/Reel, YouTube Watch/Shorts, TikTok Video, X Post, Threads Post, Facebook Reel/Post, LinkedIn Post, Reddit Post, dan Telegram Post.
- Semua tombol **Buka artikel asli** memakai URL langsung ke artikel penerbit atau postingan sosial individual. Aplikasi tidak menampilkan gambar hasil scraping maupun metrik engagement.
- Kategori: Teknologi, Edukasi, Otomotif, Ekonomi & Bisnis, Olahraga, Kesehatan, Hiburan, Politik, Hukum & Kriminal, Internasional, Gaya Hidup & Perjalanan, Lingkungan & Cuaca, dan Lainnya.
- Filter kategori serta judul atau sumber tersedia untuk hasil pencarian langsung dan hasil GitHub Actions.
- Respons Markdown mentah Jina tersedia pada panel audit, tetapi ditampilkan sebagai kode agar gambar, HTML, dan iklan tidak dimuat.
- Telegram hanya menerima artikel atau konten sosial langsung yang waktu publikasinya terverifikasi hari ini dan belum pernah dikirim. Pesan memuat kategori, sumber, waktu, dan URL asli tanpa metrik engagement.
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

- Tanggal dari sumber tidak selalu tersedia. Karena itu, tautan tanpa marker waktu hanya muncul sebagai kandidat verifikasi pada dashboard setelah kueri cadangan selesai. Kandidat tersebut tidak pernah dikirim sebagai notifikasi Telegram.
- Artikel dengan marker relatif dihitung terhadap waktu pemeriksaan Jakarta. Contoh: pada pukul 00:30, artikel `2 jam yang lalu` dianggap berasal dari hari sebelumnya dan dikeluarkan.
- GitHub Actions terjadwal dapat terlambat. Dashboard menunjukkan waktu pemeriksaan terakhir agar kondisi ini terlihat.
- Batasi `NOTIFICATION_LIMIT` agar Telegram tidak menerima terlalu banyak pesan pada pemeriksaan pertama.
- Putar ulang atau cabut token yang pernah dibagikan di chat, commit, screenshot, atau file publik.
