"""TTS: edge-tts (online, suara ID natural) -> PCM -> player yang bisa distop instan.
Fallback offline: pyttsx3/SAPI kalau edge-tts gagal.
Granularitas per-kalimat: TTS kalimat pertama bunyi sebelum LLM selesai ngetik (di T5).
"""
import asyncio
import queue
import re
import threading

import os

import httpx
import numpy as np
import sounddevice as sd

import edge_tts

from core.audio_util import decode_to_pcm

_EDGE_RATE = 24000  # output default edge-tts: audio-24khz mono mp3


def split_sentences(text: str) -> list[str]:
    """Pecah teks jadi kalimat-kalimat untuk TTS streaming."""
    parts = re.split(r"(?<=[.!?;:\n])\s+", text.strip())
    return [p for p in parts if p and p.strip()]


class Player:
    """Playback PCM float32 lewat sounddevice; stop() menghentikan seketika."""

    def __init__(self) -> None:
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self.amplitude = 0.0  # RMS chunk terakhir — untuk lip-sync avatar (T8)

    def play(self, pcm: np.ndarray, rate: int) -> None:
        """Blocking sampai selesai atau distop(). Flag stop TIDAK direset di sini
        (hindari race: stop() yang datang sebelum play() tidak boleh di-clear)."""
        if self._stopped.is_set():
            return
        with self._lock:
            self._stream = sd.OutputStream(samplerate=rate, channels=1, dtype="float32")
            self._stream.start()
        try:
            for i in range(0, len(pcm), 2048):
                if self._stopped.is_set():
                    break
                chunk = pcm[i:i + 2048]
                self.amplitude = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
                try:
                    self._stream.write(chunk)
                except sd.PortAudioError:
                    if self._stopped.is_set():
                        break
                    raise
        finally:
            self.amplitude = 0.0
            with self._lock:
                if self._stream is not None:
                    self._stream.stop()
                    self._stream.close()
                    self._stream = None

    def reset(self) -> None:
        """Panggil sekali saat mulai siklus bicara BARU (bukan per kalimat)."""
        self._stopped.clear()

    def stop(self) -> None:
        self._stopped.set()
        with self._lock:
            if self._stream is not None:
                self._stream.abort(ignore_errors=True)


class Tts:
    def __init__(self, voice: str = "id-ID-GadisNeural", rate: str = "+10%", pitch: str = "+0Hz"):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch  # pitch lebih tinggi = suara lebih muda (mis. "+30Hz")
        self.player = Player()

    async def synth(self, text: str) -> bytes:
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch)
        return b"".join([c["data"] async for c in communicate.stream() if c["type"] == "audio"])

    async def speak(self, text: str) -> None:
        """Synth satu kalimat -> mainkan (blocking, bisa distop lewat player.stop())."""
        try:
            mp3 = await self.synth(text)
            pcm, rate = decode_to_pcm(mp3, _EDGE_RATE)
        except Exception:
            # fallback SAPI via thread — sync, jangan blokir event loop;
            # ponytail: SAPI tetap tidak bisa distop mid-kalimat
            await asyncio.to_thread(self._speak_offline, text)
            return
        await asyncio.to_thread(self.player.play, pcm, rate)

    def _speak_offline(self, text: str) -> None:
        import pyttsx3
        engine = pyttsx3.init()
        for v in engine.getProperty("voices"):  # cari suara Indonesia kalau ada
            if "indonesia" in v.name.lower() or "id-ID" in v.id:
                engine.setProperty("voice", v.id)
                break
        engine.say(text)
        engine.runAndWait()
        engine.stop()

    def stop(self) -> None:
        self.player.stop()


