"""Benchmark semua kandidat LLM: Groq direct (GROQ_API_KEY) vs 9Router (YUI_API_KEY).
Ukur TTFT streaming 2x + tool_calls streaming (jalur produksi). Kriteria: cepat & tools jalan."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm import RouterLlm
from tools.registry import schemas

GROQ = ("https://api.groq.com/openai/v1", "GROQ_API_KEY")
ROUTER = ("http://localhost:20128/v1", "YUI_API_KEY")

KANDIDAT = [
    ("groq-direct", GROQ, "llama-3.1-8b-instant"),
    ("groq-direct", GROQ, "llama-3.3-70b-versatile"),
    ("groq-direct", GROQ, "openai/gpt-oss-20b"),
    ("groq-direct", GROQ, "openai/gpt-oss-120b"),
    ("groq-direct", GROQ, "qwen/qwen3.6-27b"),
    ("9router", ROUTER, "groq/llama-3.1-8b-instant"),
    ("9router", ROUTER, "groq/llama-3.3-70b-versatile"),
    ("9router", ROUTER, "cf/@cf/meta/llama-3.1-8b-instruct-fp8-fast"),  # baseline saat ini
]


async def satu(src: str, ep, mid: str) -> None:
    url, key_env = ep
    llm = RouterLlm(url, os.environ[key_env], mid, 128, 0.6)
    ttfts = []
    try:
        for _ in range(2):
            t0 = time.perf_counter()
            async for _ in llm.stream([{"role": "user", "content": "hai"}]):
                break
            ttfts.append((time.perf_counter() - t0) * 1000)
    except Exception as e:
        print(f"{src:11s} {mid:45s} TTFT GAGAL {type(e).__name__} {str(e)[:80]}")
        return
    hasil = "TIDAK"
    try:
        async for ev in llm.stream_events([{"role": "user", "content": "atur volume ke 20"}], schemas()):
            if ev["type"] == "tool_calls" and ev["data"]:
                hasil = ev["data"][0]["name"]
                break
    except Exception as e:
        hasil = f"GAGAL {type(e).__name__} {str(e)[:60]}"
    print(f"{src:11s} {mid:45s} TTFT {ttfts[0]:5.0f}/{ttfts[1]:5.0f}ms | tools -> {hasil}")


async def main() -> None:
    for src, ep, mid in KANDIDAT:
        await satu(src, ep, mid)


if __name__ == "__main__":
    asyncio.run(main())
