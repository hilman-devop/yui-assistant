"""Tool katakan: Yui mengucapkan teks lewat speaker laptop (suara beneran bunyi).
Dipicu dari WA/suara saat user minta Yui bicara/ngomong/bilang sesuatu."""
from pathlib import Path

import httpx
import yaml

from tools.registry import tool

_ROOT = Path(__file__).resolve().parent.parent


@tool("katakan",
      "Ucapkan teks lewat speaker laptop dengan suara Yui (bunyi beneran). Dipakai HANYA kalau "
      "user eksplisit minta Yui bicara/ngomong/bilang/katakan sesuatu dengan suara, misal dari WA. "
      "Suara Yui SELALU bahasa Jepang — isi 'teks' dengan bahasa Jepang kasual yang imut "
      "(panggil user ご主人様), bukan bahasa Indonesia.",
      properties={"teks": {"type": "string", "description": "kalimat yang diucapkan, 100% bahasa Jepang"}},
      required=["teks"])
def katakan(teks: str) -> str:
    cfg = yaml.safe_load(open(_ROOT / "config.yaml", encoding="utf-8"))["web"]
    try:
        r = httpx.post(f"http://{cfg['host']}:{cfg['port']}/api/say", json={"text": teks}, timeout=5)
        r.raise_for_status()
    except Exception as e:
        return f"Gagal bicara: {e}"
    return f"Sudah kuucapkan dengan suara: \"{teks}\""
