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
from stage.scene3.fastconv import convolve_feeds
from stage.scene3.fastdsp import fast_match_loudness, fast_split
from stage.scene3.plan import object_paths
from stage.spatial.hrtf import BASE_DELAY, HrtfSet, get_hrtf
from stage.spatial.neutral import timbre_filter
from stage.spatial.room import Brir, brir, get_space
from stage.spatial.upmix import apply_width, centre_sides, limit_peaks, width_filter

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


def _trim(h: NDArray, max_s: float, sr: int) -> NDArray[np.float32]:
    """The response cut at `max_s` (the dry stage has nothing after 80 ms), as float32."""
    return np.ascontiguousarray(h[:, : int(max_s * sr)], dtype=np.float32)


@lru_cache(maxsize=1024)
def _filter(space: str, sr: int, az: float, el: float, dist: float, directional_db: float,
            head: str, early: bool) -> NDArray[np.float32]:
    """direct + early reflections (or the direct sound alone) as a trimmed float32 filter."""
    b = _brir3(space, sr, az, el, dist, (), directional_db, head)
    return _trim(b.direct + b.early if early else b.direct, 0.1, sr)


@lru_cache(maxsize=16)
def _centre_filter(space: str, sr: int, head: str) -> NDArray[np.float32]:
    """A flat, equal impulse in both ears at the time and energy of the head filter straight
    ahead, so the untouched centre lines up with the sides rendered through head filters."""
    ref = _filter(space, sr, 0.0, 0.0, 1.5, 0.0, head, False)
    h = np.zeros_like(ref)
    at = int(np.argmax(np.abs(ref).sum(axis=0)))
    h[:, at] = float(np.sqrt(np.mean(np.sum(ref.astype(np.float64) ** 2, axis=1))))
    return h


