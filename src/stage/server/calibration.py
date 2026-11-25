"""Calibration stimuli: a short noise burst from a known direction through a chosen measured head.

The web app's calibration game (decision 0026) plays these. The burst is band-limited pink-ish
noise (200 Hz to 12 kHz, three 120 ms pulses with 40 ms gaps and 10 ms ramps): broadband enough to
carry the spectral cues of elevation and front-back, short enough to be played from a direction
without head movement helping. It is rendered dry (the direct HRTF only), like the objects of the
dry stage, and cached because the same few stimuli are asked for again and again.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from scipy.signal import butter, sosfiltfilt

from stage.spatial.heads import DEFAULT_HEAD, PUBLISHED, head_label, pack_path
from stage.spatial.hrtf import get_hrtf
from stage.stream import codec

SR = 48000


def burst(seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(0.52 * SR)
    noise = rng.standard_normal(n)
    # Pink-ish: a 1/f tilt by integrating lightly, then band-limit.
    sos = butter(2, [200, 12000], "bandpass", fs=SR, output="sos")
    x = sosfiltfilt(sos, np.cumsum(noise) * 0.02 + noise)
    env = np.zeros(n)
    ramp = int(0.01 * SR)
    for k in range(3):
        a = int(k * 0.16 * SR)
        b = a + int(0.12 * SR)
        seg = np.ones(b - a)
        seg[:ramp] = np.linspace(0, 1, ramp)
        seg[-ramp:] = np.linspace(1, 0, ramp)
        env[a:b] = seg
    x = x * env
    return (0.5 * x / (np.max(np.abs(x)) + 1e-9)).astype(np.float32)


@lru_cache(maxsize=256)
def stimulus(head: str, az: float, el: float) -> bytes:
    hs = get_hrtf(SR, head=head)
    h = hs.hrirs(az, el)[0]
    x = burst()
    left = np.convolve(x, h[0])[: x.size + 64]
    right = np.convolve(x, h[1])[: x.size + 64]
    y = np.stack([left, right])
    return codec.encode_segment(y, SR, "flac").data


def create_calibration_router() -> APIRouter:
    router = APIRouter(prefix="/v3/calibration")

    @router.get("/heads")
    def heads() -> dict:
        have = [h for h in PUBLISHED if h == DEFAULT_HEAD or pack_path(h).is_file()]
        return {"heads": [{"id": h, "label": head_label(h)} for h in have], "default": DEFAULT_HEAD}

    @router.get("/stimulus")
    def stim(head: str = DEFAULT_HEAD, az: float = 0.0, el: float = 0.0) -> Response:
        if head not in PUBLISHED or not -180 <= az <= 180 or not -45 <= el <= 90:
            raise HTTPException(400, "unknown head or direction")
        data = stimulus(head, round(az, 1), round(el, 1))
        return Response(data, media_type="audio/flac",
                        headers={"Cache-Control": "public, max-age=86400"})

    return router
