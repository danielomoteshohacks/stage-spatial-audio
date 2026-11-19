"""Named render profiles: the ablation chain of the spatialisation spike (decision 0007).

V0 is the default renderer. Each later profile adds one thing to the one before:

    V1 front-arc limit   V2 pinna   V3 directional-band steering
    V4 image-source early reflections   V5 FDN late field with controlled coherence

Each addition is an independent field of `Profile`, so a cue whose gate fails can be dropped
without touching the others. "max" holds the toggles whose gates passed (see 0007, Results).

The soundfield is rotatable: `look_yaw_deg` turns the head. The direct sectors are rendered at
alpha_k - yaw, and the reflections arrive from their world directions minus yaw, while the room
and the sources stay put. Offline this is only a fixed "look"; it tests the code path that the
real-time head tracker would drive (0008). A static rotation is not a head-motion cue.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray
from scipy.signal import fftconvolve

from stage.analysis import DEFAULT_HOP, DEFAULT_N_FFT, analyse_stereo, istft, stft
from stage.render.headmodel import sector_filters
from stage.render.pinna import ear_filters, nearfield_gains
from stage.render.renderer import _EAR_NORM, _render_block, _split_gains, ambient_phases
from stage.render.room import (
    N_REFLECTIONS,
    Room,
    coherence_mix,
    early_reflection_fir,
    fdn_process,
    image_sources,
    late_unit_energy,
    source_position,
)
from stage.render.sectors import (
    SECTOR_CENTRES_DEG,
    WIDEN_LIMIT_DEG,
    sector_azimuths,
    sector_weights,
)

#: Lite has no stems, so the pan position stands in for the role (0007 H14, SPECULATIVE):
#: the centre is usually vocal, kick and bass (near), the sides are pads and guitars.
ROLE_DISTANCE_M = {"near": 1.0, "mid": 2.0, "far": 4.0}
#: Buses: name -> (role, sector indices). Left and right are kept apart so each bus has one
#: direction for its reflections.
BUSES: dict[str, tuple[str, tuple[int, ...]]] = {
    "far_left": ("far", (0, 1)),
    "mid_left": ("mid", (2, 3, 4)),
    "centre": ("near", (5, 6, 7)),
    "mid_right": ("mid", (8, 9, 10)),
    "far_right": ("far", (11, 12)),
}
#: Reference distance of the late-field calibration, and the late-to-direct energy ratio there.
LATE_REF_M = 2.0
LATE_TO_DIRECT_DB = -5.0


@dataclass(frozen=True)
class Profile:
    """One combination of spatial cues. All defaults reproduce the V0 renderer exactly."""

    name: str
    front_limit_deg: float | None = None  # H11; None keeps the default 80 degree asymptote
    pinna: bool = False  # H12
    steering_db: float = 0.0  # H13; 0 disables
    early: bool = False  # H14
    early_highpass_hz: float | None = None  # H14b
    early_send_db: float = 0.0  # H14b
    late: bool = False  # H15
    nearfield: bool = False  # H16
    look_yaw_deg: float = 0.0  # H17; positive turns the head to the right


V0 = Profile("V0")
V1 = replace(V0, name="V1", front_limit_deg=60.0)
V2 = replace(V1, name="V2", pinna=True)
V3 = replace(V2, name="V3", steering_db=1.5)
V4 = replace(V3, name="V4", early=True)
V5 = replace(V4, name="V5", late=True)
CHAIN = (V0, V1, V2, V3, V4, V5)
# H14b, registered after V4 failed P5 and P6: reflections high-passed and 3 dB lower.
V4B = replace(V4, name="V4b", early_highpass_hz=200.0, early_send_db=-3.0)
V5B = replace(V4B, name="V5b", late=True)
#: The toggles whose gates all passed in 0007 (Results): front-arc, pinna, steering and the H14b
#: early reflections. The late field failed its DRR-spacing and timbre gates, so it is left out.
MAX = replace(V4B, name="max")
PROFILES: dict[str, Profile] = {p.name: p for p in (*CHAIN, V4B, V5B, MAX)}


def get_profile(profile: str | Profile) -> Profile:
    if isinstance(profile, Profile):
        return profile
    try:
        return PROFILES[profile]
    except KeyError:
        raise ValueError(f"unknown profile {profile!r}; known: {sorted(PROFILES)}") from None


def sector_render_azimuths(profile: Profile, beta: float) -> NDArray[np.float64]:
    """World azimuth of each sector (before head rotation)."""
    limit = WIDEN_LIMIT_DEG if profile.front_limit_deg is None else profile.front_limit_deg
    return sector_azimuths(beta, limit)


def sector_distances() -> NDArray[np.float64]:
    out = np.empty(SECTOR_CENTRES_DEG.size)
    for role, idx in BUSES.values():
        out[list(idx)] = ROLE_DISTANCE_M[role]
    return out


def direct_filters(
    profile: Profile, beta: float, n_fft: int, sample_rate: int
) -> NDArray[np.complex128]:
    """Ear filters (13, 2, bins) of the direct path, including the 1/sqrt(2) ear scaling."""
    az = sector_render_azimuths(profile, beta) - profile.look_yaw_deg
    if not (profile.pinna or profile.steering_db):
        h = sector_filters(az, n_fft=n_fft, sample_rate=sample_rate)  # exactly the V0 path
    else:
        h = ear_filters(
            az, n_fft=n_fft, sample_rate=sample_rate, pinna=profile.pinna,
            steering_db=profile.steering_db,
        )
    if profile.nearfield:
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
        h = h * nearfield_gains(az, sector_distances(), freqs)
    return _EAR_NORM * h


def bus_world_azimuth(profile: Profile, beta: float, bus: str) -> float:
    az = sector_render_azimuths(profile, beta)
    return float(np.mean(az[list(BUSES[bus][1])]))


def bus_early_fir(
    profile: Profile, beta: float, bus: str, sample_rate: int, room: Room | None = None
) -> NDArray[np.float64]:
    room = Room() if room is None else room
    role, _ = BUSES[bus]
    src = source_position(room, bus_world_azimuth(profile, beta, bus), ROLE_DISTANCE_M[role])
    refl = image_sources(room, src)[:N_REFLECTIONS]
    return early_reflection_fir(
        refl, sample_rate=sample_rate, yaw_deg=profile.look_yaw_deg, pinna=profile.pinna,
        steering_db=profile.steering_db, ear_norm=_EAR_NORM,
        highpass_hz=profile.early_highpass_hz, send_db=profile.early_send_db,
    )


def late_gain(sample_rate: int, n_fft: int = DEFAULT_N_FFT) -> float:
    """Late-chain gain at LATE_REF_M so late energy is LATE_TO_DIRECT_DB below a centred direct.

    Calibrated against the V0 centre filter so the level does not change with the other toggles.
    """
    h = _EAR_NORM * sector_filters([0.0], n_fft=n_fft, sample_rate=sample_rate)[0]
    direct_energy = float(np.sum(np.abs(np.fft.irfft(h, n=n_fft, axis=-1)) ** 2))
    target = direct_energy * 10.0 ** (LATE_TO_DIRECT_DB / 10.0)
    return float(np.sqrt(target / late_unit_energy(sample_rate)))


def _bus_signals(p, angle_deg, block_frames, n_samples, split) -> dict[str, NDArray]:
    """Time-domain mono signal of each bus: the inverse STFT of its sectors' share of p."""
    specs = {name: np.zeros_like(p) for name in BUSES}
    for start in range(0, p.shape[0], block_frames):
        sl = slice(start, min(start + block_frames, p.shape[0]))
        gains = _split_gains(sector_weights(angle_deg[sl]), split)
        for name, (_, idx) in BUSES.items():
            specs[name][sl] = gains[list(idx)].sum(axis=0) * p[sl]
    return {
        name: istft(s[np.newaxis], n_samples, n_fft=DEFAULT_N_FFT, hop=DEFAULT_HOP)[0]
        for name, s in specs.items()
    }


