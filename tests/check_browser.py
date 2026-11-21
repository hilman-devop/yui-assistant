"""Self-check browser_task: registrasi, parsing context.jsonl, error path, live test."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools  # noqa: F401
from tools.registry import announce_of, names, schemas
from tools.browser import _last_assistant_text, browser_task


def main() -> None:
    # 1) registrasi
    assert "browser_task" in names(), "browser_task harus terdaftar"
    schema = next(s for s in schemas() if s["function"]["name"] == "browser_task")
    assert schema["function"]["parameters"]["required"] == ["task"]
    assert announce_of("browser_task"), "announce harus tersimpan"
    assert announce_of("get_time") == "", "tool biasa tanpa announce"
    print("registrasi + announce OK")

    # 2) parsing context*.jsonl: pilih mtime terbaru, ambil assistant terakhir, dukung parts
    with tempfile.TemporaryDirectory() as d:
        lama = Path(d) / "context.jsonl"
        lama.write_text(json.dumps({"role": "assistant", "content": "jawaban lama"}) + "\n", encoding="utf-8")
        baru = Path(d) / "context_1.jsonl"
        baru.write_text(
            json.dumps({"role": "user", "content": "tanya"}) + "\n"
            + json.dumps({"role": "assistant", "content": [{"type": "text", "text": "jawaban "}, {"type": "text", "text": "baru"}]}) + "\n",
            encoding="utf-8")
        now = time.time()
        os.utime(lama, (now - 100, now - 100))
        os.utime(baru, (now, now))
        assert _last_assistant_text(d) == "jawaban baru", f"parsing salah: {_last_assistant_text(d)!r}"
    print("parsing context.jsonl OK")

    # 3) server mati -> pesan error user-friendly (bukan traceback)
    hasil = browser_task.__wrapped__ if hasattr(browser_task, "__wrapped__") else None
    import tools.browser as tb
    asli = tb._cfg
    tb._cfg = lambda: {"kimi_web": "http://127.0.0.1:1", "session_id": "x", "token": "", "timeout_s": 5}
    try:
        out = tb.browser_task("tes")
        assert "belum jalan" in out, f"error path salah: {out!r}"
    finally:
        tb._cfg = asli
    print("error path server mati OK")

    # 4) live test (skip kalau dashboard mati)
    import httpx
    try:
        httpx.get("http://127.0.0.1:5494/api/sessions/", timeout=3).raise_for_status()
    except Exception:
        print("dashboard kimi web mati -> live test dilewati")
        print("BROWSER OK (parsial)")
        return
    out = browser_task("jawab singkat: berapa 2+2?")
    print(f"live: {out[:100]!r}")
    assert out.strip() and "belum jalan" not in out and "tidak ketemu" not in out, f"live gagal: {out!r}"
    assert "4" in out, f"jawaban aneh: {out!r}"
    print("BROWSER OK: tool + dashboard + session berfungsi")


if __name__ == "__main__":
    main()