def render_v3(audio: NDArray, sample_rate: int, plan: dict[str, Any],
              leaves: dict[str, NDArray], returns: dict[str, NDArray] | None = None,
              export_bed: bool = False, directional_db: float = 0.0, want_objects: bool = True,
              t0_s: float = 0.0, timings: dict[str, float] | None = None) -> SceneResult:
    """Render a v3 plan. `leaves` and `returns` (the dereverberated parts' reverb) are (2, n).

    `want_objects=False` skips the per-object stems (the streaming path), which lets sources that
    share a filter be summed before they are convolved. `t0_s` is the time of the first sample
    in the song, so events and breathing follow the song's clock when a chunk is rendered alone.
    `timings`, if given, receives seconds per stage.
    """
    t_start = time.perf_counter()
    tm = timings if timings is not None else {}

    def tick(name: str, t: float) -> float:
        now = time.perf_counter()
        tm[name] = tm.get(name, 0.0) + now - t
        return now

    t = time.perf_counter()
    audio = np.asarray(audio, dtype=np.float32)
    sr = int(sample_rate)
    n = audio.shape[1]
    space = plan.get("space", "dry_stage")
    head = str(plan.get("hrtf") or "D1")
    hs = get_hrtf(sr, head=head)
    crossover = float(plan.get("crossover_hz", 120.0))
    low, high_mix = fast_split(audio, sr, crossover)
    block_times = t0_s + (np.arange((n + HOP - 1) // HOP + 1) * HOP + BLOCK / 2) / sr
    openness = openness_at(plan, block_times)
    bed = _Bed(n, export_bed)
    t = tick("split", t)

    # Gather every source: static ones go to the batched convolver, moving ones are rendered
    # block by block.
    feeds: list[tuple[int, NDArray, tuple, NDArray]] = []  # object index, signal, key, filter
    centre_record = plan.get("centre", "record") == "record"
    moving_out: dict[int, NDArray] = {}
    moving = 0
    names = [o["name"] for o in plan["stems"]]
    for oi, obj in enumerate(plan["stems"]):
        gain = distance_gain(float(obj["dist"])) * 10.0 ** (float(obj.get("gain_db", 0.0)) / 20.0)
        dist = float(obj["dist"])
        if obj["kind"] == "return":
            src = (returns or {}).get(obj["leaf"].split("~")[0])
            if src is None:
                continue
            high = np.asarray(src, dtype=np.float32)  # full band: the crossover comes after
            gate = transient_gate(high, sr)
            for i, f in enumerate(obj["feeds"]):
                ch = 0 if f["ch"] == "L" else 1
                d = _highpass(decorrelate(high[ch], seed=211 * (ch + 1) + 17 * i, sample_rate=sr,
                                          gate=gate), sr)
                sig = (d * np.sqrt(f["weight"]) * gain).astype(np.float32)
                key = (space, sr, round(f["az"], 1), round(f["el"], 1), directional_db, head,
                       "direct")
                feeds.append((oi, sig, key, _filter(space, sr, round(f["az"], 1),
                                                    round(f["el"], 1), 1.5, directional_db, head,
                                                    False)))
                bed.add(sig, f["az"], f["el"])
            continue
        if obj["leaf"] not in leaves:
            continue
        # The leaf goes in full band: the head filters and reflections are linear, so removing
        # everything below the crossover from their *sum* (one filtering) equals filtering each
        # leaf first (15 filterings).
        high = np.asarray(leaves[obj["leaf"]], dtype=np.float32)
        mono = _mono(high) if any(f["ch"] == "M" for f in obj["feeds"]) else None
        # Centre and sides of the part (decision 0031), computed once per object.
        parts = (centre_sides(high, sr) if any(f["ch"] in ("C", "Ls", "Rs") for f in obj["feeds"])
                 else None)
        dynamic = bool(obj.get("events")) or bool(obj.get("breathes"))
        paths = object_paths(obj, plan, block_times, openness) if dynamic else None
        for i, f in enumerate(obj["feeds"]):
            src_sig = (mono if f["ch"] == "M" else parts[f["ch"]] if f["ch"] in ("C", "Ls", "Rs")
                       else high[0 if f["ch"] == "L" else 1])
            sig = (gain * src_sig).astype(np.float32)
            still = not (dynamic and (np.ptp(paths[i][0]) > 0.5 or np.ptp(paths[i][1]) > 0.5))
            if (centre_record and still and f["ch"] in ("C", "M")
                    and abs(float(f["az"])) < 1.0 and abs(float(f["el"])) <= 15.0):
                # The record's centre, as the record has it (decision 0032): the vocal, the kick
                # and snare and whatever else was mixed to the middle reach both ears at once,
                # exactly as in the stereo mix, with no head filter on them. Only what was beside
                # the listener in the mix is moved around them.
                feeds.append((oi, sig, ("record-centre", sr, head),
                              _centre_filter(space, sr, head)))
                bed.add(sig, 0.0, 0.0)
                continue
            if not still:
                az_b, el_b = paths[i]
                y = render_path(sig, az_b, el_b, dist, hs, directional_db).astype(np.float32)
                moving_out[oi] = moving_out.get(oi, 0.0) + y
                ma, me = round(float(np.mean(az_b)), 1), round(float(np.mean(el_b)), 1)
                # The reflections of a moving source are those of its mean position.
                early_only = _filter(space, sr, ma, me, round(dist, 2), directional_db, head,
                                     True).copy()
                early_only[:, : int(0.002 * sr)] = 0.0  # the direct sound is already in `y`
                feeds.append((oi, sig, (space, sr, ma, me, round(dist, 2), directional_db, head,
                                        "early"), early_only))
                bed.add(sig, ma, me)
                moving += 1
            else:
                a0 = round(float(paths[i][0][0]) if dynamic else float(f["az"]), 1)
                e0 = round(float(paths[i][1][0]) if dynamic else float(f["el"]), 1)
                feeds.append((oi, sig, (space, sr, a0, e0, round(dist, 2), directional_db, head,
                                        "full"),
                              _filter(space, sr, a0, e0, round(dist, 2), directional_db, head,
                                      True)))
                bed.add(sig, a0, e0)
    t = tick("sources", t)

    objects_out: dict[str, NDArray] = {}
    if want_objects:
        outs = convolve_feeds([f[1] for f in feeds], [f[2] for f in feeds], [f[3] for f in feeds],
                              n, per_feed=True)
        acc: dict[int, NDArray] = {}
        for (oi, *_), y in zip(feeds, outs, strict=True):
            acc[oi] = acc.get(oi, 0.0) + y[:, BASE_DELAY : BASE_DELAY + n]
        for oi, y in moving_out.items():
            acc[oi] = acc.get(oi, 0.0) + y
        for oi, y in acc.items():
            objects_out[names[oi]] = y.astype(np.float32)
        for k in objects_out:
            objects_out[k] = fast_split(objects_out[k], sr, crossover)[1]
        total = sum(objects_out.values()) if objects_out else np.zeros((2, n), np.float32)
    else:
        groups: dict[tuple, list] = {}
        for _, sig, key, filt in feeds:
            g = groups.setdefault(key, [np.zeros(n, np.float32), filt])
            g[0][: sig.size] += sig[:n]
        keys = list(groups)
        out = convolve_feeds([groups[k][0] for k in keys], keys, [groups[k][1] for k in keys], n)
        total = out[:, BASE_DELAY : BASE_DELAY + n].copy()
        for y in moving_out.values():
            total += y
        total = fast_split(total, sr, crossover)[1]
    t = tick("convolve", t)

    # Width (decision 0031): never narrower than the record. The side channel is lifted per band
    # before the timbre match, which then sees (and keeps) the final balance.
    hw, width = width_filter(high_mix, total, sr)
    total = apply_width(total, hw)
    for k in objects_out:
        objects_out[k] = apply_width(objects_out[k], hw)
    # Neutrality: one timbre filter and one gain for the whole upper band and every object stem.
    h, timbre = timbre_filter(high_mix, total, sr)
    h32 = np.asarray(h, dtype=np.float32)[np.newaxis]
    upper = fftconvolve(total, h32, axes=-1)[:, :n]
    upper_m, gain_u = fast_match_loudness(audio, low, upper, sr)
    timbre["upper_gain_db"] = round(20.0 * float(np.log10(gain_u)), 2)
    for k in objects_out:
        objects_out[k] = (gain_u * fftconvolve(objects_out[k], h32, axes=-1)[:, :n]).astype(
            np.float32)
    if bed.data is not None:
        bed.data[bed.names.index("L")] += low[0]
        bed.data[bed.names.index("R")] += low[1]
    t = tick("neutral", t)
    binaural, limit_db = limit_peaks(low + upper_m, sr)
    return SceneResult(binaural=binaural, objects=objects_out,
                       bed=bed.data, info={
        "engine": "v3-objects", "hrtf": hs.name, "head": head, "space": space,
        "crossover_hz": crossover, "timbre_match": timbre, "width_match": width,
        "limiter_db": limit_db, "objects": names,
        "moving_sources": moving, "directional_db": directional_db, "late_field": False,
        "render_s": round(time.perf_counter() - t_start, 3), "stage_s": {
            k: round(v, 3) for k, v in tm.items()}})


@lru_cache(maxsize=256)
def _direct_only(space: str, sr: int, az: float, el: float, directional_db: float,
                 head: str = "D1") -> Brir:
    b = _brir3(space, sr, round(az, 1), round(el, 1), 1.5, (), directional_db, head)
    return Brir(direct=b.direct, early=np.zeros_like(b.early), late=b.late)


__all__ = ["render_v3", "openness_at", "direct_early_shares", "directional_curve_db"]
