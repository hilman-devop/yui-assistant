"""Server avatar: FastAPI static + WebSocket /ws.
Broadcast {state, amp} tiap 60ms -> index.html gerakkan mulut Live2D.
POST /wa: webhook wacli (pesan WA masuk), diverifikasi HMAC X-Wacli-Signature."""
import asyncio
import hashlib
import hmac
import json
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

INDEX = Path(__file__).parent / "index.html"
WEB = Path(__file__).parent
ASSETS = WEB / "assets"
ACTIVE = ASSETS / "active.json"  # karakter terpilih: {"model": "<folder>/<file>.model3.json"}


def karakter_tersedia() -> list[str]:
    """Semua karakter di assets/: folder yang punya *.model3.json (Cubism 3/4) atau *.model.json (Cubism 2)."""
    out = []
    for d in sorted(ASSETS.iterdir()):
        if d.is_dir():
            hits = sorted(d.glob("*.model3.json")) or sorted(d.glob("*.model.json"))
            if hits:
                out.append(f"{d.name}/{hits[0].name}")
    return out


def karakter_aktif() -> str:
    try:
        m = json.loads(ACTIVE.read_text(encoding="utf-8"))["model"]
        if m in karakter_tersedia():
            return m
    except Exception:
        pass
    return "osagegirl/osagegirl.model3.json"  # default awal


def terapkan_suara(pipe, cfg: dict, model_path: str) -> None:
    """Suara per karakter: folder karakter -> tts.character_voices -> FishTts.set_voice."""
    voice = (cfg.get("tts", {}).get("character_voices", {}) or {}).get(model_path.split("/")[0])
    if voice and hasattr(getattr(pipe, "tts", None), "set_voice"):
        pipe.tts.set_voice(voice)


def create_app(pipe, wa_secret: str = "", wa_handler=None, cfg: dict | None = None) -> FastAPI:
    app = FastAPI()
    clients: set[WebSocket] = set()
    app.mount("/vendor", StaticFiles(directory=WEB / "vendor"), name="vendor")
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/")
    async def index():
        return FileResponse(INDEX)

    async def broadcast(msg: str) -> None:
        dead = []
        for c in clients:
            try:
                await c.send_text(msg)
            except Exception:
                dead.append(c)
        for c in dead:
            clients.discard(c)

    @app.get("/api/character")
    async def get_character():
        return {"model": karakter_aktif(), "available": karakter_tersedia()}

    @app.post("/api/character")
    async def set_character(request: Request):
        target = str((await request.json()).get("model", "")).strip().lower()
        for cand in karakter_tersedia():
            if target in (cand.lower(), cand.split("/")[0].lower()):
                ACTIVE.write_text(json.dumps({"model": cand}), encoding="utf-8")
                if cfg:
                    terapkan_suara(pipe, cfg, cand)
                await broadcast(json.dumps({"reload": True}))  # pet/browser reload -> load model baru
                return {"ok": True, "model": cand}
        return JSONResponse({"ok": False, "error": f"karakter '{target}' tidak ada",
                             "available": karakter_tersedia()}, status_code=404)

    @app.post("/api/pause")
    async def set_pause(request: Request):
        if not hasattr(pipe, "toggle_pause"):
            return JSONResponse({"ok": False, "error": "mode WA-only, tidak ada mic"}, status_code=400)
        try:
            body = await request.json()
        except Exception:
            body = {}
        target = body.get("paused")
        if target is None or bool(target) != pipe.paused:
            pipe.toggle_pause()
        return {"ok": True, "paused": pipe.paused}

    @app.post("/api/say")
    async def say(request: Request):
        if not hasattr(pipe, "say"):
            return JSONResponse({"ok": False, "error": "mode WA-only, tidak ada TTS"}, status_code=400)
        text = str((await request.json()).get("text", "")).strip()
        if not text:
            return JSONResponse({"ok": False, "error": "text kosong"}, status_code=400)
        asyncio.create_task(pipe.say(text))
        return {"ok": True}

    @app.post("/wa")
    async def wa(request: Request):
        if wa_handler is None:
            return JSONResponse({"ok": False}, status_code=404)
        body = await request.body()
        expected = "sha256=" + hmac.new(wa_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(request.headers.get("X-Wacli-Signature", ""), expected):
            return JSONResponse({"ok": False}, status_code=403)
        payload = json.loads(body)
        if "EventType" not in payload:  # receipt/presence diabaikan; message memang tanpa EventType
            print(f"[wa] webhook: Chat={str(payload.get('Chat'))[:25]!r} SenderJID={payload.get('SenderJID')!r} Text={str(payload.get('Text'))[:30]!r}")
            asyncio.create_task(wa_handler(payload))  # fire-and-forget: webhook harus cepat balik
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(client: WebSocket):
        await client.accept()
        clients.add(client)
        try:
            while True:
                await client.receive_text()  # keepalive; pesan client diabaikan
        except WebSocketDisconnect:
            clients.discard(client)

    @app.on_event("startup")
    async def broadcaster():
        async def loop():
            while True:
                if clients:
                    amp = float(getattr(pipe.tts.player, "amplitude", 0.0))
                    await broadcast(json.dumps({"state": pipe.state, "amp": round(amp, 3)}))
                await asyncio.sleep(0.06)
        asyncio.create_task(loop())

    return app
