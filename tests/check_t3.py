"""Self-check T3: TTS synth + playback + stop instan.
Run: .venv\\Scripts\\python tests\\check_t3.py  (mengeluarkan suara di speaker)
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.audio_util import decode_to_pcm
from core.tts import Tts, split_sentences

KALIMAT_PANJANG = ("Ini adalah kalimat uji yang sengaja dibuat sangat panjang supaya "
                   "kita punya waktu beberapa detik untuk menekan tombol stop dan membuktikan "
                   "bahwa suara berhenti hampir seketika tanpa menunggu kalimat selesai.")


def main() -> None:
    # splitter
    s = split_sentences("Halo bos. Apa kabar hari ini? Baik sekali!")
    assert s == ["Halo bos.", "Apa kabar hari ini?", "Baik sekali!"], s

    tts = Tts()

    # synth + decode
    mp3 = asyncio.run(tts.synth("Halo, saya Yui."))
    assert len(mp3) > 1000, "mp3 terlalu kecil"
    pcm, rate = decode_to_pcm(mp3, 24000)
    assert rate == 24000 and len(pcm) > 24000, (rate, len(pcm))
    print(f"synth OK: {len(mp3)} bytes -> pcm {len(pcm)/rate:.1f}s @ {rate}Hz")

    # playback penuh (kalimat pendek)
    asyncio.run(tts.speak("Tes satu dua tiga, suara Yui sudah jalan."))
    assert tts.player.amplitude == 0.0

    # playback panjang + stop di tengah
    async def stop_test() -> float:
        tts.player.reset()  # siklus bicara baru (di produksi: SentenceSpeaker.start)
        task = asyncio.create_task(tts.speak(KALIMAT_PANJANG))
        await asyncio.sleep(3.0)  # pastikan sudah bunyi (synth ~1-2s + play)
        t0 = time.perf_counter()
        tts.stop()
        await task
        return time.perf_counter() - t0

    stop_latency = asyncio.run(stop_test())
    print(f"stop latency: {stop_latency*1000:.0f}ms (mau <1000ms)")
    assert stop_latency < 1.0, "stop terlalu lambat"

    # backend cloud aktif (fish): synth teks pendek — hemat kuota
    import yaml as _yaml
    from core.tts import FishTts, build_tts
    cfg = _yaml.safe_load(open("config.yaml", encoding="utf-8"))
    tts2 = build_tts(cfg)
    if isinstance(tts2, FishTts):
        mp3 = asyncio.run(tts2.synth("tes"))
        assert len(mp3) > 1000
        ogg = asyncio.run(tts2.synth_ogg("tes"))  # OGG/Opus buat voice note WA
        assert ogg[:4] == b"OggS", f"synth_ogg harus kontainer OGG: {ogg[:8]}"
        assert not tts2._dead, "FishTts dead — semua key/kuota bermasalah"
        print("FishTts OK (mp3 + ogg)")
    else:
        print("backend skip (edge-tts / tanpa key)")

    print("T3 OK: synth, playback, dan stop instan berfungsi")


if __name__ == "__main__":
    main()
