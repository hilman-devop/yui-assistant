"""Tool memori: user bilang 'ingat bahwa ...' -> disimpan ke facts.json."""
from memory.store import get_memory
from tools.registry import tool


@tool("remember_fact", "Simpan fakta tentang pengguna (nama, preferensi, proyek, dll)",
      {"key": {"type": "string", "description": "nama fakta, misal 'nama_user'"},
       "value": {"type": "string", "description": "isi fakta"}},
      ["key", "value"])
def remember_fact(key: str, value: str) -> str:
    get_memory().set_fact(key, value)
    return f"Siap, aku ingat: {key} = {value}."
