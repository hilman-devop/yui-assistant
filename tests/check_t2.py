"""Self-check T2: VAD + ASR.
Alur: generate suara ID via edge-tts -> decode 16k -> VAD (speech>silence) -> ASR -> teks mirip.
Run: .venv\\Scripts\\python tests\\check_t2.py
"""
import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edge_tts

from core.asr import Asr
from core.audio_util import decode_to_pcm
from core.vad import WINDOW, Vad

KALIMAT = "Halo, saya Yui, asisten pribadi kamu di laptop ini."
ASSET = Path(__file__).parent / "assets" / "tts_test.mp3"


async def buat_aset() -> bytes:
    ASSET.parent.mkdir(exist_ok=True)
    communicate = edge_tts.Communicate(KALIMAT, "id-ID-GadisNeural")
    audio = b"".join([c["data"] async for c in communicate.stream() if c["type"] == "audio"])
    ASSET.write_bytes(audio)
    return audio


def main() -> None:
    audio = asyncio.run(buat_aset())
    pcm, _ = decode_to_pcm(audio, 16000)
    assert len(pcm) > 16000, "audio terlalu pendek"

    # VAD: speech vs silence
    vad = Vad("models/silero_vad.onnx", threshold=0.5)
    n = len(pcm) // WINDOW
    probs = [vad.prob(pcm[i * WINDOW:(i + 1) * WINDOW]) for i in range(n)]
    speech_prob = float(np.mean(probs))
    vad.reset()
    silence = np.zeros(WINDOW * 10, dtype=np.float32)
    sil_prob = max(vad.prob(silence[i * WINDOW:(i + 1) * WINDOW]) for i in range(10))
    print(f"VAD: speech={speech_prob:.3f} (mau >0.5), silence={sil_prob:.3f} (mau <0.2)")
    assert speech_prob > 0.5, "VAD tidak mendeteksi speech"
    assert sil_prob < 0.2, "VAD false-positive pada silence"

    # ASR
    asr = Asr(model_size="small", language="id")
    teks = asr.transcribe(pcm).lower()
    print(f"ASR: '{teks}'")
    assert "yui" in teks, f"ASR melenceng jauh: {teks}"

    print("T2 OK: VAD + ASR berfungsi untuk Bahasa Indonesia")


if __name__ == "__main__":
    main()
