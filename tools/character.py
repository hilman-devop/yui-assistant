"""Tool ganti_karakter: switch karakter Live2D pet via endpoint server.
Pet + tab browser otomatis reload (server broadcast {reload} via WS)."""
from pathlib import Path

import httpx
import yaml

from tools.registry import tool

_ROOT = Path(__file__).resolve().parent.parent


def _base() -> str:
    cfg = yaml.safe_load(open(_ROOT / "config.yaml", encoding="utf-8"))["web"]
    return f"http://{cfg['host']}:{cfg['port']}"


@tool("ganti_karakter",
      "Ganti karakter/avatar Live2D pet desktop ke karakter lain yang tersedia. "
      "HANYA kalau user eksplisit minta ganti/switch karakter atau avatar.",
      properties={"nama": {"type": "string",
                           "description": "nama folder atau nomor karakter; kosong = karakter berikutnya"}},
      announce="Oke, ganti karakter dulu ya.")
def ganti_karakter(nama: str = "") -> str:
    try:
        info = httpx.get(_base() + "/api/character", timeout=5).json()
    except httpx.HTTPError:
        return "Server avatar belum jalan, karakter tidak bisa diganti."
    avail = info["available"]
    if not avail:
        return "Belum ada karakter di web/assets."
    cur = info["model"]
    n = nama.strip().lower()
    if not n:
        target = avail[(avail.index(cur) + 1) % len(avail)] if cur in avail else avail[0]
    elif n.isdigit() and 1 <= int(n) <= len(avail):
        target = avail[int(n) - 1]
    else:
        cocok = [a for a in avail if n in a.split("/")[0].lower()]
        if not cocok:
            daftar = ", ".join(f"{i + 1}. {a.split('/')[0]}" for i, a in enumerate(avail))
            return f"Karakter '{nama}' tidak ada. Pilihan: {daftar}"
        target = cocok[0]
    if target == cur:
        return f"Sekarang sudah pakai {cur.split('/')[0]}."
    httpx.post(_base() + "/api/character", json={"model": target}, timeout=5)
    return f"Karakter diganti ke {target.split('/')[0]} — pet otomatis reload."
