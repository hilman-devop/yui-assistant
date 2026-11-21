"""Registry tools Yui: dekorator @tool, schema OpenAI, dispatcher.
Aksi berisiko (REQUIRES_CONFIRM) wajib konfirmasi dulu sebelum dieksekusi."""
import json
from typing import Callable

_REGISTRY: dict[str, dict] = {}

REQUIRES_CONFIRM = {"lock_pc", "sleep_pc"}


def tool(name: str, description: str, properties: dict | None = None,
         required: list[str] | None = None, announce: str = "") -> Callable:
    def deco(fn: Callable) -> Callable:
        _REGISTRY[name] = {
            "fn": fn,
            "announce": announce,  # diucapkan/dikirim dulu sebelum eksekusi (tool yang lama)
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties or {},
                        "required": required or [],
                    },
                },
            },
        }
        return fn
    return deco


def schemas() -> list[dict]:
    return [v["schema"] for v in _REGISTRY.values()]


def names() -> list[str]:
    return list(_REGISTRY)


def announce_of(name: str) -> str:
    return _REGISTRY.get(name, {}).get("announce", "")


def dispatch(name: str, args: dict | str | None = None) -> str:
    """Eksekusi tool -> string hasil (Bahasa Indonesia) untuk dibaca LLM/user."""
    entry = _REGISTRY.get(name)
    if entry is None:
        return f"Tool '{name}' tidak dikenal."
    if isinstance(args, str):
        try:
            args = json.loads(args) if args else {}
        except json.JSONDecodeError:
            return f"Argumen tool '{name}' bukan JSON valid."
    try:
        return str(entry["fn"](**(args or {})))
    except TypeError as e:
        return f"Argumen salah untuk '{name}': {e}"
    except Exception as e:
        return f"Tool '{name}' gagal: {type(e).__name__}: {e}"


def needs_confirm(name: str) -> bool:
    return name in REQUIRES_CONFIRM
