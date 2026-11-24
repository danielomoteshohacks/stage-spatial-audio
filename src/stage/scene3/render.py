"""The v3 object renderer: every leaf a dry point source through the measured HRTF.

Decision 0025. What changes from v2 (stage.scene.render):

* **No virtual loudspeakers, no room send.** Each object is rendered straight to binaural at its
  own azimuth and elevation. The default space is the "Dry stage": the direct sound plus a
  sparse set of early reflections (image sources to order 2, 6 dB under the studio's fitted
  level, all within 80 ms), and no late tail (`brir(..., late=False)`). Externalisation comes
  from the HRTF direction cues, the distance cues and those reflections, as the studies of
  non-individual HRTFs without head tracking ask for (Reed and Maher 2009; Rajendran et al.
  2019), not from reverberation.
* **The record's reverb is returned, not invented.** Level 5 of the cascade splits a part into
  a dry object and its reverb; the reverb is decorrelated (velvet noise, stage.scene.decorrelate)
  and fed to positions at the sides, rear and height at its original level, none in front. This
  is the only reverberation added by default.
* **Paths.** Objects with events or breathing are rendered in 50 percent overlapped Hann blocks
  of 1024 samples, each through the head filter at that block's direction; filters are built
  once per distinct position (1 degree in azimuth, 2 in elevation), which is what makes a moving
  object affordable. Their reflections are those of the mean position.
* **Directional bands.** Optionally, a bounded boost in the bands Blauert (1969, "Sound
  localization in the median plane", Acustica 22; Spatial Hearing, 1997) found to favour a
  direction (front 300-600 Hz and 3-6 kHz, above 7-10 kHz, behind 1-2 kHz and 10-12 kHz), at
  most `DIRECTIONAL_MAX_DB`, equal in both ears so level differences are untouched. The timbre
  matcher that follows keeps the whole render's tone, and the guard checks it.
* **Preserve the record.** The bass bypass (the original low band passes untouched), timbre
  matching and loudness matching are v2's; the guard runs on every render in the pipeline.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.signal import fftconvolve, oaconvolve

from stage.scene.decorrelate import decorrelate, transient_gate
from stage.scene.render import (
    BLOCK,
    HOP,
    SceneResult,
    _Bed,
    _highpass,
    direct_shaping,
    distance_gain,
    openness_curve,
)
from stage.scene3.plan import object_paths
from stage.spatial.hrtf import BASE_DELAY, HrtfSet, get_hrtf
from stage.spatial.neutral import match_loudness_upper, split_low_high, timbre_filter
from stage.spatial.room import Brir, brir, get_space

#: Largest boost of the directional bands, in dB (both ears alike).
DIRECTIONAL_MAX_DB = 2.0
AZ_QUANT = 1.0
EL_QUANT = 2.0


# --- Helpers shared with the planner and the diagnostics ----------------------------------------


def openness_at(plan: dict[str, Any], times: NDArray) -> NDArray:
    t = np.asarray(times, dtype=np.float64)
    dur = float(t.max(initial=0.0)) + 1.0
    curve = openness_curve(plan, int(dur * 100) + 2, 100)
    return np.interp(t, np.arange(curve.size) / 100.0, curve)


def early_scale_for(dist: float) -> float:
    """Reflections grow with distance (a more distant source is nearer the room's critical
    distance), from half to double the space's fitted level."""
    return float(np.clip(dist / 1.5, 0.5, 2.0))


@lru_cache(maxsize=512)
def _brir3(space: str, sr: int, az: float, el: float, dist: float, extra_key: tuple,
           directional_db: float, head: str = "D1") -> Brir:
    hs = get_hrtf(sr, head=head)
    extra = direct_shaping(hs, az, dist)
    if directional_db > 0.0:
        extra = extra + directional_curve_db(hs.freqs, az, el, directional_db)[np.newaxis]
    b = brir(get_space(space), hs, az, el, dist, reverb_scale=0.0,
             early_scale=early_scale_for(dist), direct_extra_db=extra, late=False)
    return Brir(direct=b.direct, early=_highpass(b.early, sr), late=b.late)


def direct_early_shares(plan: dict[str, Any], az: float, el: float, dist: float
                        ) -> tuple[float, float]:
    sr = int(plan.get("analysis_sample_rate", 44100))
    b = _brir3(plan.get("space", "dry_stage"), sr, round(az, 1), round(el, 1), round(dist, 2),
               (), 0.0, str(plan.get("hrtf") or "D1"))
    e_d = float(np.sum(b.direct**2))
    e_e = float(np.sum(b.early**2))
    tot = max(e_d + e_e, 1e-30)
    return e_d / tot, e_e / tot


