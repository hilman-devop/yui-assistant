"""Self-check T4: LLM mock stream + JSON extractor.
Run: .venv\\Scripts\\python tests\\check_t4.py
"""
import asyncio
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm import MockLlm, build_llm, extract_json_action


async def main() -> None:
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    # paksa jalur mock: tanpa endpoints + env yang pasti kosong (kebal isi .env)
    cfg["llm"] = dict(cfg["llm"], endpoints=[], api_key_env="YUI_KEY_PASTI_KOSONG")
    llm = build_llm(cfg["llm"])
    assert isinstance(llm, MockLlm), "harus mock selama API key belum diisi"

    msgs = [{"role": "system", "content": "x"}, {"role": "user", "content": "Yui, kecilin volume dong"}]
    t0 = time.perf_counter()
    chunks = [c async for c in llm.stream(msgs)]
    t_first = time.perf_counter() - t0
    full = "".join(chunks)
    print(f"mock reply: '{full.strip()}' ({len(chunks)} chunks, selesai {t_first:.2f}s)")
    assert extract_json_action(full) is not None, "keyword volume harus menghasilkan JSON aksi"
    assert len(chunks) >= 2, "harus streaming per potongan"

    chat = [c async for c in llm.stream([{"role": "user", "content": "halo apa kabar"}])]
    assert "apa kabar" in "".join(chat) and len(chat) > 3

    # JSON action extractor (buat T7)
    a = extract_json_action('{"action": "set_volume", "args": {"percent": 20}}')
    assert a == {"action": "set_volume", "args": {"percent": 20}}
    assert extract_json_action("baik saya kerjakan") is None
    assert extract_json_action('prefix {"action": "chat", "args": {"text": "halo"}}') is not None

    print("T4 OK: mock stream + JSON extractor berfungsi")


if __name__ == "__main__":
    asyncio.run(main())
