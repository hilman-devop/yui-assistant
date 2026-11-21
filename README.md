# Yui — Indonesian Voice AI Assistant

> Asisten suara berbahasa Indonesia dengan karakter Live2D yang dapat mendengar perintah, menjawab dengan suara, menjalankan tool desktop, menyimpan memori, dan terhubung ke WhatsApp.

**Stack:** Python · FastAPI · Live2D · Voice AI

## Ringkasan

Asisten suara berbahasa Indonesia dengan karakter Live2D yang dapat mendengar perintah, menjawab dengan suara, menjalankan tool desktop, menyimpan memori, dan terhubung ke WhatsApp.

## Fitur utama

- Pipeline VAD → ASR → LLM → TTS
- Wake-word bebas posisi dan barge-in
- 24 tool untuk system, aplikasi, file, browser, dan memory
- Failover endpoint LLM dan TTS
- Memori jangka panjang berbasis SQLite
- Test untuk browser, voice flow, tool, dan WhatsApp bridge

## Menjalankan secara lokal

~~~bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
~~~

## Keamanan dan batasan

Credential provider, session ID, webhook secret, dan nomor pribadi wajib disimpan di konfigurasi lokal.

Jangan commit API key, password, token, session ID, data pribadi, atau credential deployment.

## Status

Project portfolio aktif oleh **Hilman Arifin Ilham**. Verifikasi ulang dependency dan konfigurasi sebelum deployment production.

## Lisensi

Belum ada lisensi open-source yang dinyatakan. Hubungi pemilik repository sebelum menggunakan ulang atau mendistribusikan kode.

---

Dibuat oleh [Hilman Arifin Ilham](https://github.com/hilman-devop).