def directional_curve_db(freqs: NDArray, az: float, el: float, max_db: float) -> NDArray:
    """Blauert's directional bands as a smooth boost in dB (1/3-octave wide Gaussian bumps)."""
    def bump(f0: float, amount: float) -> NDArray:
        return amount * np.exp(-0.5 * (np.log2(np.maximum(freqs, 1.0) / f0) / 0.28) ** 2)

    a = np.radians(az)
    e = np.radians(el)
    front = max(np.cos(a), 0.0) * max(np.cos(e), 0.0)
    above = max(np.sin(e), 0.0)
    behind = max(-np.cos(a), 0.0) * max(np.cos(e), 0.0)
    curve = (front * (0.5 * bump(450.0, 1.0) + 0.5 * bump(4500.0, 1.0))
             + above * bump(8500.0, 1.0)
             + behind * (0.6 * bump(1500.0, 1.0) + 0.4 * bump(11000.0, 1.0)))
    return np.clip(max_db * curve, 0.0, max_db)


def _q(az: NDArray, el: NDArray) -> tuple[NDArray, NDArray]:
    return (np.round(az / AZ_QUANT) * AZ_QUANT,
            np.clip(np.round(el / EL_QUANT) * EL_QUANT, -10.0, 80.0))


# --- Rendering ----------------------------------------------------------------------------------


def render_static(x: NDArray, b: Brir) -> NDArray[np.float64]:
    y = oaconvolve(x[np.newaxis, :], b.direct + b.early, axes=-1)
    return y[:, BASE_DELAY : BASE_DELAY + x.size]


