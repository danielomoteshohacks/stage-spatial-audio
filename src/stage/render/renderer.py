"""Lite renderer: stereo in, headphone binaural stereo out. No network, no room, no distance.

Per block of frames:

1. The primary part of every bin is split over the 13 sectors by the bin's stereo angle.
2. Each sector is filtered by the head model at its *widened* azimuth, and the sectors are summed
   into a left-ear and a right-ear spectrum.
3. The ambient part keeps its two channels but gets a fixed random phase per bin and ear, so the
   ears are decorrelated (it sounds around the head instead of as a second centre image).
4. Primary and ambient are added, then the inverse STFT overlap-adds the result.

Where the widen warp is applied
-------------------------------
`sector_weights` has its Gaussians on the un-widened grid (-30 to +30), so the weights must be
computed from the source's original stereo angle. The warp is then applied to the *sector
centres* (`sector_azimuths(beta)`), which is where each sector is rendered. Weighting on an
already widened angle would push everything past about 20 degrees onto the edge sector, and
filtering at widened centres on top would widen twice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray

from stage.analysis import DEFAULT_HOP, DEFAULT_N_FFT, analyse_stereo, istft, stft
from stage.render.headmodel import sector_filters
from stage.render.sectors import sector_azimuths, sector_weights

if TYPE_CHECKING:
    from stage.render.profiles import Profile

#: Seed of the ambient decorrelation phases. Fixed so a render is bit-for-bit repeatable.
AMBIENT_SEED = 20240611

#: The head model gives each ear unit gain at low frequencies. A primary whose power was shared
#: by two speaker channels would therefore arrive at the ears with twice the power (+3 dB, measured
#: +2.5 to +3.4 dB on pink noise before this was added). Scaling the ear filters by 1/sqrt(2)
#: makes the two ears together carry the primary's power. The ambient path is an all-pass and
#: needs no such factor.
_EAR_NORM = 1.0 / np.sqrt(2.0)

#: How the sector weights (which sum to 1 in power) become gains on the complex spectrum.
_SplitMode = Literal["sqrt", "linear"]
_DEFAULT_SPLIT: _SplitMode = "linear"


def _split_gains(weights: NDArray[np.float64], mode: _SplitMode) -> NDArray[np.float64]:
    """Amplitude gain of each sector for power weights `weights` (13, ...).

    "sqrt" keeps the sum of per-sector power equal to the primary's power before filtering.
    "linear" uses the weights as amplitudes. Both exist only so the choice can be measured
    (see tests/unit/test_renderer_split.py); the renderer uses `_DEFAULT_SPLIT`.
    """
    if mode == "sqrt":
        return np.sqrt(weights)
    if mode == "linear":
        return weights
    raise ValueError(f"unknown split mode {mode!r}")


def ambient_phases(n_bins: int, seed: int = AMBIENT_SEED) -> NDArray[np.complex128]:
    """Unit-magnitude random phase per ear and bin, shape (2, n_bins).

    Unit magnitude is an all-pass, so ambient power is preserved exactly with no extra scaling.
    DC and Nyquist stay real (phase 0): the inverse real FFT drops their imaginary part, which
    would otherwise remove power there.
    """
    rng = np.random.default_rng(seed)
    phase = rng.uniform(0.0, 2.0 * np.pi, size=(2, n_bins))
    phase[:, 0] = 0.0
    phase[:, -1] = 0.0
    return np.exp(1j * phase)


def _render_block(
    primary: NDArray[np.complex128],
    ambient: NDArray[np.complex128],
    angle_deg: NDArray[np.float64],
    filters: NDArray[np.complex128],
    phases: NDArray[np.complex128],
    split: _SplitMode,
) -> NDArray[np.complex128]:
    """Binaural spectrum (2, frames, bins) for one block of frames.

    `primary` is the complex primary amplitude (frames, bins), `ambient` is (2, frames, bins),
    `filters` is (13, 2, bins) and `phases` is (2, bins).
    """
    gains = _split_gains(sector_weights(angle_deg), split)  # (13, frames, bins)
    # Sum over sectors of gain * ear filter, then scale by the primary: the sectors are copies
    # of one signal, so the weighted filter sum can be formed before multiplying by it.
    binaural = np.einsum("sfk,sek->efk", gains, filters) * primary[np.newaxis]
    return binaural + ambient * phases[:, np.newaxis, :]


def render_stereo(
    audio: NDArray[np.float64],
    sample_rate: int,
    beta: float = 2.0,
    block_frames: int = 256,
    *,
    profile: str | Profile | None = None,
    _split: _SplitMode = _DEFAULT_SPLIT,
) -> NDArray[np.float64]:
    """Render stereo audio (2, samples) to binaural stereo (2, samples), float64.

    Args:
        audio: left and right channels.
        sample_rate: in Hz. Used for the head-model filters and the analysis smoothing.
        beta: widen strength, 1.0 to 2.4. 1.0 is close to the original image, 2.4 is widest.
        block_frames: STFT frames handled at a time by the sector stage. Sector weights are 13
            times the size of a spectrogram, so this bounds the memory of the heavy step. The
            result does not depend on it.
        profile: None (default) is this renderer, unchanged. A name ("V0" to "V5", "max") or a
            `stage.render.profiles.Profile` renders with the spatialisation-spike cues of
            decision 0007 instead. "V0" gives exactly the same output as None.

    The STFT, the stereo analysis (a causal recursive smoother) and the inverse STFT run on the
    whole signal, because the analysis state would have to be carried across blocks otherwise.
    Only the 13-fold sector stage is blocked. The output has the input's length.

    Memory: measured peak about 3.1 GB for a 4 minute stereo song, from the whole-signal arrays.
    Render excerpts (the script defaults to 15 s) until the analysis can be streamed.
    """
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 2 or audio.shape[0] != 2:
        raise ValueError(f"expected stereo audio of shape (2, samples), got {audio.shape}")
    if block_frames < 1:
        raise ValueError(f"block_frames must be at least 1, got {block_frames}")
    n_samples = audio.shape[1]
    if profile is not None:
        sector_azimuths(beta)  # validates beta before the heavier work
        # Imported here: profiles builds on this module, so a top-level import would be circular.
        from stage.render.profiles import render_profile

        return render_profile(audio, sample_rate, profile, beta, block_frames, _split)

    azimuths = sector_azimuths(beta)  # also validates beta
    filters = _EAR_NORM * sector_filters(
        azimuths, n_fft=DEFAULT_N_FFT, sample_rate=int(sample_rate)
    )

    spec = stft(audio, n_fft=DEFAULT_N_FFT, hop=DEFAULT_HOP)
    analysis = analyse_stereo(spec[0], spec[1], hop=DEFAULT_HOP, sample_rate=sample_rate)
    # primary = p * u with |u| = 1, so projecting back on u recovers the scalar p.
    p = analysis.primary[0] * analysis.gain_l + analysis.primary[1] * analysis.gain_r

    n_frames, n_bins = p.shape
    phases = ambient_phases(n_bins)
    out = np.empty((2, n_frames, n_bins), dtype=np.complex128)
    for start in range(0, n_frames, block_frames):
        sl = slice(start, min(start + block_frames, n_frames))
        out[:, sl, :] = _render_block(
            p[sl], analysis.ambient[:, sl, :], analysis.angle_deg[sl], filters, phases, _split
        )
    return istft(out, n_samples, n_fft=DEFAULT_N_FFT, hop=DEFAULT_HOP)
