"""Tools aplikasi: buka app, buka URL, fokus window."""
import os
import shutil
import subprocess
import webbrowser

from tools.registry import tool

_ALIASES = {
    "chrome": "chrome", "google chrome": "chrome", "browser": "chrome",
    "notepad": "notepad", "kalkulator": "calc", "calculator": "calc",
    "explorer": "explorer", "file explorer": "explorer", "cmd": "cmd",
    "terminal": "wt", "spotify": "spotify", "vscode": "code", "vs code": "code",
    "word": "winword", "excel": "excel", "paint": "mspaint",
    "task manager": "taskmgr", "settings": "ms-settings:", "pengaturan": "ms-settings:",
}


@tool("open_app", "Buka aplikasi di laptop (chrome, notepad, spotify, vscode, dll)",
      {"name": {"type": "string", "description": "nama aplikasi"}}, ["name"])
def open_app(name: str) -> str:
    target = _ALIASES.get(name.strip().lower(), name.strip())
    try:
        if shutil.which(target):
            subprocess.Popen([target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.startfile(target)  # handle URI (ms-settings:) & nama di PATH Windows
        return f"Membuka {name}."
    except OSError as e:
        return f"Gagal membuka {name}: {e}"  # tanpa shell=True: target dari LLM = trust boundary


@tool("open_url", "Buka URL/domain di browser default, INSTAN tanpa interaksi. Pakai untuk SEMUA permintaan 'buka <situs>' (youtube, twitter, gmail, dll). Tugas yang butuh klik/baca isi halaman baru pakai browser_task.",
      {"url": {"type": "string", "description": "URL atau domain, misal youtube.com"}}, ["url"])
def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Membuka {url}."


def _first_video_id(judul: str) -> str | None:
    """Video ID hasil pertama pencarian YouTube (scrape ytInitialData — tanpa API key)."""
    import re

    import httpx
    r = httpx.get("https://www.youtube.com/results", params={"search_query": judul},
                  headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    m = re.search(r'"videoId":"([\w-]{11})"', r.text)
    return m.group(1) if m else None


@tool("putar_lagu", "Putar lagu/musik di YouTube — langsung play video pertama hasil pencarian (autoplay). Pakai untuk 'putar/setel/play lagu X'. INSTAN, jangan pakai browser_task untuk ini.",
      {"judul": {"type": "string", "description": "judul lagu / artis"}}, ["judul"])
def putar_lagu(judul: str) -> str:
    try:
        vid = _first_video_id(judul)
    except Exception as e:
        vid = None
        print(f"[tool] pencarian youtube gagal: {e}")
    if vid:
        webbrowser.open(f"https://www.youtube.com/watch?v={vid}")
        return f"Memutar '{judul}' di YouTube."
    webbrowser.open(f"https://www.youtube.com/results?search_query={judul}")  # fallback: halaman hasil
    return f"Video tidak ketemu langsung — kubuka halaman pencarian '{judul}'."


@tool("cari_github", "Cari/riset repository GitHub (nama, deskripsi, stars, url) via API publik — INSTAN, "
      "tanpa browser. Pakai untuk 'cari/riset repo X di github'. Untuk baca isi repo/halaman lebih "
      "dalam baru pakai browser_task.",
      {"query": {"type": "string", "description": "kata kunci pencarian repo"}}, ["query"])
def cari_github(query: str) -> str:
    import httpx
    try:
        r = httpx.get("https://api.github.com/search/repositories",
                      params={"q": query, "per_page": 5, "sort": "stars"},
                      headers={"Accept": "application/vnd.github+json", "User-Agent": "yui"}, timeout=10)
        r.raise_for_status()
        items = r.json().get("items", [])
    except Exception as e:
        return f"Pencarian GitHub gagal: {e}"
    if not items:
        return f"Tidak ada repo yang cocok untuk '{query}'."
    return "Repo teratas: " + "; ".join(
        f"{i['full_name']} (bintang {i['stargazers_count']}) — {(i['description'] or '-')[:80]}, {i['html_url']}"
        for i in items)


@tool("window_focus", "Aktifkan/fokus ke jendela berdasarkan judulnya",
      {"title": {"type": "string", "description": "sebagian judul jendela"}}, ["title"])
def window_focus(title: str) -> str:
    import pygetwindow as gw
    wins = [w for w in gw.getWindowsWithTitle(title) if w.title.strip()]
    if not wins:
        return f"Tidak ada jendela berjudul '{title}'."
    w = wins[0]
    if w.isMinimized:
        w.restore()
    try:
        w.activate()
    except Exception:
        pass  # Windows kadang menolak activate dari background; restore sudah cukup
    return f"Fokus ke '{w.title}'."
