"""LLM: OpenAI-compatible client -> 9Router (http://localhost:20128/v1).
Tanpa API key -> MockLlm (respons kalengan) supaya pipeline bisa dites end-to-end.
"""
import asyncio
import json
import os
from collections.abc import AsyncIterator

SYSTEM_PROMPT = """Kamu adalah Yui, asisten AI pribadi di laptop pengguna.
Selalu jawab dalam Bahasa Indonesia yang natural, santai tapi sopan (seperti asisten setia, bukan robot kaku).
SELALU panggil pengguna "Tuanku" di setiap jawaban.
Jawaban HARUS singkat dan to-the-point karena akan diucapkan lewat suara — maksimal 2-3 kalimat kecuali diminta detail.
Jangan gunakan markdown, emoji, atau format yang aneh dibaca keras.
Kamu bisa mengontrol laptop pengguna lewat tools yang tersedia. Kalau diminta melakukan aksi, gunakan tool, lalu konfirmasi singkat hasilnya.
PENTING: untuk sapaan atau obrolan biasa (halo, terima kasih, kabar), jawab natural TANPA memanggil tool apa pun — walau di riwayat ada perintah aksi sebelumnya.
PENTING urusan web: "putar/setel lagu X" -> tool putar_lagu (instan, autoplay). Sekedar membuka situs/URL ("buka youtube") -> open_url (instan). browser_task HANYA untuk tugas yang butuh interaksi di halaman (klik, isi form, baca/ambil isi) — browser_task lambat (1-3 menit).
Untuk hitungan matematika SELALU pakai tool hitung (jangan mengarang hasil). Untuk mengoperasikan aplikasi yang sudah dibuka, lanjutkan dengan type_text/press_hotkey — jangan berhenti di open_app kalau permintaannya belum selesai.
Kalau perintah tidak jelas, tanya balik dengan singkat."""


