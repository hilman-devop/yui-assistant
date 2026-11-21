"""Self-check T11: desktop pet PyQt6 — window muncul, on-top, dan TRANSPARAN.
Bukti transparan: 4 pojok window di-screenshot; kalau tembus, piksel pojok = desktop
di belakangnya (bukan hitam pekat / bukan #0d1117).
Run: .venv\\Scripts\\python tests\\check_t11.py
"""
import ctypes
import subprocess
import sys
import time
from pathlib import Path

import httpx
import mss

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WS_EX_TOPMOST = 0x8
GWL_EXSTYLE = -20
user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def main() -> None:
    proc = subprocess.Popen([sys.executable, "-u", "main.py"],
                            cwd=Path(__file__).resolve().parent.parent)
    try:
        hwnd = 0
        for _ in range(120):  # QtWebEngine + whisper butuh waktu
            hwnd = user32.FindWindowW(None, "Yui")
            if hwnd:
                break
            time.sleep(0.5)
        assert hwnd, "window pet 'Yui' tidak muncul"
        print(f"window pet muncul: hwnd={hwnd}")

        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        assert style & WS_EX_TOPMOST, "window tidak always-on-top"
        print("always-on-top OK")

        time.sleep(6)  # beri waktu render model
        rc = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        with mss.mss() as sct:
            img = sct.grab({"left": rc.left, "top": rc.top,
                            "width": rc.right - rc.left, "height": rc.bottom - rc.top})
        w, h = img.width, img.height
        pojok = [img.pixel(2, 2), img.pixel(w - 3, 2),
                 img.pixel(2, h - 3), img.pixel(w - 3, h - 3)]
        print(f"piksel pojok (RGB): {pojok}")
        hitam = lambda p: p[0] < 12 and p[1] < 12 and p[2] < 12
        gelap_web = lambda p: abs(p[0] - 13) < 6 and abs(p[1] - 17) < 6 and abs(p[2] - 23) < 6
        assert not all(hitam(p) for p in pojok), "4 pojok hitam pekat -> tidak transparan"
        assert not all(gelap_web(p) for p in pojok), "4 pojok = warna halaman -> tidak transparan"
        print("transparansi OK (pojok menembus desktop)")

        r = httpx.get("http://127.0.0.1:8765/", timeout=10)
        assert r.status_code == 200
        print("server avatar OK")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("T11 OK: desktop pet PyQt6 berfungsi")


if __name__ == "__main__":
    main()