def render_path(x: NDArray, az_blocks: NDArray, el_blocks: NDArray, dist: float, hs: HrtfSet,
                directional_db: float) -> NDArray[np.float64]:
    """Direct sound of a mono source along a path: per-block head filters, overlap-added Hann
    blocks, with one filter per distinct quantised position."""
    n = x.size
    n_blocks = az_blocks.size
    qa, qe = _q(az_blocks, el_blocks)
    pos = np.stack([qa, qe], axis=1)
    uniq, inv = np.unique(pos, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    extra = np.stack([direct_shaping(hs, float(a), dist)
                      + (directional_curve_db(hs.freqs, float(a), float(e), directional_db)[
                          np.newaxis] if directional_db > 0 else 0.0)
                      for a, e in uniq])
    h = hs.hrirs(uniq[:, 0], uniq[:, 1], extra)  # (U, 2, n_fft)
    m = 1 << int(np.ceil(np.log2(BLOCK + hs.n_fft)))
    h_f = np.fft.rfft(h, m)  # (U, 2, m/2+1)
    win = np.hanning(BLOCK + 1)[:BLOCK]
    out = np.zeros((2, n_blocks * HOP + m))
    pad = np.pad(x, (0, n_blocks * HOP + BLOCK - n))
    for c0 in range(0, n_blocks, 256):
        c1 = min(n_blocks, c0 + 256)
        segs = np.stack([pad[k * HOP : k * HOP + BLOCK] * win for k in range(c0, c1)])
        y = np.fft.irfft(np.fft.rfft(segs, m)[:, np.newaxis] * h_f[inv[c0:c1]], m)
        for i, k in enumerate(range(c0, c1)):
            out[:, k * HOP : k * HOP + m] += y[i]
    return out[:, BASE_DELAY : BASE_DELAY + n]


def _mono(x: NDArray) -> NDArray:
    """Mid signal with the energy of the stereo leaf restored, so a hard-panned source is not
    7 dB down when it is rendered as one point source."""
    mid = (x[0] + x[1]) / np.sqrt(2.0)
    e_st = float(np.sum(x**2))
    e_mid = float(np.sum(mid**2))
    g = float(np.clip(np.sqrt(e_st / max(e_mid, 1e-20)), 1.0, 1.6))
    return mid * g


def render_v3(audio: NDArray, sample_rate: int, plan: dict[str, Any],
              leaves: dict[str, NDArray], returns: dict[str, NDArray] | None = None,
              export_bed: bool = False, directional_db: float = 0.0) -> SceneResult:
    """Render a v3 plan. `leaves` and `returns` (the dereverberated parts' reverb) are (2, n)."""
    t_start = time.perf_counter()
    audio = np.asarray(audio, dtype=np.float64)
    sr = int(sample_rate)
    n = audio.shape[1]
    space = plan.get("space", "dry_stage")
    head = str(plan.get("hrtf") or "D1")
    hs = get_hrtf(sr, head=head)
    crossover = float(plan.get("crossover_hz", 120.0))
    low, high_mix = split_low_high(audio, sr, crossover)
    block_times = (np.arange((n + HOP - 1) // HOP + 1) * HOP + BLOCK / 2) / sr
    openness = openness_at(plan, block_times)
    bed = _Bed(n, export_bed)
    objects_out: dict[str, NDArray] = {}
    total = np.zeros((2, n))
    moving = 0
    for obj in plan["stems"]:
        name = obj["name"]
        y = np.zeros((2, n))
        gain = distance_gain(float(obj["dist"])) * 10.0 ** (float(obj.get("gain_db", 0.0)) / 20.0)
        dist = float(obj["dist"])
        if obj["kind"] == "return":
            src = (returns or {}).get(obj["leaf"].split("~")[0])
            if src is None:
                continue
            _, high = split_low_high(np.asarray(src, dtype=np.float64), sr, crossover)
            gate = transient_gate(high, sr)
            for i, f in enumerate(obj["feeds"]):
                ch = 0 if f["ch"] == "L" else 1
                d = _highpass(decorrelate(high[ch], seed=211 * (ch + 1) + 17 * i, sample_rate=sr,
                                          gate=gate), sr)
                sig = d * np.sqrt(f["weight"]) * gain
                # The return is diffuse by design: direct HRTF only, no early reflections.
                y += render_static(sig, _direct_only(space, sr, f["az"], f["el"],
                                                     directional_db, head))
                bed.add(sig, f["az"], f["el"])
        else:
            if obj["leaf"] not in leaves:
                continue
            _, high = split_low_high(np.asarray(leaves[obj["leaf"]], dtype=np.float64), sr,
                                     crossover)
            mono = _mono(high) if any(f["ch"] == "M" for f in obj["feeds"]) else None
            dynamic = bool(obj.get("events")) or bool(obj.get("breathes"))
            paths = object_paths(obj, plan, block_times, openness) if dynamic else None
            for i, f in enumerate(obj["feeds"]):
                sig = gain * (mono if f["ch"] == "M" else high[0 if f["ch"] == "L" else 1])
                if dynamic and (np.ptp(paths[i][0]) > 0.5 or np.ptp(paths[i][1]) > 0.5):
                    az_b, el_b = paths[i]
                    y += render_path(sig, az_b, el_b, dist, hs, directional_db)
                    ma, me = float(np.mean(az_b)), float(np.mean(el_b))
                    room = _brir3(space, sr, round(ma, 1), round(me, 1), round(dist, 2), (),
                                  directional_db, head).early
                    y += oaconvolve(sig[np.newaxis], room, axes=-1)[
                        :, BASE_DELAY : BASE_DELAY + n]
                    bed.add(sig, ma, me)
                    moving += 1
                else:
                    a0 = float(paths[i][0][0]) if dynamic else float(f["az"])
                    e0 = float(paths[i][1][0]) if dynamic else float(f["el"])
                    b = _brir3(space, sr, round(a0, 1), round(e0, 1), round(dist, 2), (),
                               directional_db, head)
                    y += render_static(sig, b)
                    bed.add(sig, a0, e0)
        objects_out[name] = y
        total += y
    # Neutrality: one timbre filter and one gain for the whole upper band and every object stem.
    h, timbre = timbre_filter(high_mix, total, sr)
    upper = fftconvolve(total, h[np.newaxis], axes=-1)[:, :n]
    upper_m, gain_u = match_loudness_upper(audio, low, upper, sr)
    timbre["upper_gain_db"] = round(20.0 * float(np.log10(gain_u)), 2)
    for k in objects_out:
        objects_out[k] = gain_u * fftconvolve(objects_out[k], h[np.newaxis], axes=-1)[:, :n]
    if bed.data is not None:
        bed.data[bed.names.index("L")] += low[0]
        bed.data[bed.names.index("R")] += low[1]
    return SceneResult(binaural=low + upper_m, objects=objects_out, bed=bed.data, info={
        "engine": "v3-objects", "hrtf": hs.name, "space": space, "crossover_hz": crossover,
        "timbre_match": timbre, "objects": list(objects_out), "moving_sources": moving,
        "directional_db": directional_db, "late_field": False,
        "render_s": round(time.perf_counter() - t_start, 3)})


@lru_cache(maxsize=256)
def _direct_only(space: str, sr: int, az: float, el: float, directional_db: float,
                 head: str = "D1") -> Brir:
    b = _brir3(space, sr, round(az, 1), round(el, 1), 1.5, (), directional_db, head)
    return Brir(direct=b.direct, early=np.zeros_like(b.early), late=b.late)


__all__ = ["render_v3", "openness_at", "direct_early_shares", "directional_curve_db"]