class MockLlm:
    """LLM kalengan untuk testing tanpa API key.
    Keyword aksi -> balas JSON aksi (menguji jalur fallback JSON-prompt di agent)."""

    _MOCK_JSON = {
        "volume": '{"action": "set_volume", "args": {"percent": 20}}',
        "kunci": '{"action": "lock_pc"}',
        "buka": '{"action": "open_app", "args": {"name": "notepad"}}',
    }

    def __init__(self, delay: float = 0.03):
        self._delay = delay
        self.model = "mock"

    async def stream(self, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[str]:
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        user_l = user.lower()
        js = next((v for k, v in self._MOCK_JSON.items() if k in user_l), None)
        if js is not None:
            await asyncio.sleep(self._delay)
            yield js[:len(js) // 2]
            await asyncio.sleep(self._delay)
            yield js[len(js) // 2:]
            return
        reply = f"Baik, kamu bilang: {user}. Ada lagi yang bisa saya bantu?"
        for word in reply.split(" "):
            await asyncio.sleep(self._delay)
            yield word + " "

    def supports_native_tools(self) -> bool:
        return False


class RouterLlm:
    def __init__(self, base_url: str, api_key: str, model: str = "auto",
                 max_tokens: int = 512, temperature: float = 0.6):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=30.0)
        self._base_url = base_url
        self._model_cfg = model
        self.model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    async def resolve_model(self) -> str:
        """Kalau model='auto', ambil model pertama yang dilayani router."""
        if self._model_cfg != "auto":
            return self._model_cfg
        models = await self._client.models.list()
        assert models.data, "9Router tidak melayani model apapun"
        self.model = models.data[0].id
        return self.model

    async def stream(self, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[str]:
        kwargs: dict = dict(model=self.model, messages=messages, stream=True,
                            max_tokens=self._max_tokens, temperature=self._temperature)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = await self._client.chat.completions.create(**kwargs)
        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                # router (cf workers-ai) kadang kirim token angka sbg int, bukan str
                yield str(delta.content)

    def supports_native_tools(self) -> bool:
        return True  # divalidasi beneran di T10; fallback JSON-prompt ada di agent

    async def stream_events(self, messages: list[dict],
                            tools: list[dict] | None = None) -> AsyncIterator[dict]:
        """Streaming + akumulasi tool_calls. Yield {"type":"text","data":str}
        lalu {"type":"tool_calls","data":[{name,args,id}]} di akhir bila ada."""
        kwargs: dict = dict(model=self.model, messages=messages, stream=True,
                            max_tokens=self._max_tokens, temperature=self._temperature)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            response = await self._client.chat.completions.create(**kwargs)
            acc: dict[int, dict] = {}
            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    yield {"type": "text", "data": str(delta.content)}  # int guard: lihat stream()
                for tc in delta.tool_calls or []:
                    slot = acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] += tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments
            if acc:
                calls = []
                for slot in acc.values():
                    try:
                        args = json.loads(slot["args"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    calls.append({"name": slot["name"], "args": args, "id": slot["id"]})
                yield {"type": "tool_calls", "data": calls}
        except Exception as e:
            # Groq tool_use_failed (400 di create(), sebelum token apapun): model menghasilkan
            # tool_call rusak untuk obrolan biasa — ulangi sekali tanpa tools agar giliran tidak mati.
            if tools and "failed_generation" in str(e):
                print(f"[llm] tool_calls rusak -> ulangi tanpa tools")
                async for d in self.stream(messages):
                    yield {"type": "text", "data": d}
                return
            raise


class FailoverLlm:
    """Rantai RouterLlm: kena rate-limit/quota -> pindah endpoint cadangan berikutnya
    (permanen untuk sesi ini; quota harian memang tidak balik dalam hitungan menit)."""

    def __init__(self, llms: list):
        self._llms = llms
        self._i = 0

    @property
    def _cur(self):
        return self._llms[self._i]

    @property
    def model(self):
        return self._cur.model

    def supports_native_tools(self) -> bool:
        return True

    async def resolve_model(self) -> str:
        return await self._cur.resolve_model()

    @staticmethod
    def _limited(e: Exception) -> bool:
        s = str(e).lower()
        # 403/access denied: Groq kadang blokir per-IP (VPN/dsb) — tetap coba cadangan
        return any(k in s for k in ("429", "401", "403", "rate_limit", "quota", "tokens per day",
                                    "invalid_api_key", "access denied", "permissiondenied"))

    def _next(self) -> bool:
        if self._i + 1 >= len(self._llms):
            return False
        self._i += 1
        print(f"[llm] rate limit -> cadangan #{self._i + 1} ({self._cur.model})")
        return True

    # ponytail: retry mengulang stream dari awal; aman karena 429 praktis selalu
    # terjadi di create() sebelum token pertama, bukan di tengah stream.
    async def stream(self, messages: list[dict], tools: list[dict] | None = None) -> AsyncIterator[str]:
        while True:
            try:
                async for d in self._cur.stream(messages, tools):
                    yield d
                return
            except Exception as e:
                if self._limited(e) and self._next():
                    continue
                raise

    async def stream_events(self, messages: list[dict],
                            tools: list[dict] | None = None) -> AsyncIterator[dict]:
        while True:
            try:
                async for ev in self._cur.stream_events(messages, tools):
                    yield ev
                return
            except Exception as e:
                if self._limited(e) and self._next():
                    continue
                raise


def build_llm(cfg: dict):
    """Factory: rantai failover kalau ada 'endpoints'; Router tunggal kalau tidak; Mock kalau tanpa key."""
    if cfg.get("endpoints"):
        llms = []
        for ep in cfg["endpoints"]:
            key = os.environ.get(ep.get("api_key_env", ""), "") or ep.get("api_key", "")
            if not key:
                print(f"[llm] endpoint {ep['base_url']} tanpa key -> dilewati")
                continue
            llms.append(RouterLlm(ep["base_url"], key, ep.get("model") or cfg.get("model", "auto"),
                                  cfg.get("max_tokens", 512), cfg.get("temperature", 0.6)))
        if llms:
            print(f"[llm] failover: {len(llms)} endpoint siap")
            return llms[0] if len(llms) == 1 else FailoverLlm(llms)
        print("[llm] semua endpoint tanpa key -> mode MOCK")
        return MockLlm()
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        print(f"[llm] env {cfg['api_key_env']} kosong -> mode MOCK (respons kalengan)")
        return MockLlm()
    return RouterLlm(cfg["base_url"], api_key, cfg.get("model", "auto"),
                     cfg.get("max_tokens", 512), cfg.get("temperature", 0.6))


def extract_json_action(text: str) -> dict | None:
    """Fallback protokol JSON-prompt (T7): LLM membalas murni JSON aksi.
    Format: {"action": "<tool>", "args": {...}} atau {"action": "chat", "args": {"text": ...}}"""
    text = text.strip()
    if not text.startswith("{"):
        m = text.find("{")
        if m == -1:
            return None
        text = text[m:]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and "action" in obj:
        return obj
    return None
