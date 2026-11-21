"""Tool mode_diam: matikan/nyalakan pendengaran Yui (mic diabaikan saat diam).
Sama dengan hotkey F11 — dipakai supaya bisa dipicu dari suara/WA.
Bangun dari diam hanya bisa via WA/hotkey (Yui tidak mendengar saat diam)."""
from pathlib import Path

import httpx
import yaml

from tools.registry import tool

_ROOT = Path(__file__).resolve().parent.parent


def _base() -> str:
    cfg = yaml.safe_load(open(_ROOT / "config.yaml", encoding="utf-8"))["web"]
    return f"http://{cfg['host']}:{cfg['port']}"


@tool("mode_diam",
      "Kontrol mode diam Yui: saat diam, Yui berhenti mendengarkan mic dan tidak merespons suara "
      "sampai dinyalakan lagi. Dipakai HANYA kalau user eksplisit minta Yui diam/jangan dengarkan/"
      "mute, atau sebaliknya minta Yui bangun/lanjut mendengarkan/unmute.",
      properties={"aktif": {"type": "boolean",
                            "description": "true = diam (matikan pendengaran), false = mendengarkan lagi; kosong = toggle"}})
def mode_diam(aktif: bool | None = None) -> str:
    payload = {} if aktif is None else {"paused": aktif}
    try:
        r = httpx.post(_base() + "/api/pause", json=payload, timeout=5)
        paused = r.json()["paused"]
    except Exception as e:
        return f"Gagal mengatur mode diam: {e}"
    if paused:
        return "Yui sekarang diam, tidak mendengarkan. Bilang lewat WA atau tekan F11 untuk membangunkan."
    return "Yui mendengarkan lagi."
