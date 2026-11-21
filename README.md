# Yui — Indonesian Voice AI Assistant

![Python 3.12](https://img.shields.io/badge/Python_3.12-2f81f7?style=flat) ![FastAPI](https://img.shields.io/badge/FastAPI-2f81f7?style=flat) ![PyQt6](https://img.shields.io/badge/PyQt6-2f81f7?style=flat) ![PixiJS](https://img.shields.io/badge/PixiJS-2f81f7?style=flat) ![Live2D](https://img.shields.io/badge/Live2D-2f81f7?style=flat) ![Groq](https://img.shields.io/badge/Groq-2f81f7?style=flat) ![Whisper](https://img.shields.io/badge/Whisper-2f81f7?style=flat) ![SQLite](https://img.shields.io/badge/SQLite-2f81f7?style=flat)

> Pipeline voice assistant dari wake word, VAD, ASR, LLM, TTS, sampai tool execution dalam satu workspace.

## Tentang proyek

Pipeline voice assistant dari wake word, VAD, ASR, LLM, TTS, sampai tool execution dalam satu workspace. Dokumentasi ini dibuat sebagai panduan singkat untuk memahami ruang lingkup proyek, menjalankannya secara lokal, dan membaca batasan penggunaannya.

## Fitur utama

- Pipeline VAD → ASR → LLM → TTS
- Wake word dan barge-in
- Tool system untuk aplikasi, file, browser, dan memory
- Failover endpoint LLM
- Karakter Live2D
- Mode desktop dan headless WhatsApp

## Teknologi

- Python 3.12
- FastAPI
- PyQt6
- PixiJS
- Live2D
- Groq
- Whisper
- SQLite

## Menjalankan secara lokal

Prasyarat dan konfigurasi dapat berbeda menurut sistem operasi. Contoh langkah utama:

```bash
pip install -r requirements.txt
python main.py
# atau
python main.py --wa-only
```

## Struktur dan pengembangan

Mulai dari entry point dan folder konfigurasi proyek. Pisahkan credential lokal dari source code, tambahkan test untuk perubahan penting, dan gunakan environment variable untuk konfigurasi deployment.

## Keamanan

- Jangan commit API key, password, token, session ID, atau data pribadi.
- Gunakan file environment lokal dan contoh konfigurasi tanpa nilai rahasia.
- Uji perubahan pada environment development sebelum deployment.

## Status

Proyek ini merupakan bagian dari portofolio **Hilman Arifin Ilham** dan dapat dikembangkan sesuai kebutuhan penggunaan.

> **Catatan:** Semua API key, session ID, webhook secret, dan nomor pribadi harus disediakan lewat konfigurasi lokal yang tidak di-commit.

## Lisensi

Belum ada lisensi open-source yang dinyatakan di repository ini. Hubungi pemilik repository sebelum menggunakan ulang atau mendistribusikan kode.

---

Dibuat oleh [Hilman Arifin Ilham](https://github.com/hilman-devop).
