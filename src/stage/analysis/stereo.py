"""Stereo analysis: panning, coherence and the primary/ambient split.

Model (standard in the stereo-upmixing literature)
--------------------------------------------------
In each time-frequency bin the stereo pair X = [X_L, X_R] is modelled as

    X = p * u + a

where `u = [cos(phi), sin(phi)]` is the unit panning direction of one dominant
amplitude-panned "primary" sound, `p` is its complex amplitude, and `a` is an "ambient"
remainder that is uncorrelated between the channels.

The least-squares primary is the projection of X onto u:

    p = u . X          primary vector = p * u          ambient a = X - p * u

so primary + ambient equals the input exactly, and the ambient part is orthogonal to the
primary direction. Because u has unit length, no division by (1 + k^2) is needed and the
hard-left and hard-right cases (k = 0 and k = infinity) need no special handling.

Where the direction comes from
------------------------------
`phi` is the angle of the principal axis of the real 2x2 covariance of the pair, estimated
by smoothing over time (causal, so the Rust real-time core can match it) and over a few
neighbouring bins:

    phi = 0.5 * atan2(2 * Re(P_LR), P_LL - P_RR)

Two coherence measures are returned:

* `coherence`: |P_LR| / sqrt(P_LL * P_RR). High for any strongly related pair, including
  time-delayed (spaced-microphone) content.
* `inphase_coherence`: max(Re(P_LR), 0) / sqrt(P_LL * P_RR). High only when the channels are
  related by a gain (amplitude panning), which is the assumption of the model. This is the
  measure used to decide whether a bin may be treated as a panned source.
  (It refines the |P_LR| definition used in the specification: the real part is the
  statistic that matches an amplitude-panning model.)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import lfilter, lfilter_zi

SPEAKER_HALF_ANGLE_DEG = 30.0
_TAN_HALF = np.tan(np.radians(SPEAKER_HALF_ANGLE_DEG))


@dataclass(frozen=True)
class StereoAnalysis:
    """Per-bin results. Arrays are (frames, bins) unless stated otherwise."""

    gain_l: np.ndarray  # cos(phi): left component of the panning direction
    gain_r: np.ndarray  # sin(phi): right component of the panning direction
    position: np.ndarray  # position index in [-1, 1], -1 hard left, +1 hard right
    angle_deg: np.ndarray  # perceived stereo angle by the tangent law, +right
    coherence: np.ndarray  # |P_LR| / sqrt(P_LL P_RR), in [0, 1]
    inphase_coherence: np.ndarray  # max(Re P_LR, 0) / sqrt(P_LL P_RR), in [0, 1]
    primary: np.ndarray  # (2, frames, bins) complex: p * u
    ambient: np.ndarray  # (2, frames, bins) complex: X - p * u


def position_to_angle_deg(position: np.ndarray) -> np.ndarray:
    """Tangent law for loudspeakers at +/-30 degrees: tan(theta) = position * tan(30)."""
    return np.degrees(np.arctan(np.asarray(position) * _TAN_HALF))


def angle_to_position(angle_deg: np.ndarray) -> np.ndarray:
    """Inverse of `position_to_angle_deg`."""
    return np.tan(np.radians(np.asarray(angle_deg))) / _TAN_HALF


def smooth_cross_spectra(
    x_l: np.ndarray,
    x_r: np.ndarray,
    *,
    hop: int,
    sample_rate: float,
    time_const_s: float = 0.08,
    freq_bins: int = 5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Smoothed power and cross spectra P_LL, P_RR (real) and P_LR (complex).

    Smoothing is a causal one-pole average over time with time constant `time_const_s`,
    preceded by a box average over `freq_bins` neighbouring bins. The recursive filter
    starts from the first frame's value, so the start of a signal is not biased toward 0.
    """
    alpha = float(np.exp(-hop / (sample_rate * time_const_s)))
    b, a = np.array([1.0 - alpha]), np.array([1.0, -alpha])
    zi_unit = lfilter_zi(b, a)

    def smooth(v: np.ndarray) -> np.ndarray:
        if freq_bins > 1:
            v = uniform_filter1d(v, size=freq_bins, axis=1, mode="nearest")
        zi = zi_unit[:, None] * v[:1, :]
        out, _ = lfilter(b, a, v, axis=0, zi=zi)
        return out

    p_ll = smooth(np.abs(x_l) ** 2)
    p_rr = smooth(np.abs(x_r) ** 2)
    p_lr = smooth(x_l * np.conj(x_r))
    return p_ll, p_rr, p_lr


def analyse_stereo(
    x_l: np.ndarray,
    x_r: np.ndarray,
    *,
    hop: int,
    sample_rate: float,
    time_const_s: float = 0.08,
    freq_bins: int = 5,
    silence_floor: float = 1e-12,
) -> StereoAnalysis:
    """Analyse the spectrograms of the left and right channels (frames, bins)."""
    p_ll, p_rr, p_lr = smooth_cross_spectra(
        x_l, x_r, hop=hop, sample_rate=sample_rate, time_const_s=time_const_s, freq_bins=freq_bins
    )
    re_lr = p_lr.real

    # Principal-axis angle of the real covariance. In-phase content gives phi in [0, pi/2].
    # Anti-phase content (Re P_LR < 0) is not amplitude-panned, so it is clipped to the
    # nearest valid direction and is flagged by a zero in-phase coherence instead.
    phi = 0.5 * np.arctan2(2.0 * re_lr, p_ll - p_rr)
    phi = np.clip(phi, 0.0, np.pi / 2.0)

    silent = (p_ll + p_rr) < silence_floor
    phi = np.where(silent, np.pi / 4.0, phi)  # silence is treated as centred, not hard left
    gain_l, gain_r = np.cos(phi), np.sin(phi)
    position = np.where(silent, 0.0, (gain_r - gain_l) / (gain_r + gain_l))

    denom = np.sqrt(p_ll * p_rr) + silence_floor
    coherence = np.clip(np.abs(p_lr) / denom, 0.0, 1.0)
    inphase = np.clip(np.maximum(re_lr, 0.0) / denom, 0.0, 1.0)

    amp = gain_l * x_l + gain_r * x_r  # complex primary amplitude p = u . X
    primary = np.stack([amp * gain_l, amp * gain_r])
    ambient = np.stack([x_l, x_r]) - primary

    return StereoAnalysis(
        gain_l=gain_l,
        gain_r=gain_r,
        position=position,
        angle_deg=position_to_angle_deg(position),
        coherence=coherence,
        inphase_coherence=inphase,
        primary=primary,
        ambient=ambient,
    )
