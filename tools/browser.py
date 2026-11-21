"""Tool browser_task: delegasi tugas browser ke session Kimi CLI di dashboard `kimi web`
(protokol: POST/GET /api/sessions + WS JSON-RPC, lihat plan iceman-daredevil-starfire).
Kimi CLI yang mengeksekusi via skill kimi-webbridge — kontrol browser asli user."""
import asyncio
import glob
import json
import os
import uuid
from pathlib import Path

import httpx
import websockets
import yaml

from tools.registry import tool

_ROOT = Path(__file__).resolve().parent.parent


def _cfg() -> dict:
    cfg = yaml.safe_load(open(_ROOT / "config.yaml", encoding="utf-8"))
    return cfg.get("browser", {})


def _last_assistant_text(session_dir: str) -> str:
    """Ambil teks pesan assistant terakhir dari context*.jsonl (mtime terbaru)."""
    files = glob.glob(str(Path(session_dir) / "context*.jsonl"))
    if not files:
        return ""
    terbaru = max(files, key=os.path.getmtime)
    last = ""
    for line in open(terbaru, encoding="utf-8"):
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            last = content
        elif isinstance(content, list):  # parts: [{"type":"text","text":...}]
            last = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return last.strip()


async def _run(task: str, cfg: dict) -> str:
    base = cfg.get("kimi_web", "http://127.0.0.1:5494").rstrip("/")
    sid = cfg.get("session_id", "")
    token = cfg.get("token", "")
    timeout = cfg.get("timeout_s", 300)
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{base}/api/sessions/{sid}", headers=headers)
        if r.status_code == 404:
            return "Session Kimi tidak ketemu di dashboard. Cek browser.session_id di config."
        r.raise_for_status()
        session_dir = r.json()["session_dir"]

    ws_url = base.replace("http", "ws", 1) + f"/api/sessions/{sid}/stream"
    if token:
        ws_url += f"?token={token}"
    my_id = uuid.uuid4().hex[:12]
    prompt = {"jsonrpc": "2.0", "method": "prompt", "id": my_id,
              "params": {"user_input": task}}

    async def _wait_selesai(ws) -> str | None:
        """Balas string error kalau gagal; None kalau turn selesai sukses.
        Server mengirim method:'request' untuk approval tool call -> jawab
        'approve_for_session' (ke-cache: tool call berikutnya auto-approve)."""
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("method") == "request":
                rid = (msg.get("params") or {}).get("id") or msg["id"]
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {
                    "request_id": rid, "response": "approve_for_session", "feedback": ""}}))
                continue
            if msg.get("id") != my_id:
                continue  # event stream / status — abaikan
            if "error" in msg:
                teks = str(msg["error"].get("message", msg["error"]))
                if "busy" in teks.lower():
                    return "Session Kimi lagi dipakai. Coba lagi bentar."
                return f"Kimi error: {teks[:150]}"
            return None

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps(prompt))
        err = await asyncio.wait_for(_wait_selesai(ws), timeout)
        if err:
            return err

    jawaban = _last_assistant_text(session_dir)
    return jawaban[-600:] if jawaban else "Kimi selesai, tapi jawabannya kosong. Cek session-nya di dashboard."


@tool("browser_task",
      "Delegasikan tugas browser INTERAKTIF (klik, isi form, baca/ambil isi halaman, searching yang hasilnya perlu dibaca) ke Kimi+WebBridge di browser asli user. LAMBAT: 1-3 menit. JANGAN dipakai untuk sekadar membuka situs/URL (itu pakai open_url, instan) atau sapaan/obrolan.",
      properties={"task": {"type": "string", "description": "instruksi tugas browser lengkap"}},
      required=["task"],
      announce="Oke, lagi kukerjain di browser, ini bisa agak lama. ")
def browser_task(task: str) -> str:
    try:
        return asyncio.run(_run(task, _cfg()))
    except (httpx.ConnectError, OSError, websockets.InvalidURI):
        return "Dashboard Kimi web belum jalan. Nyalain dulu dari Kimi CLI dengan /web."
    except TimeoutError:
        return "Tugas browser kelamaan, dibatalkan. Kerjaannya tetap bisa dicek di dashboard Kimi."
