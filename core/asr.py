"""ASR: dua backend, interface sama (.transcribe(pcm16k) -> str).
- RouterAsr: POST /audio/transcriptions OpenAI-compatible (dipakai untuk Groq — cepat+akurat, online).
- Asr (lokal): faster-whisper CPU int8 (offline, lambat di CPU lemah).
Fallback otomatis: router gagal -> lokal.
"""
import io
import os
import wave

import numpy as np


def pcm_to_wav(pcm16k: np.ndarray, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(pcm16k, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


class Asr:
    """Lokal: faster-whisper, Bahasa Indonesia, CPU int8. Satu model (single-pass)."""

    def __init__(self, model_size: str = "base", device: str = "cpu",
                 compute_type: str = "int8", language: str = "id", beam_size: int = 1):
        from faster_whisper import WhisperModel
        self._language = language
        self._beam = beam_size
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type,
                                  cpu_threads=os.cpu_count() or 4, num_workers=1)

    def transcribe(self, pcm16k: np.ndarray) -> str:
        segments, _ = self.model.transcribe(
            pcm16k, language=self._language, beam_size=self._beam,
            vad_filter=False, condition_on_previous_text=False)
        return " ".join(s.text for s in segments).strip()

    def transcribe_file(self, path) -> str:
        """File audio apa pun (ogg/opus VN WA dll) — PyAV yang decode."""
        segments, _ = self.model.transcribe(
            str(path), language=self._language, beam_size=self._beam,
            vad_filter=False, condition_on_previous_text=False)
        return " ".join(s.text for s in segments).strip()


class RouterAsr:
    """Cloud STT OpenAI-compatible /audio/transcriptions (dipakai: Groq).
    Circuit breaker: gagal sekali -> lokal terus selama sesi (percobaan ulang cuma buang waktu)."""

    def __init__(self, base_url: str, api_key: str, model: str = "whisper-1",
                 language: str = "id", fallback: Asr | None = None):
        self._url = base_url.rstrip("/") + "/audio/transcriptions"
        self._key = api_key
        self._model = model
        self._language = language
        self._fallback = fallback
        self._dead = False

    def transcribe(self, pcm16k: np.ndarray) -> str:
        if self._dead:
            return self._fallback.transcribe(pcm16k)
        import httpx
        try:
            r = httpx.post(self._url,
                           headers={"Authorization": f"Bearer {self._key}"},
                           data={"model": self._model, "language": self._language},
                           files={"file": ("speech.wav", pcm_to_wav(pcm16k), "audio/wav")},
                           timeout=6.0)
            r.raise_for_status()
            return r.json().get("text", "").strip()
        except Exception as e:
            if self._fallback is None:
                raise
            self._dead = True
            print(f"[asr] router STT tidak tersedia ({type(e).__name__}) -> lokal untuk sesi ini")
            return self._fallback.transcribe(pcm16k)

    def transcribe_file(self, path) -> str:
        """Upload file apa adanya (ogg/mp3/wav) — dipakai untuk voice note WA."""
        if self._dead:
            return self._fallback.transcribe_file(path)
        import httpx
        try:
            name = os.path.basename(str(path))
            if name.lower().endswith(".oga"):
                name = name[:-4] + ".ogg"  # Groq menolak ekstensi .oga; isinya sama (ogg opus)
            with open(path, "rb") as f:
                r = httpx.post(self._url,
                               headers={"Authorization": f"Bearer {self._key}"},
                               data={"model": self._model, "language": self._language},
                               files={"file": (name, f)},
                               timeout=30.0)
            r.raise_for_status()
            return r.json().get("text", "").strip()
        except Exception as e:
            if self._fallback is None:
                raise
            self._dead = True
            print(f"[asr] router STT tidak tersedia ({type(e).__name__}) -> lokal untuk sesi ini")
            return self._fallback.transcribe_file(path)


def build_asr(cfg: dict):
    """Factory: Groq STT (GROQ_API_KEY) > lokal. 9Router sengaja dilewati — tidak support STT,
    mencoba tetap membuang 1 HTTP call gagal di ucapan pertama tiap sesi."""
    language = cfg.get("language", "id")
    acfg = cfg["asr"]
    backend = acfg.get("backend", "auto")
    local = Asr(acfg["model_size"], acfg["device"], acfg["compute_type"], language,
                acfg["beam_size"])
    if backend == "local":
        return local
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key:
        print("[asr] STT via Groq (whisper-large-v3-turbo)")
        return RouterAsr("https://api.groq.com/openai/v1", groq_key,
                         acfg.get("groq_model", "whisper-large-v3-turbo"),
                         language, fallback=local)
    return local
