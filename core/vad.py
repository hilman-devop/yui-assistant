"""Silero VAD via onnxruntime langsung (tanpa torch, tetap ringan).
Model: models/silero_vad.onnx (~2MB). Input: chunk 512 sample @16kHz float32.
Mendukung model v4 (input h/c) dan v5 (input state) secara adaptif.
"""
from pathlib import Path

import numpy as np
import onnxruntime as ort

WINDOW = 512  # 32ms @16kHz, ukuran wajib silero


class Vad:
    def __init__(self, model_path: str | Path, threshold: float = 0.5):
        self.threshold = threshold
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._sess = ort.InferenceSession(str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])
        names = {i.name for i in self._sess.get_inputs()}
        self._v5 = "state" in names  # v5: state (2,1,128); v4: h,c (2,1,64) terpisah
        self.reset()

    def reset(self) -> None:
        if self._v5:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
        else:
            self._h = np.zeros((2, 1, 64), dtype=np.float32)
            self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def prob(self, chunk: np.ndarray) -> float:
        """chunk: float32 (512,) @16kHz -> probabilitas bicara 0..1"""
        x = chunk.astype(np.float32)[None, :]
        sr = np.array(16000, dtype=np.int64)
        if self._v5:
            out, self._state = self._sess.run(None, {"input": x, "state": self._state, "sr": sr})
        else:
            out, self._h, self._c = self._sess.run(None, {"input": x, "h": self._h, "c": self._c, "sr": sr})
        return float(out[0][0])

    def is_speech(self, chunk: np.ndarray, threshold: float | None = None) -> bool:
        return self.prob(chunk) >= (threshold if threshold is not None else self.threshold)