def render_profile(
    audio: NDArray[np.float64],
    sample_rate: int,
    profile: str | Profile,
    beta: float = 2.0,
    block_frames: int = 256,
    split: str = "linear",
) -> NDArray[np.float64]:
    """Render stereo (2, n) to binaural (2, n) with a named profile. See `render_stereo`."""
    prof = get_profile(profile)
    audio = np.asarray(audio, dtype=np.float64)
    n_samples = audio.shape[1]
    filters = direct_filters(prof, beta, DEFAULT_N_FFT, int(sample_rate))

    spec = stft(audio, n_fft=DEFAULT_N_FFT, hop=DEFAULT_HOP)
    analysis = analyse_stereo(spec[0], spec[1], hop=DEFAULT_HOP, sample_rate=sample_rate)
    p = analysis.primary[0] * analysis.gain_l + analysis.primary[1] * analysis.gain_r
    n_frames, n_bins = p.shape
    phases = ambient_phases(n_bins)
    out = np.empty((2, n_frames, n_bins), dtype=np.complex128)
    for start in range(0, n_frames, block_frames):
        sl = slice(start, min(start + block_frames, n_frames))
        out[:, sl, :] = _render_block(
            p[sl], analysis.ambient[:, sl, :], analysis.angle_deg[sl], filters, phases, split
        )
    y = istft(out, n_samples, n_fft=DEFAULT_N_FFT, hop=DEFAULT_HOP)
    if not (prof.early or prof.late):
        return y

    buses = _bus_signals(p, analysis.angle_deg, block_frames, n_samples, split)
    if prof.early:
        for name, sig in buses.items():
            fir = bus_early_fir(prof, beta, name, int(sample_rate))
            for ear in range(2):
                y[ear] += fftconvolve(sig, fir[ear])[:n_samples]
    if prof.late:
        send = np.zeros(n_samples)
        for name, sig in buses.items():
            send += (ROLE_DISTANCE_M[BUSES[name][0]] / LATE_REF_M) * sig
        # The ambient part is the room already in the recording; it feeds the late field too.
        amb = istft(analysis.ambient, n_samples, n_fft=DEFAULT_N_FFT, hop=DEFAULT_HOP)
        send += (amb[0] + amb[1]) / np.sqrt(2.0)
        late = coherence_mix(fdn_process(send, int(sample_rate)), int(sample_rate))
        y += late_gain(int(sample_rate)) * late
    return y


