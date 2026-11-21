# Yui — Asisten Suara AI & Desktop Pet

> Asisten pribadi berbahasa Indonesia berwujud karakter Live2D: mendengar perintah suara, menjawab dengan suara, mengendalikan PC, dan membalas WhatsApp.

## ✨ Fitur

- Pipeline VAD -> ASR -> LLM -> TTS
- Wake-word bebas posisi + barge-in
- 24 tools (system, apps, files, memory, browser)
- Failover 5 endpoint LLM dan 3 key TTS
- 2 karakter Live2D berganti-suara
- Memori jangka panjang (SQLite)
- Bridge WhatsApp (VN -> VN)

## 🛠 Tech Stack

"Python 3.12" "FastAPI" "PyQt6" "PixiJS + Live2D" "Groq" "Fish Audio" "faster-whisper" "Silero VAD"

## 🚀 Menjalankan

```
pip install -r requirements.txt
python main.py            # mode desktop pet
python main.py --wa-only  # headless
```

## 📌 Catatan

Proyek ini merupakan bagian dari portofolio pribadi. Kode disusun untuk kebutuhan nyata,
bukan sekadar demo, sehingga sebagian konfigurasi spesifik lingkungan mungkin perlu
disesuaikan sebelum dijalankan.
