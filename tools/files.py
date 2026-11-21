"""Tools file & clipboard."""
from pathlib import Path

import pyperclip

from tools.registry import tool

_DEFAULT_DIRS = [Path.home() / d for d in ("Desktop", "Documents", "Downloads")]


@tool("find_file", "Cari file berdasarkan nama/pola di folder umum (Desktop, Documents, Downloads)",
      {"pattern": {"type": "string", "description": "pola nama, misal 'laporan' atau '*.pdf'"},
       "folder": {"type": "string", "description": "opsional, path folder spesifik"}})
def find_file(pattern: str, folder: str | None = None) -> str:
    if "*" not in pattern and "?" not in pattern:
        pattern = f"*{pattern}*"
    roots = [Path(folder)] if folder else _DEFAULT_DIRS
    hasil: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob(pattern):
                hasil.append(str(p))
                if len(hasil) >= 10:
                    break
        except OSError:
            continue
        if len(hasil) >= 10:
            break
    if not hasil:
        return f"File '{pattern}' tidak ketemu."
    return "Ketemu:\n" + "\n".join(hasil[:10])


@tool("clipboard_read", "Baca isi clipboard")
def clipboard_read() -> str:
    text = pyperclip.paste()
    return f"Isi clipboard: {text[:500]}" if text else "Clipboard kosong."


@tool("clipboard_write", "Salin teks ke clipboard", {"text": {"type": "string"}}, ["text"])
def clipboard_write(text: str) -> str:
    pyperclip.copy(text)
    return "Teks disalin ke clipboard."