def role_impulse_response(
    profile: str | Profile, role: str, sample_rate: int = 44100, beta: float = 2.0,
    length_s: float = 2.0,
) -> dict[str, NDArray[np.float64]]:
    """Binaural impulse response of one role's bus, split into direct, early and late parts.

    Used for the DRR proxy. Each part is (2, n). Uses the right-hand bus for mid and far.
    """
    prof = get_profile(profile)
    bus = {"near": "centre", "mid": "mid_right", "far": "far_right"}[role]
    n = int(length_s * sample_rate)
    az = bus_world_azimuth(prof, beta, bus) - prof.look_yaw_deg
    if prof.pinna or prof.steering_db:
        h = ear_filters([az], n_fft=DEFAULT_N_FFT, sample_rate=sample_rate, pinna=prof.pinna,
                        steering_db=prof.steering_db)[0]
    else:
        h = sector_filters([az], n_fft=DEFAULT_N_FFT, sample_rate=sample_rate)[0]
    direct = np.zeros((2, n))
    # Zero-phase shadow magnitudes ring a little before time 0; centre them at sample 64.
    ir = np.roll(np.fft.irfft(_EAR_NORM * h, n=DEFAULT_N_FFT, axis=-1), 64, axis=-1)
    direct[:, : DEFAULT_N_FFT] = ir
    early = np.zeros((2, n))
    late = np.zeros((2, n))
    if prof.early:
        fir = bus_early_fir(prof, beta, bus, sample_rate)
        fir = np.roll(fir, 64, axis=-1)
        early[:, : fir.shape[1]] = fir
    if prof.late:
        imp = np.zeros(n)
        imp[64] = ROLE_DISTANCE_M[role] / LATE_REF_M
        late = late_gain(sample_rate) * coherence_mix(fdn_process(imp, sample_rate), sample_rate)
    return {"direct": direct, "early": early, "late": late}
