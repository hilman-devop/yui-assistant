"""Tool notebooklm: kendalikan NotebookLM (notebook.google.com) lewat browser_task.
NotebookLM tidak punya API resmi — otomasi browser asli user (sudah login Google) via
Kimi WebBridge. Lambat (1-3 menit). Prinsip: baca/tanya/generate boleh, HAPUS tidak."""
import asyncio

import httpx
import websockets

from tools.browser import _cfg, _run
from tools.registry import tool

_BUKA = "Buka https://notebook.google.com, masuk ke {target}. "
_AWAS = " JANGAN menghapus apa pun. Kalau UI berbahasa Indonesia, sesuaikan nama tombolnya."
_AKSI = ("tanya", "tambah_sumber", "upload_file", "audio_overview", "ringkasan", "study_guide",
         "faq", "jadwal")


def _instruksi(aksi: str, isi: str, target: str) -> str:
    buka = _BUKA.format(target=target)
    if aksi == "tanya":
        return (buka + f"Ketik pertanyaan ini persis apa adanya di kolom chat notebook: \"{isi}\" — "
                "tunggu jawaban selesai dimuat, kembalikan SELURUH isinya apa adanya." + _AWAS)
    if aksi == "tambah_sumber":
        return (buka + f"Klik 'Tambah sumber'/'Add source', pilih sumber dari link (situs web/YouTube), "
                f"tempel URL ini persis: {isi} — konfirmasi, tunggu sampai sumber muncul terindeks "
                "di daftar sumber, lalu selesai." + _AWAS)
    if aksi == "upload_file":
        return (buka + "Klik 'Tambah sumber'/'Add source', pilih upload file. Saat menemukan input "
                f"file (input[type=file]), pakai action upload dengan files=[\"{isi}\"] (path Windows "
                "persis, JANGAN dibuka lewat dialog). Tunggu sumber terindeks di daftar, lalu selesai." + _AWAS)
    if aksi == "audio_overview":
        return (buka + "Di panel Studio, klik 'Audio Overview' lalu konfirmasi generate. JANGAN tunggu "
                "prosesnya selesai (bisa 5-10 menit) — cukup pastikan prosesnya MULAI, lalu selesai." + _AWAS)
    tombol = {"ringkasan": "'Briefing doc' (kalau tidak ada, tanya di chat: 'rangkum semua sumber')",
              "study_guide": "'Study guide'", "faq": "'FAQ'", "jadwal": "'Timeline'"}[aksi]
    return (buka + f"Di panel Studio klik tombol {tombol}, tunggu hasilnya selesai dimuat, baca "
            "seluruh isinya, kembalikan apa adanya dalam Bahasa Indonesia." + _AWAS)


@tool("notebooklm",
      "Kendalikan NotebookLM (notebook.google.com): 'tanya' = tanya-jawab dari dokumen user; "
      "'tambah_sumber' = simpan link web/YouTube ke notebook; 'upload_file' = upload file lokal "
      "(isi = path absolut, misal dari WA); 'audio_overview' = bikin podcast AI "
      "(jalan di background); 'ringkasan'/'study_guide'/'faq'/'jadwal' = generate laporan dari sumber. "
      "Pakai HANYA kalau user menyebut notebooklm/notebook. LAMBAT (1-3 menit, lewat browser).",
      properties={"aksi": {"type": "string", "enum": list(_AKSI), "description": "jenis tugas"},
                  "isi": {"type": "string",
                          "description": "pertanyaan (tanya) / URL (tambah_sumber); kosong utk aksi lain"},
                  "notebook": {"type": "string",
                               "description": "judul notebook; kosong = yang terakhir dibuka"}},
      required=["aksi"],
      announce="Sebentar ya, kukerjain di NotebookLM dulu. ")
def notebooklm(aksi: str, isi: str = "", notebook: str = "") -> str:
    aksi = aksi.strip().lower()
    if aksi not in _AKSI:
        return f"Aksi '{aksi}' tidak dikenal. Pilihan: {', '.join(_AKSI)}."
    if aksi in ("tanya", "tambah_sumber", "upload_file") and not isi.strip():
        kebutuhan = {"tanya": "pertanyaan", "tambah_sumber": "URL sumber", "upload_file": "path file"}
        return f"Aksi {aksi} butuh 'isi' ({kebutuhan[aksi]})."
    target = (f'notebook berjudul "{notebook.strip()}"' if notebook.strip()
              else "notebook yang paling baru dibuka")
    try:
        return asyncio.run(_run(_instruksi(aksi, isi.strip(), target), _cfg()))
    except (httpx.ConnectError, OSError, websockets.InvalidURI):
        return "Dashboard Kimi web belum jalan. Nyalain dulu dari Kimi CLI dengan /web."
    except TimeoutError:
        return "NotebookLM kelamaan, dibatalkan. Cek langsung di browser."
