"""Self-check E2E: LLM real (Groq direct + failover chain) + agent + tools + pipeline (TTS palsu).
export $(grep -v '^#' .env | xargs), lalu: .venv\Scripts\python tests\check_e2e.py
"""
import asyncio
import os
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # voice_lang ja -> teks Jepang

from core.agent import Agent
from core.llm import build_llm
from core.pipeline import Pipeline
from memory.store import Memory
from tools.registry import dispatch
import tools  # noqa: F401


class FakePlayer:
    amplitude = 0.0

    def reset(self): pass
    def stop(self): pass


class FakeTts:
    def __init__(self):
        self.spoken = []
        self.player = FakePlayer()

    async def speak(self, text):
        self.spoken.append(text)

    def stop(self): pass


async def main() -> None:
    assert os.environ.get("YUI_API_KEY"), "env YUI_API_KEY belum diisi"
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    llm = build_llm(cfg["llm"])
    agent = Agent(llm)
    await agent.probe()
    assert agent.native, "native tool_calls harus aktif di model ini"

    tts = FakeTts()
    mem = Memory("tests/assets/e2e.db", "tests/assets/e2e_facts.json")
    pipe = Pipeline(cfg, llm, tts=tts, memory=mem)
    pipe.respond = agent.respond

    v0 = int(dispatch("get_volume").split()[2])

    # perintah aksi beneran
    t0 = time.perf_counter()
    await pipe._respond_and_speak("tolong atur volume laptop ke 20 persen", time.perf_counter())
    dur = time.perf_counter() - t0
    v1 = int(dispatch("get_volume").split()[2])
    print(f"[aksi] {dur:.1f}s | volume {v0}->{v1} | diucapkan: {tts.spoken}")
    assert v1 == 20, "LLM real gagal memicu set_volume"
    dispatch("set_volume", {"percent": v0})

    # obrolan biasa
    tts.spoken.clear()
    await pipe._respond_and_speak("halo Yui, kamu lagi apa?", time.perf_counter())
    teks = " ".join(tts.spoken)
    print(f"[chat] diucapkan: '{teks[:90]}'")
    assert teks.strip() and not teks.strip().startswith("{"), "chat harus teks natural"

    # riwayat tersimpan
    assert len(mem.recent(10)) >= 4

    print("E2E OK: LLM real + tools + pipeline berfungsi")


if __name__ == "__main__":
    asyncio.run(main())
