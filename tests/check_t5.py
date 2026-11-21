"""Self-check T5: pipeline — wake parsing, ignore non-wake, respons end-to-end (mock LLM + fake TTS).
Run: .venv\\Scripts\\python tests\\check_t5.py
"""
import asyncio
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edge_tts

from core.asr import Asr
from core.audio_util import decode_to_pcm
from core.llm import MockLlm
from core.pipeline import Pipeline, _SENT_END, _is_echo, extract_command

ASSETS = Path(__file__).parent / "assets"


class FakePlayer:
    amplitude = 0.0

    def reset(self): pass
    def stop(self): pass


class FakeTts:
    def __init__(self):
        self.spoken: list[str] = []
        self.player = FakePlayer()

    async def speak(self, text: str):
        self.spoken.append(text)
        await asyncio.sleep(0.01)

    def stop(self): pass


async def buat_audio(teks: str, nama: str):
    p = ASSETS / nama
    if not p.exists():
        audio = b"".join([c["data"] async for c in edge_tts.Communicate(teks, "id-ID-GadisNeural").stream()
                          if c["type"] == "audio"])
        p.write_bytes(audio)
    return decode_to_pcm(p.read_bytes(), 16000)[0]


async def main() -> None:
    # 1) wake parsing murni
    assert extract_command("Yui, kecilin volume") == "kecilin volume"
    assert extract_command("yuy tolong buka chrome") == "tolong buka chrome"
    assert extract_command("Yui") == ""
    assert extract_command("halo apa kabar") is None
    assert extract_command("halo yui") == "halo"            # wake-word di akhir
    assert extract_command("kamu tahu yui?") == "kamu tahu"  # posisi bebas = respon
    assert extract_command("yuima apa kabar") is None        # substring bukan wake-word
    # pemisah kalimat: ':' setelah angka (jam) bukan akhir kalimat
    assert not _SENT_END.search("sekarang jam 10:30 ya")
    assert _SENT_END.search("begini caranya: coba")
    print("wake parsing OK")

    # 1b) echo filter: perintah yang semua katanya sedang diucapkan Yui = echo
    assert _is_echo("kita mulai", "Yuk kita mulai.")            # wake-variant salah dengar
    assert _is_echo("cuaca hari ini cerah", "Cuaca hari ini cerah sekali di Jakarta.")
    assert not _is_echo("atur volume ke 50", "Baik, volume sudah saya atur ke 20 persen.")
    assert not _is_echo("stop", "kalimat apa pun")              # 1 kata = interaksi asli
    assert not _is_echo("kita mulai", "")                      # Yui sedang diam
    print("echo filter OK")

    # 2) pipeline end-to-end dengan audio beneran.
    # Catatan: assert pada ALUR (state, wake, respons non-kosong) — akurasi kata ASR
    # lokal memang terbatas di CPU ini; akurasi penuh divalidasi di T10 via router.
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    asr = Asr(cfg["asr"]["model_size"], language=cfg["language"])
    tts = FakeTts()
    from memory.store import Memory
    (ASSETS / "t5.db").unlink(missing_ok=True)  # db uji harus bersih — assert menghitung jumlah turn
    mem = Memory(str(ASSETS / "t5.db"), str(ASSETS / "t5_facts.json"))
    pipe = Pipeline(cfg, MockLlm(delay=0.001), asr=asr, tts=tts, memory=mem)
    states = []
    pipe.on_state = lambda s, a: states.append(s)

    pcm = await buat_audio("Yui, kecilin volume dong", "wake_volume.mp3")
    t0 = time.perf_counter()
    await pipe.handle_utterance(pcm)
    dur = time.perf_counter() - t0
    print(f"respons: {tts.spoken} ({dur:.2f}s total)")
    assert tts.spoken, "tidak ada respons untuk perintah wake"
    assert "processing" in states and "speaking" in states and states[-1] == "idle"
    assert len(mem.recent(10)) == 2 and mem.recent(10)[1]["role"] == "assistant"

    # 2b) mode diam (F11): state paused, toggle balik ke idle
    assert pipe.toggle_pause() is True and pipe.state == "paused"
    assert pipe.toggle_pause() is False and pipe.state == "idle"
    print("mode diam OK")

    # 3) ucapan tanpa wake-word diabaikan (jendela lanjutan ditutup dulu = user diam >10 detik)
    pipe._await_until = 0.0
    tts.spoken.clear()
    pcm2 = await buat_audio("Halo semuanya, apa kabar hari ini", "no_wake.mp3")
    h0 = len(mem.recent(10))
    await pipe.handle_utterance(pcm2)
    assert tts.spoken == [] and len(mem.recent(10)) == h0, "ucapan non-wake harus diabaikan"
    print("non-wake diabaikan OK")

    # 3b) panggil 'Yui' doang -> disahut (ご主人様), ucapan berikutnya = perintah tanpa wake-word
    tts.spoken.clear()
    pcm3 = await buat_audio("Yui", "wake_only.mp3")
    h1 = len(mem.recent(10))
    await pipe.handle_utterance(pcm3)
    assert any("ご主人様" in s for s in tts.spoken), f"sahutan harus panggil goshujin-sama: {tts.spoken}"
    assert pipe._await_until > 0 and len(mem.recent(10)) == h1, "sahutan tidak boleh dicatat ke memori"
    tts.spoken.clear()
    pcm4 = await buat_audio("Kecilin volume dong", "lanjutan.mp3")  # tanpa wake-word
    await pipe.handle_utterance(pcm4)
    assert tts.spoken and len(mem.recent(10)) == h1 + 2, "ucapan setelah sahutan harus jadi perintah"
    assert pipe._await_until > 0, "setelah menjawab harus ada jendela lanjutan"
    print("panggil-dulu-baru-perintah OK")

    # 3c) lanjutan obrolan: habis Yui jawab, ucapan tanpa wake-word = lanjutan (bukan diabaikan)
    tts.spoken.clear()
    pcm5 = await buat_audio("Terima kasih Yui", "lanjutan2.mp3")
    h2 = len(mem.recent(10))
    await pipe.handle_utterance(pcm5)
    assert tts.spoken and len(mem.recent(10)) == h2 + 2, "lanjutan tanpa wake-word harus diproses"
    pipe._await_until = 0.0  # tutup jendela manual = user diam >10 detik
    tts.spoken.clear()
    h3 = len(mem.recent(10))
    await pipe.handle_utterance(pcm5)
    assert not tts.spoken and len(mem.recent(10)) == h3, "jendela tertutup -> non-wake diabaikan lagi"
    print("lanjutan obrolan OK")

    print("T5 OK: pipeline end-to-end berfungsi")


if __name__ == "__main__":
    asyncio.run(main())
