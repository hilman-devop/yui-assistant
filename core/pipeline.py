"""Pipeline utama Yui.
mic -> VAD -> ASR(id) -> wake-word "yui" (posisi bebas) -> LLM stream -> TTS per kalimat.
Interrupt: (1) hotkey, (2) barge-in "yui, stop" saat Yui bicara,
(3) echo self-filter: transkrip yang cocok kalimat Yui sendiri dibuang.
"""
import asyncio
import queue
import random
import re
import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd

from core.asr import build_asr
from core.llm import SYSTEM_PROMPT
from core.tts import SentenceSpeaker, Tts, build_tts
from core.vad import WINDOW, Vad
from memory.store import Memory, get_memory

WAKE_VARIANTS = ("yui", "yuy", "yuyy", "yuyi")
STOP_WORDS = {"stop", "berhenti", "diam", "cukup", "sudah", "stopppp"}
# Suara = Jepang (karakter anime); WA tetap Indonesia (prompt WA tidak berubah).
VOICE_LANG_RULE = ("\nPENTING — ATURAN INI MENIMPA aturan bahasa lain di atas: kamu sedang menjawab "
                   "lewat SUARA dengan suara karakter anime Jepang. SELURUH jawabanmu HARUS 100% dalam "
                   "bahasa Jepang kasual yang imut dan pendek (1-3 kalimat), MESKIPUN user berbicara "
                   "bahasa Indonesia. Dilarang satu kata pun bahasa Indonesia/Inggris. Tanpa markdown. "
                   "SELALU panggil user 'ご主人様' (goshujin-sama) di setiap jawaban.")
# Sahutan saat dipanggil 'Yui' tanpa perintah (acak, tanpa LLM = instan + pasti bervariasi).
SAHUTAN = ("はい、ご主人様！", "なんですか、ご主人様？", "お呼びですか、ご主人様？",
           "はーい、ご主人様。何しましょう？", "ご用件は何ですか、ご主人様？", "なになに、ご主人様？")
TUNGGU_PERINTAH_S = 15   # setelah disahut, ucapan berikutnya (tanpa wake-word) = perintah
TUNGGU_LANJUTAN_S = 10   # setelah Yui menjawab, jendela lanjutan obrolan tanpa panggil ulang
_SENT_END = re.compile(r"[.!?;\n]|(?<!\d):")  # ':' bukan akhir kalimat kalau habis angka (jam 10:30)


def _is_echo(cmd: str, spoken: str) -> bool:
    """Perintah hasil dengar-ulang suara Yui sendiri: semua katanya memang sedang diucapkan.
    Dipakai saat state=speaking — wake-word di echo berasal dari salah dengar (misal 'yuk'->'yui')."""
    a = set(re.findall(r"\w+", cmd.lower()))
    if len(a) < 2:
        return False  # perintah 1 kata ("stop", "lanjut") = interaksi asli, jangan pernah dibuang
    b = set(re.findall(r"\w+", spoken.lower()))
    return a <= b


def extract_command(text: str, prefix: str = "yui") -> str | None:
    """Kembalikan perintah tanpa wake-word, '' kalau dipanggil tanpa perintah,
    None kalau tidak ada wake-word. Wake-word boleh di posisi mana pun (kata utuh):
    'yui, kecilin volume' -> 'kecilin volume'; 'halo yui' -> 'halo'."""
    t = text.strip().lower()
    if not t:
        return None
    variants = sorted({prefix, *WAKE_VARIANTS}, key=len, reverse=True)
    m = re.search(r"\b(?:" + "|".join(variants) + r")\b", t)
    if not m:
        return None
    after = t[m.end():].strip(" .,!?")
    if after:
        return after
    return t[:m.start()].strip(" .,!?")  # wake-word di akhir: perintah = teks sebelumnya


