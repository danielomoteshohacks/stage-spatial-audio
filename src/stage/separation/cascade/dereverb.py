"""Level 5: split a stem into a dry object and the reverb it carried.

The dry part becomes a point source in the scene; the reverb is kept and returned later as a
diffuse field around and above the listener (decision 0025). Two routes:

* a model (the vocal dereverberator of the cascade), guarded by the rule the SJTU X-LANCE
  system uses (arXiv 2602.09042): if the dry output is more than 10 dB quieter than the input
  the model has removed the voice and not the room (typical for backing vocals and doubled
  parts), and the stem is left as it was, with no reverb return;
* `dereverb_dsp`, model-free, for every other stem and for the CPU path: late-reverberation
  spectral subtraction after Lebart, Boucher and Denbigh (2001, "A new method based on spectral
  subtraction for speech dereverberation", Acta Acustica 87), ESTABLISHED. Reverberation after
  the first `t_delay` seconds is modelled as an exponentially decaying copy of the past power
  of the signal itself, with decay set by the reverberation time; a Wiener-like gain removes
  that estimate, limited to `floor_db` so a note's own decay is not eaten. The reverberation
  time is estimated blindly from the median decay rate of the stem's energy envelope
  (`estimate_rt60`, SPECULATIVE: it is an estimate from music, not from a clean decay).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import uniform_filter1d

from stage.analysis.stft import istft, stft

N_FFT = 2048
HOP = 512
GUARD_DB = 10.0


def level_db(x: NDArray) -> float:
    return float(10.0 * np.log10(np.mean(x**2) + 1e-20))


def guard(dry: NDArray, original: NDArray, max_drop_db: float = GUARD_DB) -> bool:
    """True when the dry output is acceptable (not more than `max_drop_db` below the input)."""
    return level_db(original) - level_db(dry) <= max_drop_db


def estimate_rt60(x: NDArray, sample_rate: int, lo: float = 0.2, hi: float = 2.0) -> float:
    """Blind reverberation time from the steepest sustained decays of the broadband envelope."""
    mono = np.mean(x, axis=0)
    hop = int(0.01 * sample_rate)
    frames = mono[: mono.size // hop * hop].reshape(-1, hop)
    env_db = 10.0 * np.log10(np.mean(frames**2, axis=1) + 1e-12)
    env_db = uniform_filter1d(env_db, 3)
    slopes = []
    run = 0
    for i in range(1, env_db.size):
        if env_db[i] < env_db[i - 1] - 0.05:
            run += 1
        else:
            if run >= 8:  # at least 80 ms of unbroken decay
                s = (env_db[i - 1] - env_db[i - 1 - run]) / (run * 0.01)  # dB per second
                if s < 0:
                    slopes.append(s)
            run = 0
    if len(slopes) < 3:
        return 0.6
    rt = -60.0 / float(np.median(slopes))
    return float(np.clip(rt, lo, hi))


def dereverb_dsp(x: NDArray, sample_rate: int, rt60: float | None = None,
                 t_delay: float = 0.05, floor_db: float = -15.0, over: float = 1.0
                 ) -> tuple[NDArray, NDArray, float]:
    """(dry, reverb, rt60) with dry + reverb == x exactly."""
    n = x.shape[1]
    rt = estimate_rt60(x, sample_rate) if rt60 is None else float(rt60)
    spec = stft(x, N_FFT, HOP)
    power = np.abs(spec) ** 2
    d = max(int(round(t_delay * sample_rate / HOP)), 1)
    # Power decays 60 dB over rt60 seconds: per frame the factor is 10^(-6 * HOP / (sr * rt60)).
    decay = 10.0 ** (-6.0 * d * HOP / (sample_rate * rt))
    late = np.zeros_like(power)
    late[:, d:] = decay * power[:, :-d]
    # One-pole smoothing of the late estimate over time, as a recursion of the tail itself.
    for t in range(d + 1, power.shape[1]):
        late[:, t] = np.maximum(late[:, t], 0.5 * late[:, t - 1] * 10.0 ** (
            -6.0 * HOP / (sample_rate * rt)))
    floor = 10.0 ** (floor_db / 10.0)  # a power ratio
    gain = np.clip(1.0 - over * late / (power + 1e-12), floor, 1.0)
    gain = np.sqrt(gain)
    dry = istft(spec * gain, n, N_FFT, HOP)
    return dry, x - dry, rt
