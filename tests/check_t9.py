"""Self-check T9: memori persisten — restart pipeline, konteks tetap ingat.
Run: .venv\\Scripts\\python tests\\check_t9.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm import MockLlm
from core.pipeline import Pipeline
from memory.store import Memory, get_memory
from tools.registry import dispatch
import tools  # noqa: F401  (registrasi tool)


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
    tmp = Path(tempfile.mkdtemp())
    db, facts = str(tmp / "m.db"), str(tmp / "facts.json")

    # unit dasar
    m = Memory(db, facts)
    m.add_turn("user", "halo")
    m.add_turn("assistant", "halo juga")
    assert [t["role"] for t in m.recent(10)] == ["user", "assistant"]
    assert m.fact_text() == ""
    m.set_fact("nama_user", "Bos")
    assert "Bos" in m.fact_text() and "nama_user" in m.fact_text()
    print("unit Memory OK")

    # pipeline "restart": instance baru, db sama -> konteks masih ada
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    get_memory({"memory": {"db_path": db, "facts_path": facts}})  # init singleton ke tmp

    p1 = Pipeline(cfg, MockLlm(delay=0.001), tts=FakeTts(), memory=Memory(db, facts))
    await p1._respond_and_speak("halo Yui", 0.0)
    p2 = Pipeline(cfg, MockLlm(delay=0.001), tts=FakeTts(), memory=Memory(db, facts))
    msgs = p2._messages("tes")
    isi = "\n".join(x["content"] for x in msgs)
    assert "halo Yui" in isi, "riwayat hilang setelah restart"
    assert "Bos" in msgs[0]["content"], "fakta tidak masuk system prompt"
    print("restart: riwayat + fakta masuk konteks OK")

    # tool remember_fact lewat dispatch
    assert "aku ingat" in dispatch("remember_fact", {"key": "minuman", "value": "kopi"})
    assert "kopi" in Memory(db, facts).fact_text()
    print("tool remember_fact OK")

    print("T9 OK: memori persisten berfungsi")


if __name__ == "__main__":
    asyncio.run(main())
