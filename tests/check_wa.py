"""Self-check WA bridge: filter self-chat, anti-loop, stop — tanpa WA beneran.
Run: .venv\Scripts\python tests\check_wa.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from core.wa import WaBridge
from memory.store import Memory

ASSETS = Path(__file__).parent / "assets"
SELF = "628111@s.whatsapp.net"
GROUP = "120363777@g.us"  # grup 1 orang "Yui" — wacli tidak bisa kirim ke self-chat


class FakeAgent:
    def __init__(self):
        self.calls = 0

    async def respond(self, msgs):
        self.calls += 1
        yield "jawaban tes"


class FakePipe:
    def __init__(self):
        self.stopped = False

    def stop_speaking(self):
        self.stopped = True


async def main() -> None:
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    cfg["wa"] = {"wacli_path": "bin/wacli.exe", "self_number": "628111",
                 "chat_jid": GROUP, "webhook_secret": "x"}
    (ASSETS / "wa_test.db").unlink(missing_ok=True)
    mem = Memory(str(ASSETS / "wa_test.db"), str(ASSETS / "wa_test_facts.json"))
    agent, pipe = FakeAgent(), FakePipe()
    bridge = WaBridge(cfg, agent, pipe, memory=mem)
    sent: list[str] = []

    async def fake_send(chat, text):
        sent.append(text)

    bridge._send = fake_send

    # 1) perintah dari nomor sendiri di chat khusus direspon
    await bridge.handle({"Chat": GROUP, "SenderJID": SELF, "FromMe": True, "Text": "jam berapa?"})
    assert agent.calls == 1 and sent == ["jawaban tes"], "perintah di chat khusus harus direspon"
    assert [t["role"] for t in mem.recent(4)] == ["user", "assistant"], "turn harus tersimpan"
    print("chat khusus OK")

    # 2) echo balasan Yui -> dibuang (anti-loop)
    await bridge.handle({"Chat": GROUP, "SenderJID": SELF, "FromMe": True, "Text": "jawaban tes"})
    assert agent.calls == 1 and len(sent) == 1, "echo balasan harus dibuang"
    print("anti-loop OK")

    # 3) orang lain di chat khusus & chat lain ditolak
    await bridge.handle({"Chat": GROUP, "SenderJID": "628999@s.whatsapp.net", "FromMe": False, "Text": "halo"})
    await bridge.handle({"Chat": SELF, "SenderJID": SELF, "FromMe": True, "Text": "hai"})
    assert agent.calls == 1 and len(sent) == 1, "pengirim lain / chat lain harus ditolak"
    # 3b) FromMe=true kebal format JID @lid (WA baru) — tetap diterima
    await bridge.handle({"Chat": GROUP, "SenderJID": "100000000000001@lid", "FromMe": True, "Text": "lagi?"})
    assert agent.calls == 2, "FromMe=true harus diterima walau SenderJID berupa @lid"
    # 3c) identitas lain user (allow_numbers, FromMe=false) diterima: LID HP utama + PN HP kedua
    bridge._allow.update({"100000000000001", "6281234567891"})
    await bridge.handle({"Chat": GROUP, "SenderJID": "100000000000001@lid", "FromMe": False, "Text": "dari hp utama"})
    await bridge.handle({"Chat": GROUP, "SenderJID": "6281234567891@s.whatsapp.net", "FromMe": False, "Text": "dari hp kedua"})
    # JID dengan suffix device (:7) — device kedua akun yang sama
    await bridge.handle({"Chat": GROUP, "SenderJID": "100000000000001:7@lid", "FromMe": False, "Text": "dari device lain"})
    assert agent.calls == 5, "LID/PN (+suffix device) di allow_numbers harus diterima"
    print("filter pengirim/chat OK")

    # 4) "stop" -> stop_speaking + balasan, tanpa panggil LLM
    await bridge.handle({"Chat": GROUP, "SenderJID": SELF, "FromMe": True, "Text": "stop"})
    assert pipe.stopped and agent.calls == 5 and sent[-1] == "Baik, berhenti."
    print("stop OK")

    # 5) VN masuk: ditranskrip -> perintah -> balasan VN; gagal VN -> fallback teks
    async def fake_tr(chat, mid, payload=None):
        return "perintah dari pesan suara"
    voice_sent: list[str] = []
    async def fake_rv(chat, text):
        voice_sent.append(text)
        return True
    bridge._transcribe_vn, bridge._reply_voice = fake_tr, fake_rv
    # wacli mengirim VN sebagai Text='[Audio]' + MessageID (tanpa MediaType pun terdeteksi)
    await bridge.handle({"Chat": GROUP, "SenderJID": "100000000000001@lid", "FromMe": False,
                         "Text": "[Audio]", "MessageID": "ABC123"})
    assert agent.calls == 6 and voice_sent == ["jawaban tes"], "VN harus ditranskrip + dibalas VN"
    async def fake_rv_gagal(chat, text):
        return False
    bridge._reply_voice = fake_rv_gagal
    await bridge.handle({"Chat": GROUP, "SenderJID": "100000000000001@lid", "FromMe": False,
                         "Text": "[Audio]", "MessageID": "DEF456"})
    assert agent.calls == 7 and sent[-1] == "jawaban tes", "VN gagal kirim harus fallback teks"
    await bridge.handle({"Chat": GROUP, "SenderJID": SELF, "FromMe": True,
                         "Text": "[Audio]", "MessageID": "GHI789"})
    assert agent.calls == 7, "VN dari device sendiri harus diabaikan (anti-loop)"
    # placeholder media non-audio ([Image] dll) jangan pernah diteruskan ke LLM
    await bridge.handle({"Chat": GROUP, "SenderJID": "100000000000001@lid", "FromMe": False,
                         "Text": "[Image]", "MessageID": "JKL012"})
    assert agent.calls == 7, "placeholder media non-audio harus diabaikan"
    print("VN masuk/balas OK")

    # 6) dokumen dari user -> antre upload NotebookLM (bukan ke LLM); asing/diri sendiri ditolak
    uploaded: list[str] = []
    async def fake_doc(chat, mid):
        uploaded.append(mid)
    bridge._dokumen_ke_notebooklm = fake_doc
    await bridge.handle({"Chat": GROUP, "SenderJID": "100000000000001@lid", "FromMe": False,
                         "Text": "[Document]", "MessageID": "DOC1"})
    assert uploaded == ["DOC1"] and agent.calls == 7, "dokumen user harus ke upload, bukan LLM"
    await bridge.handle({"Chat": GROUP, "SenderJID": "628999@s.whatsapp.net", "FromMe": False,
                         "Text": "[Document]", "MessageID": "DOC2"})
    await bridge.handle({"Chat": GROUP, "SenderJID": SELF, "FromMe": True,
                         "Text": "[Document]", "MessageID": "DOC3"})
    assert uploaded == ["DOC1"], "dokumen asing/dari device sendiri harus ditolak"
    print("dokumen->notebooklm OK")

    print("WA OK: bridge filter + anti-loop + stop berfungsi")


if __name__ == "__main__":
    asyncio.run(main())
