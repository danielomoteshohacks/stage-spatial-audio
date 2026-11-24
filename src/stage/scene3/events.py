"""Musical events that move objects, and the eased paths they follow (decision 0024).

v2 moved a few objects on a constant sinusoid. v3 moves objects when the music does something:

* **riser**: a rise in high-band energy over a bar or more that ends at a section boundary; the
  effects object climbs overhead and the pads lift with it, then settle;
* **fill**: a burst of tom hits (or a dense snare bar); the toms sweep across the front arc
  from one side to the other, once, over the fill;
* **throw**: an isolated burst on the effects leaf (a delay throw, an ad-lib tail); it flies
  from its place to behind the listener and returns.

Every path is a list of keyframes (time, offset) eased with smoothstep between keys and zero
outside the first and last. Times are snapped to the beat grid. Speed and range are capped for
comfort (`cap_keys`): the peak speed of a smoothstep between two keys is 1.5 times the average,
and when a path would exceed the cap its amplitude is reduced (never its timing: the move must
land on the beat), so a fill that is too fast for the cap becomes a narrower sweep.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, sosfiltfilt

SMOOTHSTEP_PEAK = 1.5  # peak derivative of 3x^2 - 2x^3 on [0, 1]


def smoothstep(x: NDArray) -> NDArray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def eased_path(keys: list[list[float]], times: NDArray) -> NDArray[np.float64]:
    """Offset at `times` for keyframes [[t0, v0], [t1, v1], ...]; zero outside the keys."""
    t = np.asarray(times, dtype=np.float64)
    out = np.zeros_like(t)
    for (ta, va), (tb, vb) in zip(keys[:-1], keys[1:], strict=True):
        sel = (t >= ta) & (t < tb)
        if np.any(sel):
            out[sel] = va + (vb - va) * smoothstep((t[sel] - ta) / max(tb - ta, 1e-6))
    if keys and keys[-1][0] <= float(t.max(initial=0.0)):
        out[t >= keys[-1][0]] = keys[-1][1]
    return out


def peak_speed(keys: list[list[float]]) -> float:
    """Peak speed (units per second) of an eased path."""
    best = 0.0
    for (ta, va), (tb, vb) in zip(keys[:-1], keys[1:], strict=True):
        best = max(best, SMOOTHSTEP_PEAK * abs(vb - va) / max(tb - ta, 1e-6))
    return best


def cap_keys(keys: list[list[float]], max_speed: float, max_range: float) -> list[list[float]]:
    """Scale a path's amplitude so its peak speed and its total range respect the caps."""
    amp = max(abs(v) for _, v in keys) or 1.0
    k = min(1.0, max_range / amp)
    sp = peak_speed(keys) * k
    if sp > max_speed:
        k *= max_speed / sp
    return [[t, round(v * k, 2)] for t, v in keys]


def snap(t: float, beats: list[float]) -> float:
    if not beats:
        return t
    b = np.asarray(beats)
    return float(b[int(np.argmin(np.abs(b - t)))])


