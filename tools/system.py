"""Tools sistem Windows: volume, brightness, media, keyboard, waktu, power."""
import datetime
import subprocess

import comtypes
import keyboard
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from tools.registry import tool


def _endpoint_volume():
    comtypes.CoInitialize()
    return AudioUtilities.GetSpeakers().EndpointVolume


@tool("get_time", "Dapatkan tanggal dan jam sekarang")
def get_time() -> str:
    now = datetime.datetime.now()
    hari = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"][now.weekday()]
    return now.strftime(f"{hari}, %d %B %Y, jam %H:%M")


@tool("set_volume", "Atur volume sistem", {"percent": {"type": "integer", "description": "0-100"}}, ["percent"])
def set_volume(percent: int) -> str:
    percent = max(0, min(100, int(percent)))
    _endpoint_volume().SetMasterVolumeLevelScalar(percent / 100, None)
    return f"Volume diatur ke {percent} persen."


@tool("get_volume", "Lihat volume sistem sekarang")
def get_volume() -> str:
    return f"Volume sekarang {round(_endpoint_volume().GetMasterVolumeLevelScalar() * 100)} persen."


@tool("set_brightness", "Atur kecerahan layar laptop", {"percent": {"type": "integer", "description": "0-100"}}, ["percent"])
def set_brightness(percent: int) -> str:
    import screen_brightness_control as sbc
    percent = max(0, min(100, int(percent)))
    sbc.set_brightness(percent)
    return f"Kecerahan layar diatur ke {percent} persen."


@tool("media_control", "Kontrol media: play, pause, next, previous, mute",
      {"action": {"type": "string", "enum": ["play", "pause", "next", "previous", "mute"]}}, ["action"])
def media_control(action: str) -> str:
    keymap = {"play": "play/pause media", "pause": "play/pause media",
              "next": "next track", "previous": "previous track", "mute": "volume mute"}
    if action not in keymap:
        return f"Aksi media '{action}' tidak dikenal."
    keyboard.send(keymap[action])
    return f"Media: {action}."


@tool("press_hotkey", "Tekan kombinasi tombol keyboard, misal 'ctrl+c', 'alt+tab', 'win+d'",
      {"keys": {"type": "string", "description": "kombinasi tombol, contoh: ctrl+shift+esc"}}, ["keys"])
def press_hotkey(keys: str) -> str:
    keyboard.send(keys.lower().replace(" ", ""))
    return f"Menekan {keys}."


@tool("type_text", "Ketik teks ke jendela aktif", {"text": {"type": "string"}}, ["text"])
def type_text(text: str) -> str:
    keyboard.write(text, delay=0.02)
    return "Teks diketik."


import ast as _ast
import operator as _op

_MATH_OPS = {_ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mult: _op.mul, _ast.Div: _op.truediv,
             _ast.FloorDiv: _op.floordiv, _ast.Mod: _op.mod, _ast.Pow: _op.pow,
             _ast.USub: _op.neg, _ast.UAdd: _op.pos}


def _eval_math(node):
    """Eval AST matematika murni (tanpa eval() — aman dari injeksi)."""
    if isinstance(node, _ast.Expression):
        return _eval_math(node.body)
    if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, _ast.BinOp) and type(node.op) in _MATH_OPS:
        return _MATH_OPS[type(node.op)](_eval_math(node.left), _eval_math(node.right))
    if isinstance(node, _ast.UnaryOp) and type(node.op) in _MATH_OPS:
        return _MATH_OPS[type(node.op)](_eval_math(node.operand))
    raise ValueError("ekspresi tidak didukung")


@tool("hitung", "Hitung ekspresi matematika secara persis, misal '3*6', '(10+5)/3', '2**10', '0.15*200'. "
      "SELALU pakai ini untuk pertanyaan hitungan — instan dan akurat. Buka aplikasi kalkulator "
      "HANYA kalau user eksplisit minta aplikasinya.",
      {"ekspresi": {"type": "string", "description": "ekspresi matematika, misal 3*6"}}, ["ekspresi"])
def hitung(ekspresi: str) -> str:
    bersih = ekspresi.replace("×", "*").replace("x", "*").replace(":", "/").replace(",", ".")
    try:
        hasil = _eval_math(__import__("ast").parse(bersih, mode="eval"))
    except Exception:
        return f"Tidak bisa menghitung '{ekspresi}'."
    if isinstance(hasil, float) and hasil == int(hasil):
        hasil = int(hasil)
    return f"{ekspresi} = {hasil}"


@tool("lock_pc", "Kunci layar Windows (PERLU KONFIRMASI)")
def lock_pc() -> str:
    subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
    return "Layar dikunci."


@tool("sleep_pc", "Sleep laptop (PERLU KONFIRMASI)")
def sleep_pc() -> str:
    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=False)
    return "Laptop sleep."
