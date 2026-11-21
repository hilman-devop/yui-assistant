"""Agent: routing respons LLM -> tool kontrol PC.
Dua mode:
- native: function calling OpenAI (butuh RouterLlm.stream_events, divalidasi T10)
- fallback: protokol JSON-di-prompt (dipakai MockLlm & model tanpa tool_calls)
Konfirmasi: aksi berisiko (lock/sleep) ditahan sebagai pending sampai user bilang ya/tidak.
"""
import asyncio
from collections.abc import AsyncIterator

from core.llm import extract_json_action
from tools.registry import announce_of, dispatch, names, needs_confirm, schemas

_YES = {"ya", "iya", "ok", "oke", "lanjut", "gas", "yes", "yakin", "lanjutkan", "boleh"}
_NO = {"tidak", "batal", "jangan", "ga", "gak", "nggak", "no", "stop"}


def _fallback_instruction() -> str:
    from tools.registry import _REGISTRY
    katalog = "\n".join(f"- {n}: {v['schema']['function']['description']}" for n, v in _REGISTRY.items())
    return (
        "\n\nKamu bisa mengontrol laptop lewat aksi berikut:\n" + katalog +
        "\nKalau user meminta salah satu aksi itu, balas HANYA satu baris JSON: "
        '{"action": "<nama>", "args": {...}} — tanpa teks lain. '
        "Untuk obrolan biasa, balas normal Bahasa Indonesia tanpa JSON.")


class Agent:
    def __init__(self, llm):
        self.llm = llm
        self.native = llm.supports_native_tools()
        self.pending: tuple[str, dict] | None = None  # (tool, args) menunggu konfirmasi

    async def probe(self) -> None:
        """Uji sekali apakah model beneran mengembalikan tool_calls.
        Kalau tidak -> turun ke mode fallback JSON-prompt. Dipanggil saat startup."""
        if not self.native:
            return
        from tools.registry import schemas
        try:
            async for ev in self.llm.stream_events(
                    [{"role": "user", "content": "atur volume ke 20"}], schemas()):
                if ev["type"] == "tool_calls" and ev["data"]:
                    print("[agent] native tool_calls aktif")
                    return
            self.native = False
            print("[agent] model tidak mengembalikan tool_calls -> fallback JSON-prompt")
        except Exception as e:
            self.native = False
            print(f"[agent] probe gagal ({type(e).__name__}) -> fallback JSON-prompt")

    async def respond(self, messages: list[dict]) -> AsyncIterator[str]:
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        user_l = user.strip().lower().rstrip(".!?")
        if self.pending:
            print(f"[agent] jawaban konfirmasi: '{user_l}' (pending: {self.pending[0]})")
            kata = set(user_l.split())
            if kata & _YES:
                name, args = self.pending
                self.pending = None
                yield "Oke. " + await asyncio.to_thread(dispatch, name, args)
                return
            if kata & _NO:
                self.pending = None
                yield "Baik, dibatalkan."
                return
            yield "Aku masih menunggu konfirmasi. Ya atau tidak?"
            return
        if self.native:
            async for d in self._native(messages):
                yield d
        else:
            async for d in self._fallback(messages):
                yield d

    async def _run_action(self, act: dict) -> AsyncIterator[str]:
        name, args = act.get("action", ""), act.get("args") or {}
        if name == "chat":
            yield str(args.get("text", ""))
            return
        if name not in names():
            yield f"Maaf, aku tidak bisa {name}."
            return
        print(f"[agent] tool: {name}({args})")
        if info := announce_of(name):
            yield info  # kabar dulu sebelum tool lama jalan (mis. browser_task)
        if needs_confirm(name):
            self.pending = (name, args)
            yield f"Aku akan {name.replace('_', ' ')}. Yakin mau aku lanjutkan?"
            return
        hasil = await asyncio.to_thread(dispatch, name, args)
        print(f"[agent]   -> {hasil}")
        yield hasil

    async def _fallback(self, messages: list[dict]) -> AsyncIterator[str]:
        msgs = [dict(messages[0], content=messages[0]["content"] + _fallback_instruction()),
                *messages[1:]]
        buf, decided, is_json = "", False, False
        async for d in self.llm.stream(msgs):
            if not decided:
                buf += d
                s = buf.lstrip()
                if s.startswith("{"):
                    decided, is_json = True, True
                elif s:
                    decided = True
                    yield buf
                    buf = ""
            elif is_json:
                buf += d
            else:
                yield d
        if is_json:
            act = extract_json_action(buf)
            if act is None:
                yield buf
            else:
                async for out in self._run_action(act):
                    yield out
        elif buf:
            yield buf

    async def _native(self, messages: list[dict]) -> AsyncIterator[str]:
        tool_calls = None
        async for ev in self.llm.stream_events(messages, schemas()):
            if ev["type"] == "text":
                yield ev["data"]
            else:
                tool_calls = ev["data"]
        for tc in tool_calls or []:
            async for out in self._run_action({"action": tc["name"], "args": tc["args"]}):
                yield out
        # ponytail: hasil tool tidak dirangkum LLM lagi (hemat 1 RTT); string hasil sudah natural.
