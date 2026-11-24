"""Measure the magnitude response of the renderer's sector chain for fixed pan positions.

Usage:
    python scripts/measure_sector_sum.py [--beta 2.0] [--profile V0] [--step 0.25] [--verify]

A source at stereo angle theta is shared over neighbouring sectors (Gaussian weights), and every
sector has its own ear delay. At each ear the copies add as complex numbers, so two sectors whose
delays differ by tau cancel near 1 / (2 tau): a comb. This script computes, at the renderer's own
STFT bins, the response of that weighted sum for each ear,

    H_sum(f) = sum_k w_k(theta) * F_k(f)      (the primary path of `_render_block`)

and compares it with H_ref(f), the same ear filter at the source's exact widened azimuth (what
a renderer with one filter per bin would apply; decision 0006 used it as the reference too).
The ratio H_sum / H_ref isolates the comb from the head shadow, which is intended.

The 1/sqrt(2) ear scaling is divided out, so 0 dB at 100 Hz means unity gain per ear.

--verify renders an amplitude-panned pink noise through `render_stereo` and checks that the
measured ear-to-source ratio matches the computed H_sum, so the numbers describe the real chain.
The renderer is only called, never changed.
"""

from __future__ import annotations

import argparse

import numpy as np
from numpy.typing import NDArray

from stage.analysis import DEFAULT_HOP, DEFAULT_N_FFT, angle_to_position, stft
from stage.guard import third_octave_bands
from stage.render import render_stereo
from stage.render.pinna import ear_filters
from stage.render.profiles import Profile, direct_filters, get_profile, sector_render_azimuths
from stage.render.renderer import _DEFAULT_SPLIT, _EAR_NORM, _split_gains
from stage.render.sectors import SECTOR_CENTRES_DEG, WIDEN_LIMIT_DEG, sector_weights, widen_azimuth

SAMPLE_RATE = 44100
F_LOW, F_HIGH = 100.0, 20000.0
TOP_OCTAVE = (10000.0, 20000.0)
#: Sector centres and the points halfway between neighbours, right half only: the sector grid,
#: the weights and the head model are all mirror-symmetric, so -theta gives the same responses
#: with the ears swapped (tested in tests/unit/test_measure_sector_sum.py).
POSITIONS_DEG = (0.0, 2.5, 5.0, 7.5, 12.5, 15.0, 17.5, 22.5, 25.0, 27.5, 30.0)
TABLE_FREQS_HZ = (100, 1000, 2000, 4000, 6000, 8000, 10000, 12500, 16000, 20000)


def freqs_hz(n_fft: int = DEFAULT_N_FFT, sample_rate: int = SAMPLE_RATE) -> NDArray[np.float64]:
    return np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)


def sector_sum_response(
    theta_deg: float, beta: float, profile: str | Profile = "V0",
    n_fft: int = DEFAULT_N_FFT, sample_rate: int = SAMPLE_RATE,
) -> NDArray[np.complex128]:
    """H_sum for both ears, shape (2, bins), with the 1/sqrt(2) ear scaling divided out.

    Built from the renderer's own pieces (`direct_filters`, `sector_weights`, `_split_gains`), so
    it follows any change to them.
    """
    prof = get_profile(profile)
    filters = direct_filters(prof, beta, n_fft, sample_rate) / _EAR_NORM  # (13, 2, bins)
    gains = _split_gains(sector_weights(theta_deg), _DEFAULT_SPLIT)  # (13,)
    return np.einsum("s,sek->ek", gains, filters)


def reference_response(
    theta_deg: float, beta: float, profile: str | Profile = "V0",
    n_fft: int = DEFAULT_N_FFT, sample_rate: int = SAMPLE_RATE,
) -> NDArray[np.complex128]:
    """H_ref: one ear filter at the exact widened azimuth of theta, shape (2, bins).

    Mirrors `direct_filters` for a single direction. The near-field toggle depends on per-sector
    distances, which a single direction does not have, so it is refused rather than guessed.
    """
    prof = get_profile(profile)
    if prof.nearfield:
        raise ValueError("the near-field toggle has no single-direction reference")
    limit = WIDEN_LIMIT_DEG if prof.front_limit_deg is None else prof.front_limit_deg
    az = float(widen_azimuth(theta_deg, beta, limit)) - prof.look_yaw_deg
    return ear_filters(
        [az], n_fft=n_fft, sample_rate=sample_rate, pinna=prof.pinna,
        steering_db=prof.steering_db,
    )[0]


def _db(x: NDArray) -> NDArray[np.float64]:
    return 20.0 * np.log10(np.maximum(np.abs(x), 1e-300))