class Pipeline:
    def __init__(self, cfg: dict, llm, asr=None, tts: Tts | None = None,
                 memory: Memory | None = None):
        self.cfg = cfg
        _vad_model = Path(__file__).resolve().parent.parent / "models" / "silero_vad.onnx"
        self.vad = Vad(str(_vad_model), cfg["vad"]["threshold"])  # absolut — jalan dari cwd mana pun
        self.asr = asr or build_asr(cfg)
        self.tts = tts or build_tts(cfg)
        self.llm = llm
        self.memory = memory or get_memory(cfg)
        self.state = "idle"          # idle | processing | speaking | paused
        self.paused = False          # mode diam: mic tetap jalan tapi ucapan diabaikan (F11)
        self.on_state = None         # hook untuk avatar (T8): fn(state:str, amplitude:float)
        self.respond = None          # diganti tools layer di T7; default llm.stream
        self._mic_q: queue.Queue = queue.Queue()
        self._speaker: SentenceSpeaker | None = None
        self._utter_task: asyncio.Task | None = None
        self._asr_lock = asyncio.Lock()  # transkripsi diserialkan — CPU tidak rebutan
        self.latency_ms = 0.0        # selesai bicara -> audio pertama, untuk dipantau
        self._spoken_recent: deque[str] = deque(maxlen=4)  # kalimat Yui terkini — deteksi echo
        self._await_until = 0.0        # > monotonic(): tunggu perintah (sahutan) / lanjutan obrolan

    # ---------- state & interrupt ----------

    def _set_state(self, s: str) -> None:
        self.state = s
        if self.on_state:
            self.on_state(s, 0.0)

    def stop_speaking(self) -> None:
        """Hentikan respons yang sedang berjalan (hotkey/barge-in)."""
        if self._speaker:
            self._speaker.stop()
        self.tts.stop()
        if self._utter_task and not self._utter_task.done():
            self._utter_task.cancel()
        self._set_state("idle")

    def toggle_pause(self) -> bool:
        """Mode diam: berhenti total (bicara + proses mic). Balik = mendengarkan lagi."""
        self.paused = not self.paused
        if self.paused:
            self.stop_speaking()
            self._set_state("paused")
            print("[yui] DIAM — ucapan diabaikan (F11 lanjut)")
        else:
            self._set_state("idle")
            print("[yui] mendengarkan lagi")
        return self.paused

    # ---------- loop mic ----------

    def _open_mic(self) -> None:
        def cb(indata, frames, t, status):
            self._mic_q.put(indata[:, 0].copy())
        self._mic = sd.InputStream(samplerate=self.cfg["audio"]["sample_rate"], channels=1,
                                   dtype="float32", blocksize=WINDOW, callback=cb)
        self._mic.start()

    async def run(self) -> None:
        self._open_mic()
        vcfg = self.cfg["vad"]
        speech: list[np.ndarray] = []
        in_speech = False
        silent_ms = 0
        self._set_state("idle")
        print("[yui] mendengarkan... panggil 'Yui, ...' (Ctrl+C untuk keluar)")
        max_ms = vcfg.get("max_utterance_ms", 12000)
        while True:
            chunk = await asyncio.to_thread(self._mic_q.get)
            if self.paused:
                speech, in_speech, silent_ms = [], False, 0  # kuras antrean, jangan proses
                continue
            thr = vcfg["speaking_threshold"] if self.state == "speaking" else vcfg["threshold"]
            if self.vad.is_speech(chunk, thr):
                if not in_speech:
                    print("[yui] mendengar suara...")
                speech.append(chunk)
                in_speech = True
                silent_ms = 0
            elif in_speech:
                speech.append(chunk)
                silent_ms += 32
            dur_ms = len(speech) * 32
            if in_speech and (silent_ms >= vcfg["min_silence_ms"] or dur_ms >= max_ms):
                if dur_ms >= max_ms:
                    print(f"[yui] ucapan dipotong di {dur_ms//1000}s (maks {max_ms//1000}s)")
                pcm = np.concatenate(speech)
                speech, in_speech, silent_ms = [], False, 0
                if len(pcm) * 1000 // 16000 >= vcfg["min_speech_ms"]:
                    self._utter_task = asyncio.create_task(self.handle_utterance(pcm))

    # ---------- per ucapan ----------

    async def handle_utterance(self, pcm: np.ndarray) -> None:
        t0 = time.perf_counter()
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        if rms < 0.01:
            # noise pelan (kipas, angin) — whisper menghalusinasi di audio seperti ini;
            # lewati ASR = hemat panggilan API. Naikkan ambang kalau suara lirih ikut terpotong.
            print(f"[yui] audio pelan (rms {rms:.3f}) — noise, ASR dilewati")
            return
        async with self._asr_lock:
            text = await asyncio.to_thread(self.asr.transcribe, pcm)  # single-pass: dual-pass tiny+base = 2x waktu ASR
        if not text or text.strip() in (".", "..", "..."):
            return  # hening/noise — whisper kadang halusinasi "..." di audio senyap
        print(f"[yui] dengar: '{text}' (ASR {time.perf_counter()-t0:.2f}s)")
        cmd = extract_command(text, self.cfg["wake"]["prefix"])
        if cmd is None:
            if time.monotonic() < self._await_until and self.state != "speaking":
                cmd = text.strip(" .,!?")  # lanjutan: user menjawab sahutan Yui
                print(f"[yui]   -> perintah (lanjutan): '{cmd}'")
            else:
                print("[yui]   -> bukan buat Yui, diabaikan")
                return
        self._await_until = 0.0
        if not cmd:  # dipanggil 'Yui' doang -> sahut dulu, perintah menyusul
            self._await_until = time.monotonic() + TUNGGU_PERINTAH_S
            await self._sahut(t0)
            return
        if self.state == "speaking" and any(_is_echo(cmd, s) for s in self._spoken_recent):
            print(f"[yui]   -> echo suara sendiri, diabaikan: '{text}'")
            return  # ponytail: hanya aktif saat speaking; echo yang mendarat tepat setelah selesai lolos
        print(f"[yui]   -> perintah: '{cmd}'")

        if self.state == "speaking":
            self.stop_speaking()  # barge-in: perintah baru memotong respons lama
        if cmd.lower() in STOP_WORDS:
            self.stop_speaking()
            return
        try:
            await self._respond_and_speak(cmd, t0)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[yui] error: {e}")
            self._set_state("idle")
            try:  # kabari lewat suara — kegagalan total jangan diam saja
                self.tts.player.reset()
                await self.tts.speak("ごめんなさい、ご主人様。頭の回線が混んでいます。少ししてからもう一度お願いします。")
            except Exception:
                pass

    async def _sahut(self, t0: float) -> None:
        """Jawab panggilan polos (acak, langsung TTS tanpa LLM). Tidak dicatat ke memori."""
        teks = random.choice(SAHUTAN)
        print(f"[yui] bilang: {teks}")
        self._spoken_recent.append(teks)
        self.tts.player.reset()  # buka flag stop (siklus bicara baru — sama seperti SentenceSpeaker)
        self._set_state("speaking")
        self.latency_ms = (time.perf_counter() - t0) * 1000
        await self.tts.speak(teks)
        self._set_state("idle")

    async def say(self, text: str) -> None:
        """Ucapkan teks apa adanya lewat speaker (diminta via WA/tool `katakan`)."""
        print(f"[yui] bilang (diminta): {text}")
        self._spoken_recent.append(text)
        self.tts.player.reset()  # tanpa ini, play() batal kalau pernah kena stop sebelumnya
        self._set_state("speaking")
        await self.tts.speak(text)
        self._set_state("idle")

    def _messages(self, cmd: str) -> list[dict]:
        turns = self.cfg["memory"]["history_turns"]
        lang_rule = VOICE_LANG_RULE if self.cfg.get("voice_lang") == "ja" else ""
        return [{"role": "system", "content": SYSTEM_PROMPT + self.memory.fact_text() + lang_rule},
                *self.memory.recent(turns), {"role": "user", "content": cmd or "halo"}]

    async def _respond_and_speak(self, cmd: str, t0: float) -> None:
        self._set_state("processing")
        self._speaker = SentenceSpeaker(self.tts)
        self._speaker.start()
        respond = self.respond or self.llm.stream
        buf, full, first_audio = "", "", False
        async for delta in respond(self._messages(cmd)):
            buf += delta
            full += delta
            while (m := _SENT_END.search(buf)):
                sent, buf = buf[:m.end()].strip(), buf[m.end():]
                if sent:
                    if not first_audio:
                        self._set_state("speaking")
                        self.latency_ms = (time.perf_counter() - t0) * 1000
                        print(f"[yui] latensi: {self.latency_ms:.0f}ms")
                        first_audio = True
                    print(f"[yui] bilang: {sent}")
                    self._spoken_recent.append(sent)
                    self._speaker.feed(sent)
        if buf.strip():
            print(f"[yui] bilang: {buf.strip()}")
            self._spoken_recent.append(buf.strip())
            self._speaker.feed(buf.strip())
        self.memory.add_turn("user", cmd)
        self.memory.add_turn("assistant", full.strip())
        await self._speaker.wait_done()
        self._set_state("idle")
        # jendela lanjutan: user boleh langsung nyaut tanpa manggil 'Yui' lagi
        self._await_until = time.monotonic() + TUNGGU_LANJUTAN_S
