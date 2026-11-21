"""Entry point Yui. Run: .venv\\Scripts\\python main.py
Avatar: buka http://127.0.0.1:8765 di browser."""
import asyncio
import sys

import keyboard
import uvicorn
import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # print emoji Windows aman

import os
from pathlib import Path

for line in Path(__file__).with_name(".env").read_text(encoding="utf-8").splitlines() \
        if Path(__file__).with_name(".env").exists() else []:
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from types import SimpleNamespace

from core.agent import Agent
from core.llm import build_llm
from core.pipeline import Pipeline
from core.wa import WaBridge
from web.desktop import Pet
from web.server import create_app, karakter_aktif, terapkan_suara


async def amain(wa_only: bool = False) -> None:
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    llm = build_llm(cfg["llm"])
    agent = Agent(llm)
    if wa_only:
        # tanpa mic/ASR/TTS: hanya agent + webhook WA (dipakai saat jauh dari laptop)
        pipe = SimpleNamespace(state="idle",
                               tts=SimpleNamespace(player=SimpleNamespace(amplitude=0.0)),
                               stop_speaking=lambda: None)
    else:
        pipe = Pipeline(cfg, llm)
        pipe.respond = agent.respond
    bridge = None
    if cfg.get("wa", {}).get("enabled"):
        bridge = WaBridge(cfg, agent, pipe)
        print("[wa] bridge aktif — perintah via self-chat WA diterima")

    async def warmup_dan_probe() -> None:
        """Jalan di background — tidak boleh menghalangi listening."""
        if hasattr(llm, "resolve_model"):
            await llm.resolve_model()
            print(f"[llm] model: {llm.model}")
        try:
            async for _ in llm.stream([{"role": "user", "content": "hai"}]):  # bunuh cold-start
                break
        except Exception as e:
            print(f"[llm] warmup gagal: {type(e).__name__}")
        await agent.probe()
        print("[llm] siap")

    asyncio.create_task(warmup_dan_probe())

    keyboard.on_press_key(cfg.get("hotkeys", {}).get("interrupt", "f9"),
                          lambda e: pipe.stop_speaking())
    if hasattr(pipe, "toggle_pause"):
        keyboard.on_press_key(cfg.get("hotkeys", {}).get("pause", "f11"),
                              lambda e: pipe.toggle_pause())

    terapkan_suara(pipe, cfg, karakter_aktif())  # suara per karakter saat startup
    web = uvicorn.Server(uvicorn.Config(
        create_app(pipe, wa_secret=bridge.secret if bridge else "",
                   wa_handler=bridge.handle if bridge else None, cfg=cfg),
        host=cfg["web"]["host"], port=cfg["web"]["port"],
        log_level="warning"))
    if bridge:
        asyncio.create_task(bridge.run_sync())
    print(f"[yui] avatar: http://{cfg['web']['host']}:{cfg['web']['port']}")
    try:
        if wa_only:
            await web.serve()
        else:
            await asyncio.gather(web.serve(), pipe.run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[yui] dadah.")
    finally:
        pipe.stop_speaking()


def main() -> None:
    wa_only = "--wa-only" in sys.argv
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    if not wa_only and cfg.get("desktop", {}).get("pet", False):
        import threading
        url = f"http://{cfg['web']['host']}:{cfg['web']['port']}/?pet=1"
        pet = Pet(url, width=cfg["desktop"].get("width", 320),
                  height=cfg["desktop"].get("height", 420))
        keyboard.on_press_key(cfg.get("hotkeys", {}).get("clickthrough", "f10"),
                              lambda e: pet.toggle_clickthrough())
        keyboard.on_press_key(cfg.get("hotkeys", {}).get("debug", "f8"),
                              lambda e: pet.toggle_debug())
        threading.Thread(target=lambda: asyncio.run(amain()), daemon=True).start()
        print("[yui] mode desktop pet: geser = drag, dblclick/F10 = click-through")
        pet.start()  # blocking di main thread
    else:
        asyncio.run(amain(wa_only))


if __name__ == "__main__":
    main()
