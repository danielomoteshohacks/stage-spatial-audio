"""Delivery encoding: Opus (or AAC) for streaming, FLAC for downloads.

Opus at 160 kb/s stereo is transparent for almost all music (the IETF codec's listening tests put
it above 128 kb/s for stereo music, RFC 6716 and the Opus listening-test reports), and a minute is
about 1.2 MB, which matters on mobile data. Where a browser cannot play Opus in Ogg (older Safari)
the same segment is encoded as AAC-LC in an ADTS-free MP4 audio file at 192 kb/s.

Segments are encoded on their own, with `pad_s` of the neighbouring audio on each side that the
client throws away: a lossy codec's first and last tens of milliseconds are the least accurate, so
the part kept is always well inside both ends and two neighbouring segments meet with only the
codec's own noise between them (tests/unit/test_stream_codec.py measures the seam).

ffmpeg is used when it is on the machine (a Space gets it from packages.txt); otherwise Opus
falls back to libsndfile's encoder and AAC is not offered (the server then answers Opus only and
says so).
"""

from __future__ import annotations

import io
import shutil
import subprocess
from dataclasses import dataclass

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

PAD_S = 0.05
OPUS_KBPS = 160
AAC_KBPS = 192
FORMATS = {"opus": ("audio/ogg; codecs=opus", "opus"), "aac": ("audio/mp4", "m4a"),
           "flac": ("audio/flac", "flac")}


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def available_formats() -> list[str]:
    return ["opus", "flac"] + (["aac"] if ffmpeg_path() else [])


@dataclass
class Encoded:
    data: bytes
    fmt: str
    sample_rate: int
    pre: int  # samples of leading context to drop after decoding (at `sample_rate`)
    post: int  # samples of trailing context to drop
    samples: int  # samples that remain after dropping the context


def _ffmpeg_encode(pcm: NDArray, sr: int, fmt: str, kbps: int) -> bytes:
    codec = ["-c:a", "libopus", "-b:a", f"{kbps}k", "-vbr", "on", "-application", "audio",
             "-f", "ogg"] if fmt == "opus" else ["-c:a", "aac", "-b:a", f"{kbps}k", "-f", "mp4",
                                                 "-movflags", "frag_keyframe+empty_moov"]
    cmd = [ffmpeg_path() or "ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "2",
           "-i", "pipe:0", "-ar", "48000", *codec, "pipe:1"]
    r = subprocess.run(cmd, input=np.ascontiguousarray(pcm.T, dtype=np.float32).tobytes(),
                       capture_output=True, check=True, timeout=120)
    return r.stdout


def encode_segment(pcm: NDArray, sr: int, fmt: str = "opus", pre: int = 0, post: int = 0,
                   kbps: int | None = None) -> Encoded:
    """Encode (2, n) float samples. `pre` and `post` are the context samples already included in
    `pcm`; the result reports them at the output rate (48 kHz for the lossy formats)."""
    x = np.clip(np.asarray(pcm, dtype=np.float32), -1.0, 1.0)
    n = x.shape[1]
    if fmt == "flac":
        b = io.BytesIO()
        sf.write(b, x.T, sr, format="FLAC", subtype="PCM_24")
        return Encoded(b.getvalue(), "flac", sr, pre, post, n - pre - post)
    if fmt not in ("opus", "aac"):
        raise ValueError(f"unknown format {fmt!r}")
    out_sr = 48000
    scale = out_sr / sr
    if ffmpeg_path():
        data = _ffmpeg_encode(x, sr, fmt, kbps or (OPUS_KBPS if fmt == "opus" else AAC_KBPS))
    elif fmt == "opus":
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(out_sr, sr)
        y = resample_poly(x, out_sr // g, sr // g, axis=1).astype(np.float32)
        b = io.BytesIO()
        sf.write(b, y.T, out_sr, format="OGG", subtype="OPUS")
        data = b.getvalue()
    else:
        raise RuntimeError("AAC needs ffmpeg, which is not on this machine")
    return Encoded(data, fmt, out_sr, int(round(pre * scale)), int(round(post * scale)),
                   int(round(n * scale)) - int(round(pre * scale)) - int(round(post * scale)))


def decode(data: bytes) -> tuple[NDArray[np.float32], int]:
    """Decode with libsndfile (Ogg Opus, FLAC) or ffmpeg (anything else); (2, n), rate."""
    try:
        x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        return x.T, sr
    except Exception:
        if not ffmpeg_path():
            raise
        r = subprocess.run([ffmpeg_path(), "-v", "error", "-i", "pipe:0", "-f", "f32le", "-ac",
                            "2", "-ar", "48000", "pipe:1"], input=data, capture_output=True,
                           check=True, timeout=120)
        return np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, 2).T, 48000
