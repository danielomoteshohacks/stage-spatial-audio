"""SoundStage's own post-processing of separated leaves (decision 0023).

Neural separators give estimates that do not add up to the mix and carry three kinds of defect:
leakage from the other stems, "musical noise" (isolated time-frequency specks where a mask
flickers) and smeared transients. This layer works on any set of leaves, whatever produced them.

1. `multichannel_wiener`: the local Gaussian model of Duong, Vincent and Gribonval (2010,
   "Under-determined reverberant audio source separation using a full-rank spatial covariance
   model", IEEE TASLP 18(7)) as used by Liutkus and Badeau (2015) and in norbert: every leaf has
   a power spectral density per tile (taken from the separator's estimate and held fixed) and a
   2x2 spatial covariance per frequency; a few EM iterations re-estimate the covariances from
   the mix, and the leaves are the Wiener estimates. The
   estimates sum to the mix by construction. ESTABLISHED.
2. `mixture_consistency`: the energy-weighted projection that makes leaves add up exactly
   (Wisdom et al. 2019, "Differentiable consistency constraints for improved deep speech
   enhancement", ICASSP). ESTABLISHED.
3. `bleed_suppress`: cross-stem coherence. Where a leaf's tile is locally coherent with a
   neighbour that dominates that tile, the tile is leakage, and the share of it that is
   coherent is moved to the dominant leaf (the sum is unchanged). The thresholds are ours:
   SPECULATIVE, and `scripts/benchmark_groundtruth.py` reports whether it helps.
4. `detect_musical_noise` and `repair_musical_noise`: a tile flickers when the leaf's share of
   the mix (its ratio mask) differs from the median of its 3 x 3 neighbourhood by more than
   0.3; a leaf's artifact rate is flickering tiles per thousand active tiles. The repair
   smooths the ratio mask with a 3 x 3 median only around the flickering tiles, so the rest of
   the leaf is untouched. SPECULATIVE thresholds, calibrated in tests/unit/test_cascade_post.py.
5. `restore_transients`: where the mix has an onset, the long analysis window has spread each
   percussive leaf's attack into the quiet before it. Around each onset the leaf is limited,
   band by band, to the mixture's own 1 ms envelope (a leaf cannot be louder than its mix), and
   the removed energy goes back to the other leaves by the consistency projection. SPECULATIVE.
6. `leaf_quality`: leakage estimate, artifact rate and energy share per leaf, and a 0 to 100
   score. The scene planner merges a leaf whose score is below its threshold back into its
   parent instead of exposing its artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import binary_dilation, median_filter, uniform_filter
from scipy.signal import butter, sosfiltfilt

from stage.analysis.stft import istft, stft

N_FFT = 2048
HOP = 512
EPS = 1e-10


# --- 1. multichannel Wiener ---------------------------------------------------------------------


def _herm(a: NDArray) -> NDArray:
    return np.conj(np.swapaxes(a, -1, -2))


def multichannel_wiener(mix: NDArray, leaves: dict[str, NDArray], iterations: int = 2,
                        n_fft: int = N_FFT, hop: int = HOP) -> dict[str, NDArray]:
    """Refine leaves (each (2, n)) with EM on the local Gaussian model; the result sums to `mix`."""
    n = mix.shape[1]
    names = list(leaves)
    x = np.transpose(stft(mix, n_fft=n_fft, hop=hop), (1, 2, 0)).astype(np.complex64)  # (T, F, 2)
    y = {k: np.transpose(stft(v, n_fft=n_fft, hop=hop), (1, 2, 0)).astype(np.complex64)
         for k, v in leaves.items()}
    t_n, f_n, _ = x.shape
    eye = np.eye(2, dtype=np.complex64)
    v = {k: np.maximum(np.mean(np.abs(y[k]) ** 2, axis=-1), EPS) for k in names}
    r = {}
    for k in names:
        c = np.einsum("tfi,tfj->tfij", y[k], np.conj(y[k])) / v[k][..., None, None]
        r[k] = c.mean(axis=0) + 1e-3 * eye
    for _ in range(max(iterations, 1)):
        sigma = sum(v[k][..., None, None] * r[k][None] for k in names) + 1e-6 * eye
        sigma_inv = np.linalg.inv(sigma)
        new_r = {}
        for k in names:
            cov_k = v[k][..., None, None] * r[k][None]
            gain = cov_k @ sigma_inv
            y[k] = np.einsum("tfij,tfj->tfi", gain, x)
            post = np.einsum("tfi,tfj->tfij", y[k], np.conj(y[k])) + (eye - gain) @ cov_k
            # Only the spatial covariance is re-estimated; the power spectral density stays the
            # separator's own estimate (norbert does the same). Re-estimating it from the
            # posterior as well lets a leaf drift towards whichever neighbour shares its pan.
            new_r[k] = (post / v[k][..., None, None]).mean(axis=0) + 1e-3 * eye
        r = new_r
    out = {}
    for k in names:
        spec = np.transpose(y[k], (2, 0, 1))
        out[k] = istft(spec, n, n_fft=n_fft, hop=hop)
    del x, y
    return out


# --- 2. mixture consistency ---------------------------------------------------------------------


def mixture_consistency(mix: NDArray, leaves: dict[str, NDArray]) -> dict[str, NDArray]:
    """Add the residual (mix - sum of leaves) back to each leaf in proportion to its local energy.

    The weight of a leaf at a sample is its energy in a 50 ms window over the sum of all leaves'
    energies there, so the correction lands where each leaf is active; the leaves then add up to
    the mix to float precision.
    """
    resid = mix - sum(leaves.values())
    win = 2205
    kernel = np.ones(win) / win
    energy = {k: np.convolve(np.mean(v**2, axis=0), kernel, mode="same") + 1e-12
              for k, v in leaves.items()}
    total = sum(energy.values())
    return {k: v + resid * (energy[k] / total)[np.newaxis] for k, v in leaves.items()}


# --- 3. bleed suppression -----------------------------------------------------------------------


def bleed_suppress(leaves: dict[str, NDArray], strength: float = 0.7, min_share: float = 0.005,
                   n_fft: int = N_FFT, hop: int = HOP) -> dict[str, NDArray]:
    """Move locally coherent leakage from each leaf to the neighbour that dominates the tile."""
    n = next(iter(leaves.values())).shape[1]
    names = list(leaves)
    spec = {k: stft(v, n_fft=n_fft, hop=hop) for k, v in leaves.items()}
    energy = {k: float(np.sum(np.abs(s) ** 2)) for k, s in spec.items()}
    total = sum(energy.values()) or 1.0
    active = [k for k in names if energy[k] / total >= min_share]
    mono = {k: spec[k].mean(axis=0) for k in active}  # (T, F)
    pw = {k: np.abs(mono[k]) ** 2 + EPS for k in active}
    moved = {k: np.zeros_like(spec[k]) for k in names}
    for a in active:
        for b in active:
            if a == b:
                continue
            cross = uniform_filter((mono[a] * np.conj(mono[b])).real, size=(5, 3)) \
                + 1j * uniform_filter((mono[a] * np.conj(mono[b])).imag, size=(5, 3))
            pa = uniform_filter(pw[a], size=(5, 3))
            pb = uniform_filter(pw[b], size=(5, 3))
            coh = np.abs(cross) / np.sqrt(pa * pb)
            dominance = pb / (pa + pb)
            leak = np.clip((coh - 0.6) / 0.4, 0.0, 1.0) ** 2 * np.clip(
                (dominance - 0.75) / 0.25, 0.0, 1.0)
            take = strength * leak
            moved[a] -= spec[a] * take[np.newaxis]
            moved[b] += spec[a] * take[np.newaxis]
    return {k: istft(spec[k] + moved[k], n, n_fft=n_fft, hop=hop) for k in names}


# --- 4. musical noise ---------------------------------------------------------------------------


def _ratio_mask(leaf: NDArray, mix_mag: NDArray, n_fft: int, hop: int) -> NDArray:
    mag = np.abs(stft(leaf, n_fft=n_fft, hop=hop)).mean(axis=0)
    return np.clip(mag / (mix_mag + 1e-9), 0.0, 1.5)


def detect_musical_noise(leaf: NDArray, mix: NDArray, n_fft: int = N_FFT, hop: int = HOP,
                         deviation: float = 0.3) -> tuple[NDArray, float]:
    """(flicker mask over (T, F), flicker rate in tiles per thousand active tiles).

    A true source has a ratio mask |leaf| / |mix| that varies smoothly over neighbouring tiles;
    a separator whose mask flickers leaves isolated specks that are heard as musical noise.
    A tile flickers when its ratio differs from the median of its 3 x 3 neighbourhood by more
    than `deviation`. Measured on a generated guitar, the reference leaf reads 5 per thousand,
    the soft azimuth masks 6, a hard pan mask 11, and a random mask 150 to 180
    (tests/unit/test_cascade_post.py); a detector on the leaf alone does not work, because
    resynthesis smooths the specks across neighbouring tiles.
    """
    mix_mag = np.abs(stft(mix, n_fft=n_fft, hop=hop)).mean(axis=0)
    ratio = _ratio_mask(leaf, mix_mag, n_fft, hop)
    dev = np.abs(ratio - median_filter(ratio, size=(3, 3), mode="nearest"))
    active = mix_mag > 1e-3 * float(mix_mag.max() + EPS)
    flagged = (dev > deviation) & active
    return flagged, float(1000.0 * flagged.sum() / max(int(active.sum()), 1))


def repair_musical_noise(mix: NDArray, leaves: dict[str, NDArray], trigger: float = 25.0,
                         n_fft: int = N_FFT, hop: int = HOP) -> tuple[dict[str, NDArray], dict]:
    """Smooth each leaf's ratio mask around its specks only; the masks are renormalised to sum to
    one, so the leaves still add up to the mix. Returns the leaves and the per-leaf flicker rates
    before the repair."""
    n = mix.shape[1]
    names = list(leaves)
    x = stft(mix, n_fft=n_fft, hop=hop)
    mags = {k: np.abs(stft(v, n_fft=n_fft, hop=hop)).mean(axis=0) for k, v in leaves.items()}
    total = sum(m**2 for m in mags.values()) + EPS
    masks = {k: m**2 / total for k, m in mags.items()}
    rates, flagged = {}, {}
    for k in names:
        specks, rate = detect_musical_noise(leaves[k], mix, n_fft, hop)
        rates[k] = rate
        flagged[k] = binary_dilation(specks, iterations=1)
    repaired = {}
    for k in names:
        smooth = median_filter(masks[k], size=(3, 3), mode="nearest")
        # Only leaves whose flicker rate is above the clean range are touched at all: on a
        # clean leaf the repair costs fidelity (ablation in docs/log.md, v3 Phase 1).
        fire = rates[k] > trigger
        repaired[k] = np.where(flagged[k] & fire, smooth, masks[k])
    norm = sum(repaired.values()) + EPS
    out = {k: istft(x * (repaired[k] / norm)[np.newaxis], n, n_fft=n_fft, hop=hop) for k in names}
    return out, rates


# --- 5. transients ------------------------------------------------------------------------------

BANDS_HZ = (60.0, 150.0, 300.0, 600.0, 1200.0, 2400.0, 4800.0, 9600.0)


def onsets(mix: NDArray, sample_rate: int, hop_s: float = 0.002, min_gap_s: float = 0.05
           ) -> NDArray[np.int64]:
    """Sample positions of percussive onsets in the mix (rising energy of the 1.5 kHz and above)."""
    sos = butter(4, 1500.0, "highpass", fs=sample_rate, output="sos")
    hi = sosfiltfilt(sos, mix.mean(axis=0))
    hop = max(int(hop_s * sample_rate), 1)
    env = np.sqrt(np.convolve(hi**2, np.ones(hop) / hop, mode="same"))[::hop]
    log_env = np.log(env + 1e-6)
    flux = np.maximum(np.diff(log_env, prepend=log_env[0]), 0.0)
    thresh = np.median(flux) + 4.0 * np.median(np.abs(flux - np.median(flux))) + 0.5
    peaks = []
    last = -10**9
    for i in np.flatnonzero(flux > thresh):
        if i - last > min_gap_s / hop_s and (i == 0 or flux[i] >= flux[i - 1]):
            peaks.append(i * hop)
            last = i
    return np.array(peaks, dtype=np.int64)


def restore_transients(mix: NDArray, leaves: dict[str, NDArray], percussive: list[str],
                       sample_rate: int, pre_s: float = 0.03, post_s: float = 0.01
                       ) -> dict[str, NDArray]:
    """Remove the pre-echo a long analysis window leaves before each percussive attack.

    A leaf cannot be louder in a band than the mixture it was taken from. Before an onset the
    mix is quiet in the high bands, so any energy a percussive leaf has there is smeared in
    from the attack. In the window from `pre_s` before to `post_s` after each onset, each
    percussive leaf is limited, band by band (octaves from 600 Hz up), to the mixture's own
    1 ms envelope. Outside those windows the leaf is untouched; the energy removed is returned
    to the other leaves by the mixture-consistency projection that follows. SPECULATIVE: the
    effect is measured as the 10 to 90 percent attack time against the reference.
    """
    out = {k: v.copy() for k, v in leaves.items()}
    pos = onsets(mix, sample_rate)
    if pos.size == 0 or not percussive:
        return out
    n = mix.shape[1]
    top = min(sample_rate / 2 - 100, 16000.0)
    edges = [600.0, 1200.0, 2400.0, 4800.0, 9600.0, top]
    bands = [butter(4, [lo, hi], "bandpass", fs=sample_rate, output="sos")
             for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
    win = np.zeros(n)
    ramp = int(0.003 * sample_rate)
    for p in pos:
        a, b = max(0, p - int(pre_s * sample_rate)), min(n, p + int(post_s * sample_rate))
        win[a:b] = 1.0
    win = np.convolve(win, np.hanning(2 * ramp + 1) / np.hanning(2 * ramp + 1).sum(), "same")
    win = np.clip(win, 0.0, 1.0)
    sm = np.ones(max(int(0.001 * sample_rate), 1)) / max(int(0.001 * sample_rate), 1)

    def env(x: NDArray) -> NDArray:
        return np.sqrt(np.convolve(np.mean(x**2, axis=0), sm, mode="same") + 1e-14)

    mix_env = [env(sosfiltfilt(b, mix, axis=-1)) for b in bands]
    for k in percussive:
        high = out[k] - sum(sosfiltfilt(b, out[k], axis=-1) for b in bands)  # below 600 Hz stays
        limited = np.zeros_like(out[k])
        for b, me in zip(bands, mix_env, strict=True):
            band = sosfiltfilt(b, out[k], axis=-1)
            gain = np.minimum(1.0, me / (env(band) + 1e-9))
            limited += band * (1.0 - win + win * gain)[np.newaxis]
        out[k] = high + limited
    return out


def attack_time_ms(x: NDArray, sample_rate: int, positions: NDArray) -> float:
    """Median 10 to 90 percent rise time (ms) of the high-passed envelope around `positions`."""
    sos = butter(4, 1500.0, "highpass", fs=sample_rate, output="sos")
    hi = sosfiltfilt(sos, x.mean(axis=0))
    env = np.abs(hi)
    sm = np.convolve(env, np.ones(16) / 16, mode="same")
    w = int(0.05 * sample_rate)
    times = []
    for p in positions:
        seg = sm[max(0, p - w // 2) : p + w]
        if seg.size < 32 or seg.max() <= 0:
            continue
        pk = int(np.argmax(seg))
        lo = np.flatnonzero(seg[:pk + 1] >= 0.1 * seg[pk])
        hi_i = np.flatnonzero(seg[:pk + 1] >= 0.9 * seg[pk])
        if lo.size and hi_i.size:
            times.append((hi_i[0] - lo[0]) / sample_rate * 1000.0)
    return float(np.median(times)) if times else float("nan")


# --- 6. quality score ---------------------------------------------------------------------------


@dataclass
class LeafQuality:
    name: str
    energy_share: float
    leakage: float  # share of the leaf's energy in tiles another leaf dominates, coherently
    artifact_rate: float  # flickering tiles per thousand active tiles
    score: float  # 0 to 100

    def as_dict(self) -> dict:
        return {"energy_share": round(self.energy_share, 5), "leakage": round(self.leakage, 4),
                "artifact_rate": round(self.artifact_rate, 2), "score": round(self.score, 1)}


def leaf_quality(leaves: dict[str, NDArray], mix: NDArray | None = None, n_fft: int = N_FFT,
                 hop: int = HOP) -> dict[str, LeafQuality]:
    """Estimate each leaf's leakage and artifacts without a reference.

    Leakage: the share of the leaf's tile energy that sits in tiles where another leaf has at
    least four times its energy *and* the two are coherent over a 5 x 3 neighbourhood (a copy of
    the other leaf, not an independent sound). Score: 100 times (1 - leakage) times a penalty
    that falls from 1 to 0 as the flicker rate goes from 15 to 150 per thousand tiles (a clean
    leaf reads under 10, a random mask 150 or more), times a
    factor that falls to zero for leaves under 0.2 percent of the total energy (too little to
    stand alone as an object).
    """
    mix = sum(leaves.values()) if mix is None else mix
    spec = {k: stft(v, n_fft=n_fft, hop=hop).mean(axis=0) for k, v in leaves.items()}
    pw = {k: np.abs(s) ** 2 + EPS for k, s in spec.items()}
    total_e = sum(float(p.sum()) for p in pw.values())
    out: dict[str, LeafQuality] = {}
    names = list(leaves)
    for k in names:
        e = float(pw[k].sum())
        leak_e = np.zeros_like(pw[k])
        for j in names:
            if j == k:
                continue
            dom = pw[j] > 4.0 * pw[k]
            if not np.any(dom):
                continue
            cross = uniform_filter((spec[k] * np.conj(spec[j])).real, size=(5, 3)) \
                + 1j * uniform_filter((spec[k] * np.conj(spec[j])).imag, size=(5, 3))
            coh = np.abs(cross) / np.sqrt(uniform_filter(pw[k], size=(5, 3))
                                          * uniform_filter(pw[j], size=(5, 3)))
            leak_e = np.maximum(leak_e, np.where(dom & (coh > 0.7), pw[k], 0.0))
        leak = float(leak_e.sum() / max(e, EPS))
        _, rate = detect_musical_noise(leaves[k], mix, n_fft, hop)
        art = float(np.clip(1.0 - (rate - 15.0) / 135.0, 0.0, 1.0))
        share = e / max(total_e, EPS)
        presence = float(np.clip(share / 0.002, 0.0, 1.0))
        out[k] = LeafQuality(k, share, leak, rate, 100.0 * (1.0 - leak) * art * presence)
    return out


def merge_poor_leaves(leaves: dict[str, NDArray], parents: dict[str, str],
                      quality: dict[str, LeafQuality], threshold: float = 40.0
                      ) -> tuple[dict[str, NDArray], dict[str, str]]:
    """Merge every leaf scoring under `threshold` into its parent leaf (or parent stem).

    `parents` maps a leaf name to the name it merges into; a parent not among the leaves is
    created by the merge. Returns the new leaves and a map of what was merged where.
    """
    merged: dict[str, str] = {}
    out = {k: v for k, v in leaves.items()}
    for k, q in quality.items():
        if q.score < threshold and k in out and k in parents:
            into = parents[k]
            out[into] = out.get(into, 0.0) + out.pop(k)
            merged[k] = into
    return out, merged
