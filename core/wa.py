"""Bridge WhatsApp via wacli: perintah dari chat khusus -> Agent -> balasan WA.
wacli sync meng-POST pesan masuk ke webhook /wa (lihat web/server.py); modul ini
handler + supervisor proses sync-nya.
Chat khusus (wa.chat_jid): grup "Laptop" — wacli tidak bisa mengirim ke
self-chat (Message Yourself) karena batasan protokol WA Web, jadi grup dipakai.
Keamanan: hanya pesan dari chat itu DAN dari identitas user (self_number +
allow_numbers: LID HP utama + PN HP kedua, suffix :device dibuang) yang direspon;
balasan Yui sendiri dibuang (anti-loop).
"""
import asyncio
import tempfile
import time
from collections import deque
from pathlib import Path

from core.llm import SYSTEM_PROMPT
from core.pipeline import STOP_WORDS, VOICE_LANG_RULE
from memory.store import Memory, get_memory


class WaBridge:
    def __init__(self, cfg: dict, agent, pipe=None, memory: Memory | None = None):
        wcfg = cfg["wa"]
        self._wacli = wcfg.get("wacli_path", "bin/wacli.exe")
        self._self = wcfg.get("self_number", "").strip()  # kosong = tolak semua
        # identitas lain milik user: pesan dari HP utama tiba sbg @lid + FromMe=false,
        # HP kedua sbg PN biasa — keduanya di allow_numbers
        self._allow = {self._self, *wcfg.get("allow_numbers", [])} - {""}
        self._chat = wcfg.get("chat_jid", "").strip() or f"{self._self}@s.whatsapp.net"
        self.secret = wcfg.get("webhook_secret", "")
        self._hook_url = f"http://{cfg['web']['host']}:{cfg['web']['port']}/wa"
        self._agent = agent
        self._pipe = pipe
        self._memory = memory or get_memory(cfg)
        self._turns = cfg.get("memory", {}).get("history_turns", 6)
        self._sent: deque[tuple[str, float]] = deque(maxlen=8)  # anti-loop: balasan Yui

    def _is_own_reply(self, text: str) -> bool:
        now = time.monotonic()
        while self._sent and now - self._sent[0][1] > 30:
            self._sent.popleft()
        return any(t == text for t, _ in self._sent)

    async def handle(self, payload: dict) -> None:
        """Terima payload webhook wacli (message). Lolos filter -> Agent -> balas."""
        text = (payload.get("Text") or "").strip()
        if payload.get("Chat") != self._chat:
            return  # chat lain — diam
        voice_reply = False
        doc_msg_id = None  # dokumen dari user -> diupload ke NotebookLM (setelah pengirim diverifikasi)
        # VN tiba sebagai Text='[Audio]' (placeholder wacli). Media lain = '[Image]' dll.
        is_media = not text or (text.startswith("[") and text.endswith("]"))
        if is_media:
            mtype = str(payload.get("MediaType") or "").lower()
            is_audio = text == "[Audio]" or "audio" in mtype
            msg_id = next((payload.get(k) for k in
                           ("MessageID", "ID", "Id", "MsgID") if payload.get(k)), "")
            if is_audio and msg_id and not payload.get("FromMe"):
                print(f"[wa] VN masuk (id {str(msg_id)[:12]}...) — transkripsi")
                text = await self._transcribe_vn(self._chat, str(msg_id), payload)
                if not text:
                    return
                voice_reply = True
            elif text == "[Document]" and msg_id and not payload.get("FromMe"):
                doc_msg_id = str(msg_id)
            else:
                print(f"[wa] media diabaikan: {text!r} keys={sorted(payload.keys())}")  # debug field
                return
        # FromMe=true = dikirim device wacli ini (balasan Yui sudah ke-filter anti-loop).
        # Pesan dari HP user tiba sbg SenderJID @lid/PN + FromMe=false -> cocokkan whitelist.
        # JID bisa bawa suffix device ("100000000000001:7@lid") -> buang ":device"
        sender = (payload.get("SenderJID") or "").split("@")[0].split(":")[0]
        sender_ok = payload.get("FromMe") or sender in self._allow
        if not sender_ok:
            return  # di chat khusus, hanya perintah dari user sendiri
        if self._is_own_reply(text):
            return  # echo balasan Yui sendiri
        if doc_msg_id is not None:
            await self._dokumen_ke_notebooklm(payload["Chat"], doc_msg_id)
            return
        print(f"[wa] perintah: '{text}'" + (" [VN]" if voice_reply else ""))
        chat = payload["Chat"]
        if text.lower() in STOP_WORDS:
            if self._pipe:
                self._pipe.stop_speaking()
            await self._reply(chat, "Baik, berhenti.")
            return
        # VN: LLM langsung jawab Jepang (hemat 1 call terjemahan); teks fallback tetap dikirim apa adanya
        lang = VOICE_LANG_RULE if voice_reply else ""
        msgs = [{"role": "system", "content": SYSTEM_PROMPT + self._memory.fact_text() + lang},
                *self._memory.recent(self._turns), {"role": "user", "content": text}]
        try:
            reply = "".join([d async for d in self._agent.respond(msgs)]).strip()
        except Exception as e:
            print(f"[wa] LLM gagal total: {type(e).__name__}: {str(e)[:100]}")
            await self._reply(chat, "Maaf Tuanku, koneksi otakku lagi gangguan (semua endpoint gagal). Coba lagi sebentar ya.")
            return
        self._memory.add_turn("user", text)
        self._memory.add_turn("assistant", reply)
        if reply:
            if not voice_reply or not await self._reply_voice(chat, reply):
                await self._reply(chat, reply)  # VN gagal/Fish mati -> teks biasa

    async def _file_store(self, chat: str, msg_id: str) -> Path | None:
        """File media dari store wacli: ~/.wacli/media/<chat_@->_>/<id>/<jenis>/message-<id>.<ext>.
        sync --download-media mengunduh di background — webhook bisa tiba SEBELUM file ada:
        polling maks 20s + tunggu ukuran stabil. (Baca langsung: `wacli media download` macet
        kena store lock selama sync jalan.)"""
        d = Path.home() / ".wacli" / "media" / chat.replace("@", "_") / msg_id
        path = None
        for _ in range(40):
            if d.is_dir():
                files = [p for p in d.rglob("*") if p.is_file() and p.stat().st_size > 0]
                if files:
                    path = files[0]
                    break
            await asyncio.sleep(0.5)
        if path is not None:  # pastikan unduhan selesai (ukuran stabil)
            s0 = -1
            while path.stat().st_size != s0:
                s0 = path.stat().st_size
                await asyncio.sleep(0.6)
        return path

    async def _transcribe_vn(self, chat: str, msg_id: str, payload: dict | None = None) -> str:
        """VN -> teks (Groq upload file / lokal PyAV). Dari store; kalau belum ada, CLI. '' = gagal."""
        asr = getattr(self._pipe, "asr", None)
        if asr is None or not hasattr(asr, "transcribe_file"):
            await self._reply(chat, "Maaf Tuanku, di mode ini aku tidak bisa dengar pesan suara.")
            return ""
        path = await self._file_store(chat, msg_id)
        downloaded = False
        if path is None:
            outdir = Path(tempfile.gettempdir()) / "yui_vn"
            outdir.mkdir(exist_ok=True)
            proc = await asyncio.create_subprocess_exec(
                self._wacli, "media", "download", "--chat", chat, "--id", msg_id,
                "--output", str(outdir), "--lock-wait", "30s",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            if proc.returncode != 0:
                print(f"[wa] unduh VN gagal: {err.decode(errors='replace')[:150]}")
                return ""
            files = sorted(outdir.glob("*"), key=lambda p: p.stat().st_mtime)
            if not files:
                return ""
            path, downloaded = files[-1], True  # hasil unduh CLI = file sementara kita, boleh hapus
        try:
            teks = await asyncio.to_thread(asr.transcribe_file, path)
            print(f"[wa] VN terdengar: '{teks}'")
            return teks
        finally:
            if downloaded:
                path.unlink(missing_ok=True)

    async def _dokumen_ke_notebooklm(self, chat: str, msg_id: str) -> None:
        """Dokumen dari WA -> upload ke NotebookLM (notebook terbaru) via browser_task."""
        path = await self._file_store(chat, msg_id)
        if path is None:
            await self._reply(chat, "Maaf Tuanku, filenya tidak ketemu di unduhan.")
            return
        await self._reply(chat, f"File '{path.name}' kuterima — kuupload ke NotebookLM (1-3 menit).")
        from tools.browser import _cfg, _run
        from tools.notebooklm import _instruksi
        try:
            hasil = await _run(_instruksi("upload_file", str(path),
                                          "notebook yang paling baru dibuka"), _cfg())
        except Exception as e:
            hasil = f"Upload gagal: {type(e).__name__} — {e}"
        print(f"[wa] upload notebooklm: {str(hasil)[:120]}")
        self._memory.add_turn("user", f"[file WA: {path.name}]")
        self._memory.add_turn("assistant", str(hasil)[-300:])
        await self._reply(chat, str(hasil)[-500:])

    async def _reply_voice(self, chat: str, text: str) -> bool:
        """Balas VN dengan VN (LLM sudah jawab Jepang): synth Fish OGG/Opus (tanpa ffmpeg).
        False = gagal -> caller kirim teks biasa."""
        synth_ogg = getattr(getattr(self._pipe, "tts", None), "synth_ogg", None)
        if synth_ogg is None:
            return False
        ogg = await synth_ogg(text)
        if not ogg:
            return False
        path = Path(tempfile.gettempdir()) / f"yui_vn_{int(time.time())}.ogg"
        path.write_bytes(ogg)
        try:
            proc = await asyncio.create_subprocess_exec(
                self._wacli, "send", "voice", "--to", chat, "--file", str(path),
                "--lock-wait", "30s", "--post-send-wait", "0",  # bawaan 2s cuma nunggu receipt
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            if proc.returncode != 0:
                print(f"[wa] gagal kirim VN: {err.decode(errors='replace')[:150]}")
                return False
            return True
        finally:
            path.unlink(missing_ok=True)

    async def _reply(self, chat: str, text: str) -> None:
        self._sent.append((text, time.monotonic()))  # sebelum kirim: echo bisa datang cepat
        await self._send(chat, text)

    async def _send(self, chat: str, text: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            self._wacli, "send", "text", "--to", chat, "--message", text,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode != 0:
            print(f"[wa] gagal kirim balasan: {err.decode(errors='replace')[:150]}")

    async def run_sync(self) -> None:
        """Supervisor: jaga `wacli sync --follow` tetap hidup; restart dengan backoff."""
        args = [self._wacli, "sync", "--follow",
                "--webhook", self._hook_url,
                "--webhook-secret", self.secret,
                "--webhook-allow-private",   # webhook kita 127.0.0.1 — default wacli menolak
                "--download-media",          # VN masuk ikut terunduh (ditranskrip jadi perintah)
                "--presence-mode", "quiet",  # HP utama tetap bunyi notifikasi
                "--max-reconnect", "0"]      # reconnect tak terbatas
        backoff = 2
        while True:
            print("[wa] sync wacli dimulai")
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
            tail = err.decode(errors="replace")[-200:] if err else ""
            print(f"[wa] sync berhenti (kode {proc.returncode}) {tail} — restart {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
