# Monitor Berita Hari Ini dengan Streamlit, GitHub Actions, dan Telegram

Aplikasi ini mengambil hasil pencarian berita melalui Jina Search, menampilkan hasil terakhir di Streamlit, lalu mengirim artikel baru ke Telegram. GitHub Actions menjalankan pemeriksaan tiap 30 menit. Tampilan Streamlit dimuat ulang tiap 5 menit.

## Fitur

- Query otomatis memakai tanggal **Asia/Jakarta**.
- Header `Authorization: Bearer ...` dan `X-Engine: direct` diterapkan saat meminta Jina Search.
- Hasil dinormalisasi dari respons JSON atau Markdown.
- Pencarian langsung di Streamlit memperlihatkan respons Markdown mentah Jina apa adanya, termasuk format `Title`, `URL Source`, deskripsi, dan tautan.
- Artikel dideduplikasi berdasarkan URL dan judul.
- Telegram hanya menerima artikel yang belum pernah diberi notifikasi.
- Riwayat dan hasil terbaru disimpan di folder `data/` agar dapat dipakai halaman Streamlit.
- Tidak ada token atau ID chat yang tersimpan di kode.

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

Untuk dashboard lokal, salin `.streamlit/secrets.toml.example` menjadi `.streamlit/secrets.toml`, isi `JINA_API_KEY`, lalu jalankan. Tombol **Cari berita terbaru** menampilkan daftar artikel dan respons Markdown mentah dari Jina di halaman yang sama:

```bash
streamlit run app.py
```

## Deploy di GitHub dan Streamlit Community Cloud

1. Buat repository GitHub baru, lalu unggah seluruh isi proyek ini.
2. Di GitHub, buka **Settings > Secrets and variables > Actions > New repository secret**. Tambahkan:
   - `JINA_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. Opsional, di **Settings > Secrets and variables > Actions > Variables**, buat `NEWS_QUERY` untuk mengganti kueri default.
4. Buka tab **Actions**, jalankan workflow **Pantau berita dan Telegram** dengan **Run workflow** sekali untuk membuat data awal.
5. Di Streamlit Community Cloud, buat aplikasi baru dari repo ini dengan file utama `app.py`.
6. Pada pengaturan Secrets Streamlit, masukkan:

```toml
JINA_API_KEY = "jina_kunci_anda"
# Isi setelah repository publik tersedia. Gunakan URL raw data/latest_news.json.
NEWS_DATA_URL = ""
```

`NEWS_DATA_URL` bersifat opsional. Jika kosong, Streamlit membaca file `data/latest_news.json` yang ikut berada di repo saat deployment. Jika diisi URL raw GitHub, dashboard menarik data terbaru tanpa menunggu deployment ulang.

## Telegram chat ID

Kirim pesan apa saja ke bot Anda terlebih dahulu. Setelah itu, buka endpoint `getUpdates` Telegram dengan token bot secara privat untuk melihat nilai `chat.id`. Jangan masukkan token bot di URL, issue GitHub, atau source code.

## Pengujian

```bash
python -m unittest discover -s tests -v
```

## Catatan operasional

- GitHub Actions berbasis jadwal dapat mengalami keterlambatan. Dashboard menampilkan waktu pemeriksaan terakhir agar keterlambatan terlihat.
- Pencarian memakai tanggal hari ini untuk meningkatkan relevansi, tetapi tanggal publikasi tiap artikel bergantung pada metadata yang dikembalikan sumber dan mesin pencari. Periksa halaman asli untuk konfirmasi.
- Respons Markdown mentah dapat sangat panjang. Dashboard menaruhnya di sesi browser saat pencarian langsung dan tidak menyimpannya ke GitHub agar repository tidak cepat membesar.
- Batasi `NOTIFICATION_LIMIT` agar Telegram tidak menerima terlalu banyak pesan ketika pertama kali dijalankan.
- Putar ulang atau cabut token yang pernah dibagikan di chat, commit, screenshot, atau file publik.