def worst_dip(
    theta_deg: float, beta: float, profile: str | Profile = "V0",
    band: tuple[float, float] = (F_LOW, F_HIGH),
) -> tuple[float, float, int]:
    """Most negative 20 log10 |H_sum / H_ref| in `band`: (dB, frequency in Hz, ear 0 L / 1 R)."""
    f = freqs_hz()
    sel = (f >= band[0]) & (f <= band[1])
    dev = _db(sector_sum_response(theta_deg, beta, profile) / reference_response(
        theta_deg, beta, profile))[:, sel]
    ear, idx = np.unravel_index(np.argmin(dev), dev.shape)
    return float(dev[ear, idx]), float(f[sel][idx]), int(ear)


#: 1/3-octave bands for the smoothed comb, 100 Hz to 16 kHz (upper edge 17.8 kHz). The 20 kHz
#: band would reach past Nyquist at 44.1 kHz.
BANDS = third_octave_bands(100.0, 16000.0)


def band_dips(
    theta_deg: float, beta: float, profile: str | Profile = "V0"
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Comb in 1/3-octave bands: (per ear (2, bands), both ears' power summed (bands,)), dB.

    A single-bin notch can be arbitrarily deep where two equal copies cancel exactly, and one
    bin of 21.5 Hz says little about how much colour is heard. Power in a 1/3-octave band of
    H_sum against the same band of H_ref is the measure the guard's timbre check uses. The
    both-ears figure is what the guard sees on a whole render; the per-ear figure shows where
    the cancellation happens.
    """
    f = freqs_hz()
    hs = np.abs(sector_sum_response(theta_deg, beta, profile)) ** 2
    hr = np.abs(reference_response(theta_deg, beta, profile)) ** 2
    _, lo, hi = BANDS
    ear = np.empty((2, lo.size))
    both = np.empty(lo.size)
    for i, (a, b) in enumerate(zip(lo, hi, strict=True)):
        sel = (f >= a) & (f < b)
        ear[:, i] = 10.0 * np.log10(hs[:, sel].sum(axis=1) / hr[:, sel].sum(axis=1))
        both[i] = 10.0 * np.log10(hs[:, sel].sum() / hr[:, sel].sum())
    return ear, both


def pan_source(theta_deg: float, mono: NDArray[np.float64]) -> NDArray[np.float64]:
    """Amplitude-pan `mono` so the stereo analysis reads stereo angle theta.

    The analysis finds u = [cos phi, sin phi] and position (sin - cos) / (sin + cos); inverting
    that for the tangent-law position gives tan phi = (1 + P) / (1 - P).
    """
    pos = float(angle_to_position(theta_deg))
    phi = np.arctan2(1.0 + pos, 1.0 - pos)
    return np.stack([np.cos(phi) * mono, np.sin(phi) * mono])


def measured_response(
    theta_deg: float, beta: float, seconds: float = 4.0, seed: int = 7
) -> NDArray[np.float64]:
    """|Y_ear| / |S| from a real render of panned white noise, averaged over frames, (2, bins).

    White noise has the same power in every bin, so no bin's ratio rests on a tiny denominator.
    Uses the default renderer (V0). The first and last frames are skipped: the analysis'
    recursive smoother needs a few frames to settle on the source's direction.
    """
    rng = np.random.default_rng(seed)
    mono = 0.1 * rng.standard_normal(int(seconds * SAMPLE_RATE))
    out = render_stereo(pan_source(theta_deg, mono), SAMPLE_RATE, beta=beta)
    s = stft(mono[np.newaxis], n_fft=DEFAULT_N_FFT, hop=DEFAULT_HOP)[0]
    y = stft(out, n_fft=DEFAULT_N_FFT, hop=DEFAULT_HOP)
    sl = slice(8, -2)
    return np.sqrt(np.sum(np.abs(y[:, sl]) ** 2, axis=1) / np.sum(np.abs(s[sl]) ** 2, axis=0))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--beta", type=float, default=2.0, help="widen strength, 1.0 to 2.4")
    parser.add_argument("--profile", default="V0", help="render profile (V0 is the default)")
    parser.add_argument("--step", type=float, default=0.25,
                        help="pan step in degrees of the sweep that finds the worst case")
    parser.add_argument("--verify", action="store_true",
                        help="also check the computed response against a real render (V0 only)")
    args = parser.parse_args()
    beta, prof = args.beta, get_profile(args.profile)
    f = freqs_hz()
    cols = [int(np.argmin(np.abs(f - fq))) for fq in TABLE_FREQS_HZ]
    az = sector_render_azimuths(prof, beta)

    print(f"profile {prof.name}, beta {beta}, {SAMPLE_RATE} Hz, n_fft {DEFAULT_N_FFT} "
          f"(bins every {f[1]:.1f} Hz)")
    print("sector centres (deg):  " + " ".join(f"{c:+.0f}" for c in SECTOR_CENTRES_DEG))
    print("rendered at (deg):     " + " ".join(f"{a:+.1f}" for a in az))
    print()
    print("|H_sum| per ear in dB (L = far ear for a right-panned source)")
    head = "theta  ear " + "".join(f"{fq:>8}" for fq in TABLE_FREQS_HZ)
    print(head)
    for theta in POSITIONS_DEG:
        h = _db(sector_sum_response(theta, beta, prof))
        for ear, name in enumerate("LR"):
            vals = "".join(f"{h[ear, c]:8.2f}" for c in cols)
            print(f"{theta:5.1f}  {name}   {vals}")
    print()
    centres = BANDS[0]
    print("Comb: 20 log10 |H_sum / H_ref|, worst dip per position. Per bin, 100 Hz to 20 kHz and")
    print("10 to 20 kHz; then in 1/3-octave bands (100 Hz to 16 kHz), per ear and both ears' power")
    print("theta  kind     per bin, all             per bin, top octave      "
          "1/3 oct, per ear     1/3 oct, both ears")
    for theta in POSITIONS_DEG:
        kind = "centre" if np.any(np.isclose(theta, SECTOR_CENTRES_DEG)) else "between"
        d_all, f_all, e_all = worst_dip(theta, beta, prof)
        d_top, f_top, e_top = worst_dip(theta, beta, prof, TOP_OCTAVE)
        ear, both = band_dips(theta, beta, prof)
        e_b, i_b = np.unravel_index(np.argmin(ear), ear.shape)
        j = int(np.argmin(both))
        print(f"{theta:5.1f}  {kind:<7}  {d_all:7.2f} dB {f_all:6.0f} Hz {'LR'[e_all]}"
              f"   {d_top:7.2f} dB {f_top:6.0f} Hz {'LR'[e_top]}"
              f"   {ear[e_b, i_b]:6.2f} dB {centres[i_b]:6.0f} {'LR'[e_b]}"
              f"   {both[j]:6.2f} dB {centres[j]:6.0f}")

    sweep = np.arange(0.0, 30.0 + 1e-9, args.step)
    results = [(worst_dip(t, beta, prof), t) for t in sweep]
    (d, fq, ear), t = min(results, key=lambda r: r[0][0])
    (dt, fqt, eart), tt = min(
        ((worst_dip(t, beta, prof, TOP_OCTAVE), t) for t in sweep), key=lambda r: r[0][0]
    )
    print()
    print(f"worst-case dip, sweep 0 to 30 deg in {args.step:g} deg steps: {d:.2f} dB at "
          f"{fq:.0f} Hz, ear {'LR'[ear]}, theta {t:g} deg")
    print(f"worst-case dip in the top octave: {dt:.2f} dB at {fqt:.0f} Hz, ear {'LR'[eart]}, "
          f"theta {tt:g} deg")
    bands = [(band_dips(t, beta, prof), t) for t in sweep]
    (ear, _), t_e = min(bands, key=lambda r: r[0][0].min())
    e_b, i_b = np.unravel_index(np.argmin(ear), ear.shape)
    (_, both), t_b = min(bands, key=lambda r: r[0][1].min())
    j = int(np.argmin(both))
    print(f"worst 1/3-octave dip, one ear: {ear[e_b, i_b]:.2f} dB in the {centres[i_b]:.0f} Hz "
          f"band, ear {'LR'[e_b]}, theta {t_e:g} deg")
    print(f"worst 1/3-octave dip, both ears' power: {both[j]:.2f} dB in the {centres[j]:.0f} Hz "
          f"band, theta {t_b:g} deg")

    if args.verify:
        if prof.name != "V0":
            raise SystemExit("--verify renders with the default renderer, so use --profile V0")
        sel = (f >= F_LOW) & (f <= 16000.0)
        print()
        print("verify against render_stereo (panned white noise, 4 s), 100 Hz to 16 kHz:")
        for theta in (2.5, 27.5):
            meas = _db(measured_response(theta, beta))[:, sel]
            pred = _db(sector_sum_response(theta, beta) * _EAR_NORM)[:, sel]
            err = np.abs(meas - pred)
            print(f"  theta {theta:4.1f}: max |measured - computed| = {np.max(err):.2f} dB, "
                  f"mean {np.mean(err):.2f} dB")


if __name__ == "__main__":
    main()
