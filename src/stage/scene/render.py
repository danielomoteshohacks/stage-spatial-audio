"""The v2 scene renderer: stems (or the whole mix) and a plan in, binaural out.

Decisions 0016 to 0018. For each stem in turn (only one stem's full-band arrays are alive at a
time):

1. **Bass bypass.** The zero-phase Linkwitz-Riley split at the plan's crossover; the lows of all
   stems sum to the low band of the mix, which is passed through untouched at the end.
2. **Decomposition of the upper band.** Harmonic/percussive separation by median filtering
   (Fitzgerald 2010, "Harmonic/percussive separation using median filtering", DAFx), with the
   percussive part defined as the remainder so the two sum exactly; then the primary/ambient
   split of the harmonic part (stage.analysis.stereo, after Avendano and Jot). Transients stay
   in the direct path and are only ever filtered by fixed or slowly cross-faded head and room
   responses, never by a per-bin gain, so they are not smeared in time.
3. **Objects to virtual sources.** Every plan object becomes one virtual source per channel at
   az +/- spread / 2 (the record's own left/right image stays inside the pair, so the artist's
   placement is kept), at its distance, through the binaural room (stage.spatial.room) with its
   room send. Objects with a wide setting cross-fade between a narrow and a wide pair as the
   sections open (verses tighter, choruses and drops wider and higher). Ambient objects without a
   spread open into the surround and height bed: velvet-noise decorrelated copies at the 7.1.4
   side, rear and top positions, with transient gating.
4. **Motion.** Moving objects follow their tempo-locked path; their direct sound is rendered in
   50 percent overlapped Hann blocks of 1024 samples, each through the head filter at that
   block's direction, so the filter changes smoothly (the head filters are continuous in azimuth
   to 0.5 dB per degree, decision 0012). Their reflections and late field are those of the mean
   position.
5. **Distance.** Level falls as the square root of distance from a 1.5 m reference (a gentle law
   that keeps the mix balance; the full inverse law would rewrite it), the direct-to-reverberant
   ratio follows the room (0013), air absorption is applied along the direct path (ISO 9613-1),
   and below 1 m an extra interaural level difference is added at low and mid frequencies, the
   near-field cue of a spherical head (Duda and Martens 1998; Brungart and Rabinowitz 1999).
6. **Neutrality** (0014): the timbre matcher and the upper-band loudness match, then the
   original low band added back.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import median_filter
from scipy.signal import butter, fftconvolve, oaconvolve, sosfilt

from stage.analysis import analyse_stereo, istft, stft
from stage.scene.decorrelate import decorrelate, transient_gate
from stage.spatial.hrtf import BASE_DELAY, HrtfSet, get_hrtf
from stage.spatial.neutral import match_loudness_upper, split_low_high, timbre_filter
from stage.spatial.room import Brir, air_absorption_db_per_m, brir, get_space

#: The 7.1.4 layout of ITU-R BS.2051 (System J) used for the bed, SOFA azimuths (+ is left).
BED_LAYOUT: dict[str, tuple[float, float] | None] = {
    "L": (30.0, 0.0), "R": (-30.0, 0.0), "C": (0.0, 0.0), "LFE": None,
    "Ls": (90.0, 0.0), "Rs": (-90.0, 0.0), "Lrs": (135.0, 0.0), "Rrs": (-135.0, 0.0),
    "Ltf": (45.0, 45.0), "Rtf": (-45.0, 45.0), "Ltr": (135.0, 45.0), "Rtr": (-135.0, 45.0),
}
#: Bed positions fed by the left and the right ambience, with their layer.
BED_FEEDS = {0: (("Ls", "side"), ("Lrs", "rear"), ("Ltf", "height"), ("Ltr", "height")),
             1: (("Rs", "side"), ("Rrs", "rear"), ("Rtf", "height"), ("Rtr", "height"))}
DISTANCE_REF_M = 1.5
BLOCK = 1024
HOP = BLOCK // 2
#: Share of an ambient bed object's energy kept on the front pair, so the record's own space is
#: still heard where it was mixed; the rest opens into the bed.
BED_FRONT_SHARE = 0.4


@dataclass
class SceneResult:
    binaural: NDArray[np.float64]
    objects: dict[str, NDArray[np.float64]]  # per-object binaural stems (sum + low = binaural)
    bed: NDArray[np.float64] | None  # (12, n) 7.1.4 channels when requested
    info: dict[str, Any] = field(default_factory=dict)


# --- Parts of a stem ---------------------------------------------------------------------------


def hpss(x: NDArray, kernel: int = 17) -> tuple[NDArray, NDArray]:
    """(harmonic, percussive) of (2, n), percussive = x - harmonic exactly."""
    n_fft, hop = 2048, 512
    spec = stft(x, n_fft=n_fft, hop=hop)
    mag = np.abs(spec).mean(axis=0)
    harm = median_filter(mag, size=(kernel, 1), mode="nearest")
    perc = median_filter(mag, size=(1, kernel), mode="nearest")
    mask = harm**2 / (harm**2 + perc**2 + 1e-20)
    h = istft(spec * mask[np.newaxis], x.shape[1], n_fft=n_fft, hop=hop)
    return h, x - h


def primary_ambient(x: NDArray, sample_rate: int) -> tuple[NDArray, NDArray]:
    spec = stft(x)
    a = analyse_stereo(spec[0], spec[1], hop=1024, sample_rate=sample_rate)
    primary = istft(a.primary, x.shape[1])
    return primary, x - primary


def stem_parts(high: NDArray, sample_rate: int) -> dict[str, NDArray]:
    """The parts the plan's sources name: direct, ambient, mid, high, all (each (2, n))."""
    harmonic, percussive = hpss(high)
    primary, ambient = primary_ambient(harmonic, sample_rate)
    mid, top = split_low_high(high, sample_rate, 4000.0)
    return {"direct": primary + percussive, "ambient": ambient, "mid": mid, "high": top,
            "all": high}


