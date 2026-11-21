"""Util audio kecil: decode mp3-bytes -> PCM float32."""
import miniaudio
import numpy as np


def decode_to_pcm(data: bytes, target_rate: int = 16000) -> tuple[np.ndarray, int]:
    """Decode audio (mp3/wav/dll) -> (float32 mono, target_rate). Resample oleh miniaudio."""
    decoded = miniaudio.decode(bytes(data), nchannels=1, sample_rate=target_rate)
    pcm = np.frombuffer(decoded.samples, dtype=np.int16).astype(np.float32) / 32768.0
    return pcm, target_rate
