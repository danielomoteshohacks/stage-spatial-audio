"""Objective spatial benchmark: v1 Lite against v2, on generated multitrack songs.

    python scripts/benchmark_spatial.py [--songs 3] [--seconds 30] [--out benchmark.json]

The songs come from stage.testsongs (synth drums, bass, chords, a formant-synthesised voice and
ambience; deterministic, no recordings). Each 30 s excerpt (from 20 s, verse into chorus) is
rendered by:

* v1 Lite: the v1 `max` profile, RMS-matched as the v1 pipeline does;
* v2 Lite: the v2 scene from the whole mix (no separation), studio, Pop template;
* v2 stems: the v2 scene from the song's true stems (the separator is benchmarked on its own by
  scripts/eval_separation.py), Pop template, motion depth 0.5, in the studio and in the living
  room (the default space).

Metrics, all from the binaural output against the original:

* Externalisation proxies. IACC: the maximum of the normalised interaural cross-correlation
  within +/-1 ms over the whole excerpt, 500 Hz to 4 kHz (ISO 3382-1 style; a headphone-stereo
  signal of centred sound reads near 1, a sound outside the head lower). ILD spread and ITD spread:
  the standard deviation over time-frequency tiles of the interaural level difference (1/3-octave
  bands above 1.5 kHz) and of the interaural time difference from the phase (bands below
  1.5 kHz): wider spreads mean sources at more distinct places. DRR estimate: the render fitted
  as a 5 ms filter of the original mid; fitted energy over residual energy in dB (lower means
  more room around the direct sound).
* Envelopment proxies. Lateral energy: the share of the render's energy in the side signal
  (L - R)/2 between 250 Hz and 4 kHz, the binaural analogue of the lateral energy fraction.
  Coherence over time: mean and standard deviation of the interaural coherence in 100 ms frames,
  500 Hz to 4 kHz; lower mean with movement over time is the envelopment cue.
* Fidelity, from the guard report (stage.guard.report): timbre deviation, artifact flags, bass
  identity below 120 Hz, loudness difference in LU, and render time on this machine.

None of these is a perceptual result; the blind test in the web app is.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stage.analysis.stft import stft  # noqa: E402
from stage.guard.levels import match_rms  # noqa: E402
from stage.guard.report import build_report  # noqa: E402
from stage.render.profiles import render_profile  # noqa: E402
from stage.scene.analysis import analyse_song  # noqa: E402
from stage.scene.plan import build_plan  # noqa: E402
from stage.scene.render import render_scene  # noqa: E402
from stage.testsongs import make_song  # noqa: E402

SONGS = ((0, 112.0), (1, 124.0), (2, 98.0), (3, 106.0), (4, 118.0))


def band(x: np.ndarray, sr: int, lo: float, hi: float) -> np.ndarray:
    return sosfiltfilt(butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos"), x, axis=-1)


def iacc(y: np.ndarray, sr: int) -> float:
    b = band(y, sr, 500.0, 4000.0)
    n = b.shape[1]
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    xc = np.fft.irfft(np.fft.rfft(b[0], nfft) * np.conj(np.fft.rfft(b[1], nfft)), nfft)
    lag = int(round(0.001 * sr))
    window = np.concatenate([xc[: lag + 1], xc[-lag:]])
    return float(np.max(np.abs(window)) / np.sqrt(np.sum(b[0] ** 2) * np.sum(b[1] ** 2)))


def ild_itd_spread(y: np.ndarray, sr: int) -> tuple[float, float]:
    spec = stft(y, n_fft=2048, hop=1024)
    freqs = np.fft.rfftfreq(2048, 1 / sr)
    p = np.abs(spec) ** 2
    loud = p.sum(axis=0) > 1e-6 * p.sum(axis=0).max()
    hi = (freqs > 1500) & (freqs < 12000)
    ild = 10 * np.log10((p[0] + 1e-12) / (p[1] + 1e-12))
    lo = (freqs > 200) & (freqs < 1500)
    ipd = np.angle(spec[0] * np.conj(spec[1]))
    itd = ipd[:, lo] / (2 * np.pi * freqs[lo]) * 1e6  # microseconds
    return float(np.std(ild[:, hi][loud[:, hi]])), float(np.std(itd[loud[:, lo]]))


def drr_estimate(orig: np.ndarray, y: np.ndarray, sr: int, ms: float = 5.0) -> float:
    """Fit y (each ear) as a short filter of the original mid; fitted over residual energy."""
    mid = orig.mean(axis=0)
    taps = int(ms * 1e-3 * sr)
    n = mid.size
    nfft = 1 << int(np.ceil(np.log2(n + taps)))
    m = np.fft.rfft(mid, nfft)
    fitted = resid = 0.0
    for ear in y:
        e = np.fft.rfft(ear, nfft)
        # Wiener (least-squares) filter in the frequency domain, smoothed to `taps` in time.
        h = np.fft.irfft(e * np.conj(m) / (np.abs(m) ** 2 + 1e-9 * np.max(np.abs(m) ** 2)), nfft)
        h[taps:] = 0.0
        est = np.fft.irfft(np.fft.rfft(h, nfft) * m, nfft)[:n]
        fitted += float(np.sum(est**2))
        resid += float(np.sum((ear - est) ** 2))
    return 10 * np.log10(fitted / max(resid, 1e-12))


def lateral_energy(y: np.ndarray, sr: int) -> float:
    b = band(y, sr, 250.0, 4000.0)
    side = (b[0] - b[1]) / 2
    return float(np.sum(side**2) / np.sum(b**2) * 2)


def coherence_over_time(y: np.ndarray, sr: int, frame_s: float = 0.1) -> tuple[float, float]:
    b = band(y, sr, 500.0, 4000.0)
    n = int(frame_s * sr)
    vals = []
    for i in range(0, b.shape[1] - n, n):
        a, c = b[0, i : i + n], b[1, i : i + n]
        den = np.sqrt(np.sum(a**2) * np.sum(c**2))
        if den > 1e-9:
            vals.append(abs(float(np.sum(a * c) / den)))
    return float(np.mean(vals)), float(np.std(vals))


def metrics(orig: np.ndarray, y: np.ndarray, sr: int, seconds: float) -> dict:
    r = build_report(orig, y, sr, {"engine": "benchmark"})
    ild_s, itd_s = ild_itd_spread(y, sr)
    coh_m, coh_s = coherence_over_time(y, sr)
    return {
        "iacc": round(iacc(y, sr), 3),
        "ild_spread_db": round(ild_s, 2),
        "itd_spread_us": round(itd_s, 1),
        "drr_estimate_db": round(drr_estimate(orig, y, sr), 2),
        "lateral_energy": round(lateral_energy(y, sr), 3),
        "coherence_mean": round(coh_m, 3),
        "coherence_std": round(coh_s, 3),
        "timbre_dev_db": r["timbre_deviation_db"],
        "artifact_flags": len(r["artifact_flags"]),
        "low_end_corr": r["low_end"]["identity_corr"],
        "loudness_diff_lu": round(abs(r["loudness_lufs"]["render"]
                                      - r["loudness_lufs"]["original"]), 2),
        "verdict": r["verdict"],
    }


CONFIGS = ("v1 Lite", "v2 Lite", "v2 stems", "v2 stems, living room")


def render(name: str, mix: np.ndarray, sr: int, stems: dict, analysis_mix, analysis_stems
           ) -> np.ndarray:
    if name == "v1 Lite":
        return match_rms(render_profile(mix, sr, "max"), float(np.sqrt(np.mean(mix**2))))
    if name == "v2 Lite":
        plan = build_plan(analysis_mix, track_id="b", mode="lite", genre="pop", space="studio",
                          motion_depth=0.5)
        return render_scene(mix, sr, plan, None).binaural
    space = "living_room" if "living room" in name else "studio"
    plan = build_plan(analysis_stems, track_id="b", mode="stems", genre="pop", space=space,
                      motion_depth=0.5)
    return render_scene(mix, sr, plan, stems).binaural


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--songs", type=int, default=5)
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--out", default="benchmark_spatial.json")
    args = ap.parse_args()
    rows = []
    for seed, tempo in SONGS[: args.songs]:
        song = make_song(seed=seed, tempo_bpm=tempo)
        sr = song.sample_rate
        a, b = int(20 * sr), int((20 + args.seconds) * sr)
        mix = song.mix[:, a:b]
        stems = {k: v[:, a:b] for k, v in song.stems.items()}
        analysis_mix = analyse_song(mix, sr)
        analysis_stems = analyse_song(mix, sr, stems)

        for name in CONFIGS:
            job = (name, mix, sr, stems, analysis_mix, analysis_stems)
            if seed == SONGS[0][0] and name != "v1 Lite":
                render(*job)  # warm the room caches, so the time is the render, not the room build
            t0 = time.perf_counter()
            y = render(*job)
            dt = time.perf_counter() - t0
            m = metrics(mix, y, sr, args.seconds)
            m.update(config=name, song=seed, render_s=round(dt, 2))
            rows.append(m)
            print(json.dumps(m), flush=True)
    Path(args.out).write_text(json.dumps({"machine": platform.processor() or platform.machine(),
                                          "rows": rows}, indent=2))
    keys = ["iacc", "ild_spread_db", "itd_spread_us", "drr_estimate_db", "lateral_energy",
            "coherence_mean", "coherence_std", "timbre_dev_db", "artifact_flags", "low_end_corr",
            "loudness_diff_lu", "render_s"]
    configs = CONFIGS
    print("\n| Metric | Better | " + " | ".join(configs) + " |")
    print("|---|---|" + "---|" * len(configs))
    better = {"iacc": "lower", "ild_spread_db": "higher", "itd_spread_us": "higher",
              "drr_estimate_db": "lower (more room)", "lateral_energy": "higher",
              "coherence_mean": "lower", "coherence_std": "higher", "timbre_dev_db": "lower",
              "artifact_flags": "lower", "low_end_corr": "higher", "loudness_diff_lu": "lower",
              "render_s": "lower"}
    for k in keys:
        vals = [np.mean([r[k] for r in rows if r["config"] == c]) for c in configs]
        print(f"| {k} | {better[k]} | " + " | ".join(f"{v:.3g}" for v in vals) + " |")
    verdicts = {c: [r["verdict"] for r in rows if r["config"] == c] for c in configs}
    print(f"\nguard verdicts: {verdicts}")


if __name__ == "__main__":
    main()