# --- Envelopes from the plan -------------------------------------------------------------------


def openness_curve(plan: dict[str, Any], n: int, sample_rate: int) -> NDArray[np.float64]:
    """Per-sample openness from the plan's sections, with a one-bar raised-cosine between them."""
    out = np.full(n, 0.5)
    sections = plan.get("sections") or []
    if not sections:
        return out
    for s in sections:
        a, b = int(s["start_s"] * sample_rate), int(s["end_s"] * sample_rate)
        out[max(0, a) : min(n, b)] = s["openness"]
    out[: int(sections[0]["start_s"] * sample_rate)] = sections[0]["openness"]
    out[int(sections[-1]["end_s"] * sample_rate) :] = sections[-1]["openness"]
    bar = int(4 * 60.0 / plan.get("tempo_bpm", 120.0) * sample_rate)
    if bar > 1:
        k = np.hanning(bar)
        out = np.convolve(np.pad(out, (bar // 2, bar - bar // 2 - 1), mode="edge"), k / k.sum(),
                          mode="valid")[:n]
    return out


def motion_offsets(plan: dict[str, Any], motion: dict[str, Any], times: NDArray) -> NDArray:
    """Azimuth offset (degrees) of a moving object at `times` (seconds)."""
    period = motion["period_bars"] * 4.0 * 60.0 / plan.get("tempo_bpm", 120.0)
    phase = (times - plan.get("first_downbeat_s", 0.0)) / period
    if motion["path"] == "orbit":
        return 360.0 * phase
    return 0.5 * motion["depth"] * np.sin(2.0 * np.pi * phase)


# --- Rendering helpers -------------------------------------------------------------------------


def direct_shaping(hs: HrtfSet, az: float, dist: float) -> NDArray[np.float64]:
    """Extra dB per ear (2, K) on the direct path: air absorption and the near-field ILD."""
    air = -air_absorption_db_per_m(hs.freqs) * dist
    extra = np.stack([air, air])
    if dist < 1.0:
        lateral = float(np.sin(np.radians(az)))  # +1 when the source is on the left
        # Near-field ILD growth of a spherical head: strongest below 1 kHz, about half above
        # 3 kHz (Brungart and Rabinowitz 1999, Fig. 6, read as a trend). SPECULATIVE magnitude.
        w = np.interp(hs.freqs, [0.0, 1000.0, 3000.0, 1e6], [1.0, 1.0, 0.5, 0.5])
        g = abs(lateral) * 10.0 * np.log10(1.0 / max(dist, 0.2)) * w
        near, far = (0, 1) if lateral >= 0 else (1, 0)
        extra[near] += g
        extra[far] -= g
    return extra


#: Reflections, the late field and the decorrelated bed are high-passed here (second order).
#: Around the crossover the untouched bass and the rendered upper band overlap; if the upper band
#: there were reverberant or decorrelated it would add to the bass incoherently and change its
#: level (6.4 dB at 125 Hz in the first Lite scene render). Keeping everything below about 200 Hz
#: direct also keeps the low end from being smeared, as v1's H14b found for early reflections.
ROOM_HIGHPASS_HZ = 200.0


def _highpass(x: NDArray, sr: int) -> NDArray:
    sos = butter(2, ROOM_HIGHPASS_HZ, btype="highpass", fs=sr, output="sos")
    return sosfilt(sos, x, axis=-1)


@lru_cache(maxsize=128)
def _brir(space: str, sr: int, az: float, el: float, dist: float, send: float) -> Brir:
    hs = get_hrtf(sr)
    b = brir(get_space(space), hs, az, el, dist, reverb_scale=send,
             direct_extra_db=direct_shaping(hs, az, dist))
    return Brir(direct=b.direct, early=_highpass(b.early, sr), late=_highpass(b.late, sr))


def render_static(x: NDArray, b: Brir) -> NDArray[np.float64]:
    y = oaconvolve(x[np.newaxis, :], b.total, axes=-1)
    return y[:, BASE_DELAY : BASE_DELAY + x.size]


def render_moving(x: NDArray, az_blocks: NDArray, el: float, dist: float, hs: HrtfSet
                  ) -> NDArray[np.float64]:
    """Direct sound of a moving mono source: per-block head filters, overlap-added Hann blocks."""
    n = x.size
    n_blocks = az_blocks.size
    win = np.hanning(BLOCK + 1)[:BLOCK]  # periodic: sums to 1 at 50 percent overlap
    m = 1 << int(np.ceil(np.log2(BLOCK + hs.n_fft)))
    out = np.zeros((2, n_blocks * HOP + m))
    pad = np.pad(x, (0, n_blocks * HOP + BLOCK - n))
    shaping = direct_shaping(hs, float(np.mean(az_blocks)), dist)
    for c0 in range(0, n_blocks, 256):
        c1 = min(n_blocks, c0 + 256)
        segs = np.stack([pad[k * HOP : k * HOP + BLOCK] * win for k in range(c0, c1)])
        h = hs.hrirs(az_blocks[c0:c1], np.full(c1 - c0, el), shaping[np.newaxis])
        y = np.fft.irfft(np.fft.rfft(segs, m)[:, np.newaxis] * np.fft.rfft(h, m), m)
        for i, k in enumerate(range(c0, c1)):
            out[:, k * HOP : k * HOP + m] += y[i]
    return out[:, BASE_DELAY : BASE_DELAY + n]


def distance_gain(dist: float) -> float:
    return float(np.clip((DISTANCE_REF_M / max(dist, 0.1)) ** 0.5, 0.6, 1.6))


def pan_bed(az: float, el: float) -> dict[str, float]:
    """Power-normalised 7.1.4 gains for one direction: pairwise in the middle and upper rings,
    then between the rings by elevation (a simple VBAP-style panner for the bed export)."""
    def ring(names: list[str]) -> dict[str, float]:
        angs = np.array([BED_LAYOUT[k][0] for k in names])
        order = np.argsort(angs)
        names = [names[i] for i in order]
        angs = angs[order]
        a = (az + 180.0) % 360.0 - 180.0
        ext = np.concatenate([angs, [angs[0] + 360.0]])
        for i in range(len(names)):
            lo, hi = ext[i], ext[i + 1]
            aa = a if a >= lo else a + 360.0
            if lo <= aa <= hi:
                f = (aa - lo) / (hi - lo)
                j = (i + 1) % len(names)
                return {names[i]: float(np.cos(f * np.pi / 2)),
                        names[j]: float(np.sin(f * np.pi / 2))}
        return {names[0]: 1.0}

    mid = ring(["L", "R", "C", "Ls", "Rs", "Lrs", "Rrs"])
    top = ring(["Ltf", "Rtf", "Ltr", "Rtr"])
    f = float(np.clip(el / 45.0, 0.0, 1.0))
    gains = {k: v * np.cos(f * np.pi / 2) for k, v in mid.items()}
    for k, v in top.items():
        gains[k] = gains.get(k, 0.0) + v * np.sin(f * np.pi / 2)
    return {k: float(v) for k, v in gains.items() if abs(v) > 1e-9}


class _Bed:
    """Accumulates the 7.1.4 export (only when asked for)."""

    def __init__(self, n: int, enabled: bool) -> None:
        self.names = list(BED_LAYOUT)
        self.data = np.zeros((len(self.names), n)) if enabled else None

    def add(self, x: NDArray, az: float, el: float) -> None:
        if self.data is None:
            return
        for k, g in pan_bed(az, el).items():
            self.data[self.names.index(k)] += g * x


# --- The renderer ------------------------------------------------------------------------------


def render_scene(audio: NDArray, sample_rate: int, plan: dict[str, Any],
                 stems: dict[str, NDArray] | None = None, export_bed: bool = False
                 ) -> SceneResult:
    """Render the plan. `stems` None (or a Lite plan) renders the whole mix as "mix"."""
    t_start = time.perf_counter()
    audio = np.asarray(audio, dtype=np.float64)
    sr = int(sample_rate)
    n = audio.shape[1]
    space = plan.get("space", "studio")
    get_space(space)  # fail early on an unknown space
    hs = get_hrtf(sr)
    crossover = float(plan.get("crossover_hz", 120.0))
    low, high_mix = split_low_high(audio, sr, crossover)
    openness = openness_curve(plan, n, sr)
    wide_w = np.clip((openness - 0.3) / 0.6, 0.0, 1.0)
    bed_cfg = plan.get("bed", {})
    bed_gain = {"side": bed_cfg.get("ambience", 1.0) * (0.6 + 0.8 * openness),
                "rear": bed_cfg.get("ambience", 1.0) * (0.5 + 0.9 * openness),
                "height": bed_cfg.get("heights", 0.5) * (0.3 + 1.2 * openness)}
    bed = _Bed(n, export_bed)
    objects_out: dict[str, NDArray] = {}
    total = np.zeros((2, n))
    sources = {"mix": audio} if plan.get("mode") == "lite" or not stems else stems
    by_stem: dict[str, list[dict[str, Any]]] = {}
    for obj in plan["stems"]:
        stem_name = obj.get("source", "mix.direct").split(".")[0]
        by_stem.setdefault(stem_name, []).append(obj)
    block_times = (np.arange((n + HOP - 1) // HOP + 1) * HOP + BLOCK / 2) / sr
    moving = 0
    for stem_name, objs in by_stem.items():
        if stem_name not in sources:
            continue
        _, high = split_low_high(np.asarray(sources[stem_name], dtype=np.float64), sr, crossover)
        parts = stem_parts(high, sr)
        del high
        for obj in objs:
            part = obj.get("source", "mix.direct").split(".")[1]
            x = parts[part]
            blend = float(obj.get("orig_blend", 0.0))
            y = np.zeros((2, n))
            g = distance_gain(float(obj["dist"]))
            send = float(obj.get("room_send", 0.5))
            dist = float(obj["dist"])
            is_bed = part == "ambient" and float(obj.get("spread", 0.0)) == 0.0
            if is_bed:
                gate = transient_gate(x, sr)
                front = np.sqrt(BED_FRONT_SHARE)
                for ch, az in ((0, 30.0), (1, -30.0)):
                    sig = front * g * x[ch]
                    y += render_static(sig, _brir(space, sr, az, 0.0, dist, send))
                    bed.add(sig, az, 0.0)
                    for i, (spk, layer) in enumerate(BED_FEEDS[ch]):
                        az_s, el_s = BED_LAYOUT[spk]
                        share = np.sqrt((1.0 - BED_FRONT_SHARE) / 4.0)
                        d = _highpass(decorrelate(x[ch], seed=97 * ch + 13 * i + 7,
                                                  sample_rate=sr, gate=gate), sr)
                        d = d * share * g * bed_gain[layer]
                        y += render_static(d, _brir(space, sr, az_s, el_s, dist, send))
                        bed.add(d, az_s, el_s)
            else:
                spread = float(obj.get("spread", 0.0))
                pairs = [(spread, float(obj["el"]), None)]
                if obj.get("wide"):
                    pairs = [(spread, float(obj["el"]), np.cos(wide_w * np.pi / 2)),
                             (float(obj["wide"]["spread"]), float(obj["wide"]["el"]),
                              np.sin(wide_w * np.pi / 2))]
                motion = obj.get("motion")
                for sp, el, w in pairs:
                    if sp <= 0.0:
                        feeds = [((x[0] + x[1]) / np.sqrt(2.0), 0.0)]
                    else:
                        feeds = [(x[0], sp / 2.0), (x[1], -sp / 2.0)]
                    for sig, off in feeds:
                        sig = g * (sig if w is None else sig * w)
                        az = float(obj["az"]) + off
                        if motion:
                            offs = motion_offsets(plan, motion, block_times)
                            az_blocks = (az + offs + 180.0) % 360.0 - 180.0
                            mean_az = float(az)
                            b = _brir(space, sr, mean_az, el, dist, send)
                            y += render_moving(sig, az_blocks, el, dist, hs)
                            room = b.early + b.late
                            y += oaconvolve(sig[np.newaxis], room, axes=-1)[
                                :, BASE_DELAY : BASE_DELAY + n]
                            moving += 1
                            bed.add(sig, mean_az, el)
                        else:
                            y += render_static(sig, _brir(space, sr, az, el, dist, send))
                            bed.add(sig, az, el)
            if blend > 0.0:
                # The original's own stereo of this part, unprocessed, kept in the object stem.
                y = (1.0 - blend) * y + blend * x
            objects_out[obj["name"]] = objects_out.get(obj["name"], 0.0) + y
            total += y
        del parts
    # Neutrality: one correction filter and one gain for the whole upper band and for every
    # object stem, so the object stems still sum to the render.
    upper = total
    h, timbre = timbre_filter(high_mix, upper, sr)
    upper = fftconvolve(upper, h[np.newaxis], axes=-1)[:, :n]
    upper_m, gain = match_loudness_upper(audio, low, upper, sr)
    timbre["upper_gain_db"] = round(20.0 * float(np.log10(gain)), 2)
    for k in objects_out:
        objects_out[k] = gain * fftconvolve(objects_out[k], h[np.newaxis], axes=-1)[:, :n]
    if bed.data is not None:
        bed.data[bed.names.index("L")] += low[0]
        bed.data[bed.names.index("R")] += low[1]
    binaural = low + upper_m
    return SceneResult(binaural=binaural, objects=objects_out, bed=bed.data, info={
        "engine": "v2-scene", "hrtf": hs.name, "space": space, "crossover_hz": crossover,
        "timbre_match": timbre, "objects": list(objects_out), "moving_sources": moving,
        "render_s": round(time.perf_counter() - t_start, 3),
    })
