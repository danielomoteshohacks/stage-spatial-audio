"""The model-free levels of the cascade: from four stems to leaves with SoundStage's own DSP.

This is what runs on a CPU with no weights: it takes the four stems any separator gives (the
SoundStage Separator, htdemucs, or the cascade's own level 1 and 3) and refines them into the
leaves the scene planner places, using azimuth discrimination (adress.py) and band and pan
rules for the kit, then the post-processing layer (post.py).

* vocals -> lead (the centre cluster) and backing_left / backing_right (the side clusters).
* drums -> kick (below about 150 Hz), snare (centre, 150 Hz to 4 kHz), toms (sides, same band)
  and hats (above about 4 kHz). The band edges are smooth cross-fades, not brick walls, and
  the three masks sum to one, so the kit adds back up exactly. SPECULATIVE rule set: the neural
  drum model (level 4) replaces it on the Space.
* bass -> bass.
* other -> one leaf per pan cluster (other_left, other_centre, other_right), each tagged "pad"
  when it is sustained (harmonic share above 0.9) and "pluck" otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from stage.analysis.stft import istft, stft
from stage.separation.cascade import post
from stage.separation.cascade.adress import (
    azimuth_split,
    find_pan_clusters,
    pan_map,
)

KIT_N_FFT = 2048
KIT_HOP = 512


@dataclass
class Leaves:
    stems: dict[str, NDArray]
    leaves: dict[str, NDArray]
    parents: dict[str, str]  # leaf -> the stem it came from
    roles: dict[str, str]
    quality: dict[str, post.LeafQuality] = field(default_factory=dict)
    info: dict = field(default_factory=dict)


def _smooth_step(f: NDArray, lo: float, hi: float) -> NDArray:
    """0 below `lo`, 1 above `hi`, raised cosine between (on a log-frequency axis)."""
    x = np.clip((np.log(np.maximum(f, 1.0)) - np.log(lo)) / (np.log(hi) - np.log(lo)), 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * x)


def split_drums(drums: NDArray, sample_rate: int) -> dict[str, NDArray]:
    """kick, snare, toms and hats from the kit by band and pan; the parts sum to `drums`."""
    n = drums.shape[1]
    spec = stft(drums, n_fft=KIT_N_FFT, hop=KIT_HOP)
    freqs = np.fft.rfftfreq(KIT_N_FFT, 1.0 / sample_rate)
    pan, conf = pan_map(spec[0], spec[1])
    high = _smooth_step(freqs, 3000.0, 5000.0)[np.newaxis, :]
    low = 1.0 - _smooth_step(freqs, 120.0, 220.0)[np.newaxis, :]
    mid = np.clip(1.0 - high - low, 0.0, 1.0)
    side = np.clip((np.abs(pan) - 0.2) / 0.3, 0.0, 1.0) * conf
    masks = {"kick": low, "hats": high, "snare": mid * (1.0 - side), "toms": mid * side}
    out = {k: istft(spec * m[np.newaxis], n, n_fft=KIT_N_FFT, hop=KIT_HOP)
           for k, m in masks.items()}
    return out


def _sustain(x: NDArray) -> float:
    from stage.scene.render import hpss

    h, _ = hpss(x)
    return float(np.sum(h**2) / (np.sum(x**2) + 1e-20))


def split_vocals(vocals: NDArray) -> dict[str, NDArray]:
    """lead, and backing_left / backing_right when the stem has side clusters."""
    centres = _clusters(vocals, min_share=0.04)
    side = [c for c in centres if abs(c) >= 0.3]
    if not side:
        return {"lead": vocals}
    use = [0.0] + side
    outs, _, _ = azimuth_split(vocals, use, sigma=0.3)
    res = {"lead": outs[0] + outs[-1]}  # the diffuse remainder stays with the lead
    for c, o in zip(side, outs[1:-1], strict=True):
        res["backing_left" if c < 0 else "backing_right"] = o
    return res


def _clusters(x: NDArray, min_share: float = 0.12) -> list[float]:
    spec = stft(x, n_fft=4096, hop=1024)
    pan, conf = pan_map(spec[0], spec[1])
    energy = np.abs(spec[0]) ** 2 + np.abs(spec[1]) ** 2
    return [c.centre for c in find_pan_clusters(pan, conf, energy, min_share=min_share)]


def split_other(other: NDArray) -> tuple[dict[str, NDArray], dict[str, str]]:
    centres = _clusters(other, min_share=0.08)
    if len(centres) < 2:
        return {"other": other}, {"other": "pad" if _sustain(other) > 0.9 else "pluck"}
    outs, used, _ = azimuth_split(other, centres, sigma=0.3)
    leaves: dict[str, NDArray] = {}
    roles: dict[str, str] = {}
    for c, o in zip(used, outs[:-1], strict=True):
        name = "other_left" if c < -0.3 else "other_right" if c > 0.3 else "other_centre"
        base, i = name, 2
        while name in leaves:  # two clusters on one side must not overwrite each other
            name, i = f"{base}{i}", i + 1
        leaves[name] = o
        roles[name] = "pad" if _sustain(o) > 0.9 else "pluck"
    leaves[next(iter(leaves))] = leaves[next(iter(leaves))] + outs[-1]  # remainder joins one
    return leaves, roles


def dsp_cascade(mix: NDArray, sample_rate: int, stems: dict[str, NDArray],
                refine: bool = True, wiener_iterations: int = 2) -> Leaves:
    """Four stems in, leaves out, refined; the leaves add up to the mix."""
    leaves: dict[str, NDArray] = {}
    parents: dict[str, str] = {}
    roles: dict[str, str] = {}
    voc = split_vocals(stems["vocals"])
    for k, v in voc.items():
        leaves[k], parents[k], roles[k] = v, "vocals", "lead_vocal" if k == "lead" else "backing"
    for k, v in split_drums(stems["drums"], sample_rate).items():
        leaves[k], parents[k], roles[k] = v, "drums", k
    leaves["bass"], parents["bass"], roles["bass"] = stems["bass"], "bass", "bass"
    oth, oroles = split_other(stems["other"])
    for k, v in oth.items():
        leaves[k], parents[k], roles[k] = v, "other", oroles[k]
    info: dict = {"levels": ["vocals pan split", "kit band/pan split", "other pan split"]}
    if refine:
        leaves = post.multichannel_wiener(mix, leaves, iterations=wiener_iterations)
        leaves, rates = post.repair_musical_noise(mix, leaves)
        leaves = post.restore_transients(
            mix, leaves, [k for k in leaves if parents[k] == "drums"], sample_rate)
        leaves = post.mixture_consistency(mix, leaves)
        info["flicker_before_repair"] = {k: round(v, 2) for k, v in rates.items()}
        info["post"] = ["multichannel wiener", "musical-noise repair", "transient restoration",
                        "mixture consistency"]
    quality = post.leaf_quality(leaves, mix)
    return Leaves(stems=stems, leaves=leaves, parents=parents, roles=roles, quality=quality,
                  info=info)
