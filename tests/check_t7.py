"""Self-check T7: tool routing — fallback JSON (mock) + native (stub) + konfirmasi.
Run: .venv\\Scripts\\python tests\\check_t7.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent import Agent
from core.llm import MockLlm
from tools import registry
from tools.registry import _REGISTRY, dispatch

MSGS = lambda u: [{"role": "system", "content": "kamu Yui"}, {"role": "user", "content": u}]


class FakeNativeLlm:
    """Stub jalur native: mengeluarkan tool_calls seperti RouterLlm.stream_events."""

    def __init__(self, calls):
        self._calls = calls

    def supports_native_tools(self):
        return True

    async def stream_events(self, messages, tools=None):
        yield {"type": "tool_calls", "data": self._calls}


async def kumpul(agent, teks):
    return "".join([d async for d in agent.respond(MSGS(teks))])


async def main() -> None:
    # stub lock_pc supaya PC tidak beneran terkunci saat tes
    asli = _REGISTRY["lock_pc"]["fn"]
    _REGISTRY["lock_pc"]["fn"] = lambda: "Layar dikunci (pura-pura)."

    # --- jalur fallback (MockLlm -> JSON prompt) ---
    agent = Agent(MockLlm(delay=0.001))
    assert not agent.native

    v0 = int(dispatch("get_volume").split()[2])
    out = await kumpul(agent, "Yui, kecilin volume dong")
    v1 = int(dispatch("get_volume").split()[2])
    print(f"fallback aksi: '{out}' | volume {v0}->{v1}")
    assert v1 == 20, "set_volume tidak dieksekusi lewat JSON fallback"
    dispatch("set_volume", {"percent": v0})  # restore

    # konfirmasi aksi berisiko: kunci -> ya -> batal
    out = await kumpul(agent, "Yui, kunci laptop")
    assert "Yakin" in out and agent.pending and agent.pending[0] == "lock_pc", out
    out = await kumpul(agent, "ya")
    assert "pura-pura" in out and agent.pending is None, out
    out = await kumpul(agent, "Yui, kunci laptop")
    out = await kumpul(agent, "jangan")
    assert "dibatalkan" in out and agent.pending is None, out
    print("konfirmasi ya/tidak OK")

    # chat biasa tidak kena JSON
    out = await kumpul(agent, "halo apa kabar")
    assert "apa kabar" in out and not out.strip().startswith("{"), out

    # --- jalur native (stub tool_calls) ---
    agent2 = Agent(FakeNativeLlm([{"name": "set_volume", "args": {"percent": 55}, "id": "x"}]))
    out = await kumpul(agent2, "atur volume 55")
    v2 = int(dispatch("get_volume").split()[2])
    print(f"native aksi: '{out}' | volume -> {v2}")
    assert v2 == 55 and "55 persen" in out
    dispatch("set_volume", {"percent": v0})  # restore

    agent3 = Agent(FakeNativeLlm([{"name": "lock_pc", "args": {}, "id": "y"}]))
    out = await kumpul(agent3, "kunci")
    assert "Yakin" in out and agent3.pending is not None

    _REGISTRY["lock_pc"]["fn"] = asli  # kembalikan
    print("T7 OK: fallback + native + konfirmasi berfungsi")


if __name__ == "__main__":
    asyncio.run(main())