class FishTts:
    """TTS Fish Audio cloud (natural, support ID+JA). Model GRATIS 's2.1-pro-free' — wajib lewat
    HEADER 'model' (tanpa header -> fallback s2.1-pro berbayar -> 402). reference_id = suara
    library/clone di fish.audio; kosong = suara default. Fallback edge-tts kalau gagal/402."""

    def __init__(self, api_keys: list[str], reference_id: str = "", fallback: Tts | None = None):
        self._keys = api_keys  # failover berurutan kalau kena limit (fair-use free model)
        self._ki = 0
        self._ref = reference_id
        self._http: httpx.AsyncClient | None = None  # persistent — handshake TLS cuma sekali per sesi
        self._loop = None  # client terikat event loop pembuatnya (asyncio.run ganda di test = loop baru)
        self.player = Player()
        self._fallback = fallback or Tts()
        self._dead = False

    async def _post(self, text: str, fmt: str) -> bytes | None:
        """Satu panggilan synth (dengan failover key). None = gagal (caller putuskan fallback)."""
        while not self._dead:
            try:
                body = {"text": text, "format": fmt, "latency": "balanced"}
                if self._ref:
                    body["reference_id"] = self._ref
                if self._http is None or self._loop is not asyncio.get_running_loop():
                    self._http = httpx.AsyncClient(timeout=30)  # ponytail: tak di-close; seumur loop
                    self._loop = asyncio.get_running_loop()
                r = await self._http.post("https://api.fish.audio/v1/tts",
                                          headers={"Authorization": f"Bearer {self._keys[self._ki]}",
                                                   "model": "s2.1-pro-free"},
                                          json=body)
                if r.status_code == 200:
                    return r.content
                if r.status_code in (401, 402, 429):
                    self._ki += 1
                    if self._ki >= len(self._keys):
                        self._dead = True
                        print("[tts] Fish limit semua key -> fallback edge-tts untuk sesi ini")
                    else:
                        print(f"[tts] fish limit -> key cadangan #{self._ki + 1}")
                else:
                    print(f"[tts] Fish {r.status_code}: {r.text[:120]}")
                    break
            except httpx.HTTPError as e:
                print(f"[tts] Fish gagal: {e}")
                break
        return None

    async def synth(self, text: str) -> bytes:
        return await self._post(text, "mp3") or await self._fallback.synth(text)

    async def synth_ogg(self, text: str) -> bytes:
        """OGG/Opus untuk voice note WA (Fish mengembalikan kontainer Ogg asli). b'' = gagal."""
        return await self._post(text, "opus") or b''

    def set_voice(self, reference_id: str) -> None:
        """Ganti suara saat runtime (suara per karakter)."""
        if reference_id != self._ref:
            self._ref = reference_id
            print(f"[tts] suara -> {reference_id[:8]}...")

    async def speak(self, text: str) -> None:
        mp3 = await self.synth(text)  # synth tidak pernah raise (fallback internal)
        pcm, rate = decode_to_pcm(mp3, _EDGE_RATE)
        await asyncio.to_thread(self.player.play, pcm, rate)

    def stop(self) -> None:
        self.player.stop()


def build_tts(cfg: dict):
    """Factory: Fish Audio kalau backend=fish + key ada; selain itu edge-tts."""
    t = cfg["tts"]
    edge = Tts(t["voice"], t["rate"], t.get("pitch", "+0Hz"))
    if t.get("backend") == "fish":
        keys = [os.environ.get(k) for k in ("FISH_API_KEY", "FISH_API_KEY_2", "FISH_API_KEY_3")]
        keys = [k for k in keys if k]
        if keys:
            print(f"[tts] Fish Audio ({len(keys)} key, ref: {t.get('fish_voice_id') or 'default'}) — fallback edge-tts")
            return FishTts(keys, t.get("fish_voice_id", ""), fallback=edge)
    return edge


class SentenceSpeaker:
    """Antre kalimat dari LLM stream, synth+play berurutan di background.
    Pipeline (T5) memanggil feed() per kalimat; close() saat LLM selesai."""

    def __init__(self, tts: Tts):
        self._tts = tts
        self._q: queue.Queue[str | None] = queue.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._tts.player.reset()  # siklus bicara baru = buka flag stop
        self._task = asyncio.create_task(self._run())

    def feed(self, sentence: str) -> None:
        self._q.put(sentence)

    async def _run(self) -> None:
        while True:
            sentence = await asyncio.to_thread(self._q.get)
            if sentence is None:
                return
            await self._tts.speak(sentence)

    async def wait_done(self) -> None:
        self._q.put(None)
        if self._task:
            await self._task

    def stop(self) -> None:
        self._tts.stop()
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