def envelope_db(x: NDArray, sample_rate: int, hop_s: float = 0.05, above_hz: float = 0.0
                ) -> NDArray:
    mono = np.mean(x, axis=0) if x.ndim > 1 else x
    if above_hz > 0:
        sos = butter(2, above_hz, "highpass", fs=sample_rate, output="sos")
        mono = sosfiltfilt(sos, mono)
    hop = max(int(hop_s * sample_rate), 1)
    m = mono[: mono.size // hop * hop].reshape(-1, hop)
    return 10.0 * np.log10(np.mean(m**2, axis=1) + 1e-12)


def detect_events(leaves: dict[str, NDArray], sample_rate: int, beats_s: list[float],
                  boundaries_s: list[float], tempo_bpm: float, roles: dict[str, str],
                  max_speed: float = 90.0, max_range: float = 100.0, depth: float = 1.0
                  ) -> list[dict[str, Any]]:
    """Events from the leaves; each names the *role* it moves, and carries az and el keyframes."""
    beat = 60.0 / max(tempo_bpm, 1.0)
    events: list[dict[str, Any]] = []
    hop_s = 0.05

    # Risers. With an effects leaf: a stretch of at least one second where its envelope rises
    # 6 dB or more from the first third to the last third. Without one: high-band energy of the
    # whole mix rising 8 dB or more over a bar into a section boundary (a weaker cue, so the
    # monotonic check tolerates 6 dB dips).
    def add_riser(t0: float, t1: float) -> None:
        t0, t1 = snap(t0, beats_s), snap(t1, beats_s)
        if t1 - t0 < beat:
            return
        events.append({"type": "riser", "role": "fx", "t0": t0, "t1": t1,
                       "el": cap_keys([[t0, 0.0], [t1, 25.0], [t1 + beat, 0.0]], max_speed,
                                      max_range * 0.5),
                       "az": [[t0, 0.0], [t1 + beat, 0.0]]})
        events.append({"type": "lift", "role": "pad", "t0": t0, "t1": t1,
                       "el": cap_keys([[t0, 0.0], [t1, 18.0], [t1 + 2 * beat, 0.0]],
                                      max_speed, max_range * 0.5),
                       "az": [[t0, 0.0], [t1 + 2 * beat, 0.0]]})

    fx_names = [k for k, r in roles.items() if r == "fx" and k in leaves]
    riser_spans: list[tuple[float, float]] = []
    for name in fx_names:
        e = np.convolve(envelope_db(leaves[name], sample_rate, hop_s), np.ones(4) / 4, "same")
        if e.max() < -50:
            continue
        idx = np.flatnonzero(e > e.max() - 25.0)
        for g in np.split(idx, np.flatnonzero(np.diff(idx) > int(0.5 / hop_s)) + 1):
            if g.size < int(1.0 / hop_s):
                continue
            third = max(g.size // 3, 1)
            if e[g[-third:]].mean() - e[g[:third]].mean() >= 6.0:
                add_riser(g[0] * hop_s, g[-1] * hop_s)
                riser_spans.append((g[0] * hop_s, g[-1] * hop_s))
    if not fx_names:
        total = sum(leaves.values())
        env = envelope_db(total, sample_rate, hop_s, above_hz=3000.0)
        smooth = np.convolve(env, np.ones(6) / 6, mode="same")
        bar = 4 * beat
        win = max(int(bar / hop_s), 2)
        for b in boundaries_s:
            i1 = int(b / hop_s)
            i0 = i1 - win
            if i0 < 0 or i1 > smooth.size:
                continue
            seg = smooth[i0:i1]
            if seg.size > 3 and seg[-3:].mean() - seg[:3].mean() >= 8.0 and np.all(
                    np.diff(seg[:: max(win // 6, 1)]) > -6.0):
                add_riser(b - bar, b)

    # Fills: stretches where the toms leaf (or a dense snare) is active.
    for name, role in roles.items():
        if role != "toms" or name not in leaves:
            continue
        e = envelope_db(leaves[name], sample_rate, 0.02)
        act = e > e.max() - 30.0
        if not np.any(act):
            continue
        idx = np.flatnonzero(act)
        groups = np.split(idx, np.flatnonzero(np.diff(idx) > int(0.6 / 0.02)) + 1)
        flip = 1.0
        for g in groups:
            if g.size < 4:
                continue
            t0, t1 = snap(g[0] * 0.02, beats_s), snap(g[-1] * 0.02 + 0.2, beats_s)
            if t1 - t0 < 0.3:
                continue
            amp = 60.0 * flip
            flip = -flip
            lead_in = max(t0 - 0.3, 0.0)
            events.append({
                "type": "fill", "role": "toms", "t0": t0, "t1": t1,
                "az": cap_keys([[lead_in, 0.0], [t0, amp], [t1, -amp], [t1 + beat, 0.0]],
                               max_speed, max_range),
                "el": [[lead_in, 0.0], [t1 + beat, 0.0]]})

    # Throws: isolated bursts on the effects leaf.
    for name, role in roles.items():
        if role != "fx" or name not in leaves:
            continue
        e = envelope_db(leaves[name], sample_rate, 0.05)
        if e.max() < -50:
            continue
        act = e > e.max() - 20.0
        idx = np.flatnonzero(act)
        for g in np.split(idx, np.flatnonzero(np.diff(idx) > int(1.0 / 0.05)) + 1):
            if g.size < 3 or g.size > int(2.5 / 0.05):
                continue
            if any(abs(g[0] * 0.05 - r0) < 1.0 for r0, _ in riser_spans):
                continue  # that burst is a riser, not a throw
            t0 = snap(g[0] * 0.05, beats_s)
            t1 = t0 + max(2 * beat, 0.8)
            events.append({"type": "throw", "role": "fx", "t0": t0, "t1": t1,
                           "az": cap_keys([[t0, 0.0], [t1, 70.0], [t1 + 2 * beat, 0.0]],
                                          max_speed, max_range),
                           "el": [[t0, 0.0], [t1 + 2 * beat, 0.0]]})
    for e in events:
        for ax in ("az", "el"):
            e[ax] = [[round(t, 3), round(v * depth, 2)] for t, v in e[ax]]
    return sorted(events, key=lambda e: e["t0"])
