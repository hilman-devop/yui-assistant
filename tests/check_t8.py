"""Self-check T8: server avatar — GET / + WebSocket broadcast state/amp.
Run: .venv\\Scripts\\python tests\\check_t8.py
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

from fastapi.testclient import TestClient

from web.server import create_app


def main() -> None:
    pipe = SimpleNamespace(state="speaking",
                           tts=SimpleNamespace(player=SimpleNamespace(amplitude=0.5)))
    with TestClient(create_app(pipe)) as client:  # 'with' wajib: menjalankan startup event
        r = client.get("/")
        assert r.status_code == 200
        html = r.text
        assert "PIXI" in html and "ParamMouthOpenY" in html and "WebSocket" in html
        print("GET / OK: Live2D + lip-sync JS ada")

        with client.websocket_connect("/ws") as ws:
            time.sleep(0.3)  # tunggu tick broadcaster (60ms)
            msg = ws.receive_json()
            print(f"broadcast: {msg}")
            assert msg["state"] == "speaking" and msg["amp"] == 0.5
            ws.send_text("ping")  # keepalive path

        # endpoint ganti karakter (active.json asli disimpan-dipulihkan)
        from web.server import ACTIVE
        asli = ACTIVE.read_text(encoding="utf-8") if ACTIVE.exists() else None
        try:
            r = client.get("/api/character")
            assert r.status_code == 200 and r.json()["available"], "tidak ada karakter di assets"
            avail = r.json()["available"]
            lain = next(a for a in avail if a != r.json()["model"]) if len(avail) > 1 else avail[0]
            r = client.post("/api/character", json={"model": lain.split("/")[0]})  # nama folder saja cukup
            assert r.status_code == 200 and r.json()["model"] == lain, r.text
            assert client.get("/api/character").json()["model"] == lain
            r = client.post("/api/character", json={"model": "ngasal123"})
            assert r.status_code == 404
            print(f"ganti karakter OK: {lain}")
        finally:
            if asli is None:
                ACTIVE.unlink(missing_ok=True)
            else:
                ACTIVE.write_text(asli, encoding="utf-8")

    # suara per karakter: POST /api/character dengan cfg character_voices -> pipe.tts.set_voice
    class VoiceTts:
        player = SimpleNamespace(amplitude=0.0)

        def __init__(self):
            self.voices = []

        def set_voice(self, v):
            self.voices.append(v)

    p = SimpleNamespace(state="idle", tts=VoiceTts())
    cfg = {"tts": {"character_voices": {lain.split("/")[0]: "voice-test-123"}}}
    with TestClient(create_app(p, cfg=cfg)) as c5:
        r = c5.post("/api/character", json={"model": lain.split("/")[0]})
        assert r.status_code == 200 and p.tts.voices == ["voice-test-123"], "suara karakter tidak diterapkan"
    # pulihkan karakter semula
    with TestClient(create_app(p)) as c6:
        c6.post("/api/character", json={"model": (json.loads(asli)["model"] if asli else "osagegirl").split("/")[0]})
    print("suara per karakter OK")

    # endpoint mode diam: pipe asli punya toggle_pause; pipe WA-only (SimpleNamespace) -> 400
    class FakePipe:
        def __init__(self):
            self.paused = False
            self.state = "idle"
            self.tts = SimpleNamespace(player=SimpleNamespace(amplitude=0.0))

        def toggle_pause(self):
            self.paused = not self.paused
            self.state = "paused" if self.paused else "idle"
            return self.paused

    with TestClient(create_app(FakePipe())) as c2:
        assert c2.post("/api/pause", json={}).json()["paused"] is True          # toggle
        assert c2.post("/api/pause", json={"paused": True}).json()["paused"] is True   # no-op
        assert c2.post("/api/pause", json={"paused": False}).json()["paused"] is False
    with TestClient(create_app(pipe)) as c3:  # pipe SimpleNamespace tanpa toggle_pause/say
        assert c3.post("/api/pause", json={}).status_code == 400
        assert c3.post("/api/say", json={"text": "tes"}).status_code == 400
    print("mode diam endpoint OK")

    # endpoint katakan: pipe asli punya say(); teks kosong -> 400
    class SayPipe(FakePipe):
        def __init__(self):
            super().__init__()
            self.said = []

        async def say(self, text):
            self.said.append(text)

    with TestClient(create_app(SayPipe())) as c4:
        assert c4.post("/api/say", json={"text": "halo tuanku"}).json()["ok"] is True
        assert c4.post("/api/say", json={"text": ""}).status_code == 400
    print("say endpoint OK")

    print("T8 OK: server avatar + WebSocket broadcast berfungsi")
    print("Catatan visual: jalankan main.py lalu buka http://127.0.0.1:8765")


if __name__ == "__main__":
    main()
