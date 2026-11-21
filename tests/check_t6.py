"""Self-check T6: registry tools — schema, dispatch, volume beneran berubah, konfirmasi.
Run: .venv\\Scripts\\python tests\\check_t6.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools  # registrasi semua tool
from tools.registry import dispatch, names, needs_confirm, schemas


def main() -> None:
    daftar = names()
    print(f"{len(daftar)} tools: {', '.join(daftar)}")
    assert len(daftar) >= 12, "minimal 12 tools"

    # schema valid untuk OpenAI
    for s in schemas():
        f = s["function"]
        assert f["name"] and f["description"] and "properties" in f["parameters"]

    # aksi berisiko ter-flag konfirmasi
    assert needs_confirm("lock_pc") and needs_confirm("sleep_pc")
    assert not needs_confirm("set_volume")

    # get_time
    assert ":" in dispatch("get_time")

    # volume: simpan, ubah, verifikasi, kembalikan
    awal = dispatch("get_volume")
    print(awal)
    v0 = int(awal.split()[2])
    target = 35 if v0 != 35 else 40
    assert f"{target} persen" in dispatch("set_volume", {"percent": target})
    assert f"{target} persen" in dispatch("get_volume"), "volume tidak berubah!"
    dispatch("set_volume", {"percent": v0})  # restore
    print(f"volume {v0}->{target}->{v0} OK")

    # clipboard roundtrip
    dispatch("clipboard_write", {"text": "yui-test-123"})
    assert "yui-test-123" in dispatch("clipboard_read")

    # find_file di folder project
    assert "config.yaml" in dispatch("find_file", {"pattern": "config.yaml", "folder": "."})

    # error handling
    assert "tidak dikenal" in dispatch("tool_ngawur")
    assert "Argumen salah" in dispatch("set_volume", {})

    print("T6 OK: registry + tools Windows berfungsi")


if __name__ == "__main__":
    main()
