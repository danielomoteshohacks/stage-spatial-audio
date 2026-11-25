"""The cascade: levels 1 to 6 and the post-processing layer, with a per-level cache.

    mix --L1--> vocals | instrumental
    vocals --L2--> lead | backing
    instrumental --L3--> bass | drums | guitar | piano | other (+ a vocal residual)
    drums --L4--> kick | snare | toms | hi-hat | cymbals
    lead, backing, guitar, piano, other --L5--> dry | reverb
    guitar, piano, other, backing (dry) --L6--> one leaf per pan cluster
    leaves --post--> Wiener, consistency, repair, quality

Every level is an *engine*: an object with `separate(audio, sr) -> {stem: (2, n)}` and a
`name`. Neural engines (stage.separation.cascade.neural) load a model from configs/cascade;
the model-free engines are the DSP functions of this package. A level whose engine is missing or
whose licence is not enabled falls back to the DSP engine and the report says so. The tree
splits by subtraction (the second branch is parent minus the first), so the leaves of a level
always add up to its parent, and the final leaves to the mix.

Caching (decision 0023): each level's output is stored under the SHA-256 of its input audio,
the engine names and the parameters, so changing the scene, the HRTF or the placement never
re-separates, and re-running a level only recomputes what changed below it.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

from stage.separation.cascade import adress, dereverb, dsp, post
from stage.separation.cascade import config as cfg

LEAD_ROLES = {"lead": "lead_vocal", "backing": "backing_vocal", "guitar": "guitar", "piano": "keys",
              # "other" is everything a four- or six-stem model does not name: in most songs the
              # chords, keys, guitars and synths, the harmonic body of the record. Labelled "pad"
              # it was sent behind and above the listener (130 degrees, 30 up), which is what made
              # the spatial version sound hollow and worse than stereo (decision 0032).
              "other": "other", "bass": "bass", "kick": "kick", "snare": "snare", "toms": "toms",
              "hats": "cymbals", "cymbals": "cymbals"}
DEREVERB_STEMS = ("lead", "backing", "guitar", "piano", "other")
SPLIT_STEMS = ("backing", "guitar", "piano", "other")


class Engine(Protocol):
    name: str

    def separate(self, audio: NDArray, sample_rate: int) -> dict[str, NDArray]: ...


@dataclass
class CascadeResult:
    leaves: dict[str, NDArray]  # dry objects, each (2, n)
    reverb: dict[str, NDArray]  # per-leaf reverb returns, each (2, n)
    parents: dict[str, str]
    roles: dict[str, str]
    quality: dict[str, post.LeafQuality]
    report: dict[str, Any] = field(default_factory=dict)

    def all_parts(self) -> dict[str, NDArray]:
        return {**self.leaves, **{f"{k}~reverb": v for k, v in self.reverb.items()}}


class Cache:
    """Per-level results on disk, keyed by content hash (FLAC, 24 bit; a few ms per leaf)."""

    def __init__(self, root: Path | None) -> None:
        self.root = root
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(audio: NDArray, *parts: Any) -> str:
        h = hashlib.sha256(np.ascontiguousarray(audio, dtype=np.float32).tobytes())
        h.update(json.dumps(parts, sort_keys=True, default=str).encode())
        return h.hexdigest()[:32]

    def get(self, key: str) -> dict[str, NDArray] | None:
        if self.root is None or not (self.root / key / "ok").is_file():
            self.misses += 1
            return None
        out = {}
        gains = json.loads((self.root / key / "gains.json").read_text())
        for p in sorted((self.root / key).glob("*.flac")):
            x, _ = sf.read(str(p), dtype="float32", always_2d=True)
            out[p.stem] = x.T * np.float32(gains.get(p.stem, 1.0))
        self.hits += 1
        return out

    def put(self, key: str, sample_rate: int, stems: dict[str, NDArray]) -> None:
        if self.root is None:
            return
        d = self.root / key
        d.mkdir(parents=True, exist_ok=True)
        gains = {}
        for k, v in stems.items():
            v = np.asarray(v, dtype=np.float32)
            # A separated stem can exceed full scale; FLAC would clip it and the leaves would no
            # longer sum to the mix, so loud stems are stored scaled and restored on reading.
            peak = float(np.max(np.abs(v))) if v.size else 0.0
            gains[k] = max(peak / 0.99, 1.0)
            sf.write(str(d / f"{k}.flac"), (v / gains[k]).T, sample_rate, subtype="PCM_24")
        (d / "gains.json").write_text(json.dumps(gains))
        (d / "ok").write_text("1")


def _sum(parts: dict[str, NDArray]) -> NDArray:
    return sum(parts.values())


def _chunked_refine(mix: NDArray, parts: dict[str, NDArray], fn: Callable[
        [NDArray, dict[str, NDArray]], dict[str, NDArray]], sample_rate: int, chunk_s: float = 30.0,
        overlap_s: float = 1.5) -> dict[str, NDArray]:
    """Apply a refinement that needs the spectrogram of its whole input to long songs in chunks
    that overlap and cross-fade, so memory and time stay bounded and there is no seam."""
    from stage.separation.cascade.runner import chunk_plan, crossfade_window

    n = mix.shape[1]
    chunk, ov = int(chunk_s * sample_rate), int(overlap_s * sample_rate)
    if n <= chunk:
        return fn(mix, parts)
    starts = chunk_plan(n, chunk, ov)
    out = {k: np.zeros_like(v, dtype=np.float32) for k, v in parts.items()}
    norm = np.zeros(n, dtype=np.float32)
    win = crossfade_window(chunk, ov)
    for s in starts:
        w = win.copy()
        if s == starts[0]:
            w[:ov] = 1.0
        if s == starts[-1]:
            w[-ov:] = 1.0
        res = fn(mix[:, s : s + chunk], {k: v[:, s : s + chunk] for k, v in parts.items()})
        for k, v in res.items():
            out[k][:, s : s + chunk] += (v * w).astype(np.float32)
        norm[s : s + chunk] += w
    return {k: v / np.maximum(norm, 1e-8) for k, v in out.items()}


class Cascade:
    def __init__(self, preset: str = "best", engines: dict[str, Engine] | None = None,
                 cache_dir: Path | None = None, allowed: tuple[str, ...] = cfg.ALLOWED_DEFAULT,
                 ensemble_weights: Any = None, quality_threshold: float = 40.0) -> None:
        self.preset_name = preset
        self.preset = cfg.preset(preset)
        self.engines = engines or {}
        self.cache = Cache(cache_dir)
        self.allowed = allowed
        self.weights = ensemble_weights
        self.quality_threshold = quality_threshold
        self.report: dict[str, Any] = {"preset": preset, "levels": {}, "models": {},
                                       "skipped": [], "timing_s": {}}

    # -- engine lookup -------------------------------------------------------------------------
    def _engines_for(self, level: int) -> list[Engine]:
        spec_ids = self.preset["levels"].get(str(level))
        if not isinstance(spec_ids, list):
            return []
        models = cfg.models()
        out = []
        for mid in spec_ids:
            ok, why = cfg.usable(models[mid], self.allowed)
            if not ok:
                self.report["skipped"].append(why)
                continue
            if mid in self.engines:
                out.append(self.engines[mid])
                self.report["models"][mid] = {"licence": models[mid].licence,
                                              "class": models[mid].licence_class}
        return out

    def _timed(self, name: str, fn: Callable[[], Any]) -> Any:
        t0 = time.perf_counter()
        r = fn()
        self.report["timing_s"][name] = round(time.perf_counter() - t0, 2)
        return r

    # -- levels --------------------------------------------------------------------------------
    def level1(self, mix: NDArray, sr: int, fallback: dict[str, NDArray] | None) -> tuple[
            NDArray, NDArray]:
        engines = self._engines_for(1)
        if not engines:
            if fallback is None:
                raise RuntimeError("no level 1 engine and no four-stem fallback was given")
            v = fallback["vocals"]
            self.report["levels"]["1"] = "fallback four-stem separator"
            return v, mix - v
        key = Cache.key(mix, "L1", [e.name for e in engines], self.weights)
        hit = self.cache.get(key)
        if hit:
            return hit["vocals"], mix - hit["vocals"]
        ests = [e.separate(mix, sr)["vocals"] for e in engines]
        w = self.weights
        vocals = ests[0] if len(ests) == 1 else __import__(
            "stage.separation.cascade.ensemble", fromlist=["combine"]).combine(
                ests, w, sr, cfg.load()["ensemble"]["bands_hz"])
        self.cache.put(key, sr, {"vocals": vocals})
        self.report["levels"]["1"] = f"{len(ests)} model(s)" + (
            "" if w is not None or len(ests) == 1 else ", equal band weights (not yet fitted)")
        return vocals, mix - vocals

    def level2(self, vocals: NDArray, sr: int) -> dict[str, NDArray]:
        engines = self._engines_for(2)
        if not engines:
            self.report["levels"]["2"] = "azimuth split of the vocals (level 6 rules)"
            parts = dsp.split_vocals(vocals)
            return {"lead": parts["lead"],
                    "backing": sum(v for k, v in parts.items() if k != "lead") if len(parts) > 1
                    else np.zeros_like(vocals)}
        key = Cache.key(vocals, "L2", engines[0].name)
        hit = self.cache.get(key)
        lead = hit["lead"] if hit else engines[0].separate(vocals, sr)["vocals"]
        if not hit:
            self.cache.put(key, sr, {"lead": lead})
        self.report["levels"]["2"] = engines[0].name
        return {"lead": lead, "backing": vocals - lead}

    def level3(self, inst: NDArray, sr: int, fallback: dict[str, NDArray] | None) -> dict[
            str, NDArray]:
        engines = self._engines_for(3)
        if engines:
            key = Cache.key(inst, "L3", engines[0].name)
            hit = self.cache.get(key)
            stems = hit or engines[0].separate(inst, sr)
            if not hit:
                self.cache.put(key, sr, stems)
            self.report["levels"]["3"] = engines[0].name
        elif fallback is not None:
            stems = {k: fallback[k] for k in ("bass", "drums", "other")}
            self.report["levels"]["3"] = "fallback four-stem separator"
        else:
            raise RuntimeError("no level 3 engine and no four-stem fallback was given")
        out = {k: v for k, v in stems.items() if k in ("bass", "drums", "guitar", "piano", "other")}
        resid = inst - _sum(out)  # whatever the model left out (and a vocal residual) stays
        out["other"] = out.get("other", 0.0) + resid
        return out

    def level4(self, drums: NDArray, sr: int) -> dict[str, NDArray]:
        engines = self._engines_for(4)
        if not engines:
            self.report["levels"]["4"] = "band and pan rules (dsp)"
            return dsp.split_drums(drums, sr)
        key = Cache.key(drums, "L4", engines[0].name)
        hit = self.cache.get(key)
        stems = hit or engines[0].separate(drums, sr)
        if not hit:
            self.cache.put(key, sr, stems)
        self.report["levels"]["4"] = engines[0].name
        out = {("hats" if k == "hh" else k): v for k, v in stems.items()}
        out["snare"] = out.get("snare", 0.0) + (drums - _sum(out))  # exactness: residual to snare
        return out

    def level5(self, name: str, x: NDArray, sr: int) -> tuple[NDArray, NDArray]:
        """(dry, reverb) of a melodic stem; the reverb is zero when the guard bypasses."""
        engines = self._engines_for(5) if name in ("lead",) else []
        if engines:
            key = Cache.key(x, "L5", engines[0].name)
            hit = self.cache.get(key)
            dry = hit["dry"] if hit else engines[0].separate(x, sr)["dry"]
            if not hit:
                self.cache.put(key, sr, {"dry": dry})
            if not dereverb.guard(dry, x):
                self.report.setdefault("dereverb_bypassed", []).append(name)
                return x, np.zeros_like(x)
            return dry, x - dry
        if self.preset["levels"].get("5") not in ("dsp", None) and not engines and name != "lead":
            pass
        dry, wet, rt = dereverb.dereverb_dsp(x, sr)
        if not dereverb.guard(dry, x):
            self.report.setdefault("dereverb_bypassed", []).append(name)
            return x, np.zeros_like(x)
        self.report.setdefault("rt60_estimate_s", {})[name] = round(rt, 2)
        return dry, wet

    def level6(self, name: str, x: NDArray) -> dict[str, NDArray]:
        outs, centres, _ = adress.azimuth_split(x)
        if len(centres) < 2:
            return {name: x}
        parts: dict[str, NDArray] = {}
        for c, o in zip(centres, outs[:-1], strict=True):
            side = "left" if c < -0.3 else "right" if c > 0.3 else "centre"
            key, i = f"{name}_{side}", 2
            while key in parts:  # two clusters on one side must not overwrite each other
                key, i = f"{name}_{side}{i}", i + 1
            parts[key] = o
        first = next(iter(parts))
        parts[first] = parts[first] + outs[-1]  # the diffuse remainder joins the first part
        return parts

    # -- the run ---------------------------------------------------------------------------------
    def run(self, mix: NDArray, sr: int, fallback_stems: dict[str, NDArray] | None = None,
            refine: bool | None = None, quality: bool = True) -> CascadeResult:
        if refine is None:
            refine = bool(self.preset.get("refine", True))
        mix = np.asarray(mix, dtype=np.float32)
        voc, inst = self._timed("L1", lambda: self.level1(mix, sr, fallback_stems))
        vparts = self._timed("L2", lambda: self.level2(voc, sr))
        iparts = self._timed("L3", lambda: self.level3(inst, sr, fallback_stems))
        kit = self._timed("L4", lambda: self.level4(iparts.pop("drums"), sr))
        stems = {**vparts, **{k: v for k, v in iparts.items()}, **kit}
        dry, wet = {}, {}
        for k, v in stems.items():
            if k in DEREVERB_STEMS and np.mean(v**2) > 1e-9:
                dry[k], r = self._timed(f"L5.{k}", lambda k=k, v=v: self.level5(k, v, sr))
                if np.any(r):
                    wet[k] = r
            else:
                dry[k] = v
        leaves: dict[str, NDArray] = {}
        roles: dict[str, str] = {}
        leaf_parent: dict[str, str] = {}
        for k, v in dry.items():
            if k in SPLIT_STEMS and np.mean(v**2) > 1e-9:
                split = self._timed(f"L6.{k}", lambda k=k, v=v: self.level6(k, v))
            else:
                split = {k: v}
            for sk, sv in split.items():
                leaves[sk], leaf_parent[sk] = sv, k
                roles[sk] = LEAD_ROLES.get(k, "pad")
        parts = {**leaves, **{f"{k}~reverb": v for k, v in wet.items()}}
        if refine:
            parts = self._timed("post", lambda: _chunked_refine(
                mix, parts, lambda m, p: post.mixture_consistency(
                    m, post.multichannel_wiener(m, p, iterations=2)), sr))
        # The leaf quality estimate is most of the cascade's CPU time (7 of 8 s on a 20 s chunk).
        # It only drives merging, which needs it on every chunk, and the report, which needs it
        # once; a streamed job asks for it on its first chunk only.
        quality = (post.leaf_quality({k: v for k, v in parts.items() if "~" not in k}, mix)
                   if (quality or refine) else {})
        merged_map: dict[str, str] = {}
        if refine:
            keep, merged_map = post.merge_poor_leaves(
                {k: v for k, v in parts.items() if "~" not in k}, leaf_parent, quality,
                self.quality_threshold)
            parts = {**keep, **{k: v for k, v in parts.items() if "~" in k}}
            for gone in merged_map:
                roles.pop(gone, None)
        out_leaves = {k: v for k, v in parts.items() if "~" not in k}
        out_wet = {k.split("~")[0]: v for k, v in parts.items() if "~" in k}
        self.report.update({"merged_into_parent": merged_map,
                            "cache": {"hits": self.cache.hits, "misses": self.cache.misses},
                            "sum_error": float(np.abs(sum(parts.values()) - mix).max())})
        return CascadeResult(leaves=out_leaves, reverb=out_wet, parents=leaf_parent, roles=roles,
                             quality=quality, report=self.report)


FOUR_STEMS = ("vocals", "drums", "bass", "other")


def collapse_to_four(res: CascadeResult) -> dict[str, NDArray]:
    """The leaves (and their reverb returns) as the four stems every separator in SoundStage is
    compared on: vocals (lead and backing), drums (the whole kit), bass, and everything else."""
    out: dict[str, NDArray] = {k: np.zeros_like(next(iter(res.leaves.values())), dtype=np.float64)
                               for k in FOUR_STEMS}
    for name, x in res.leaves.items():
        parent = res.parents.get(name, name)
        key = ("vocals" if parent in ("lead", "backing") else "drums" if parent in (
            "kick", "snare", "toms", "hats", "cymbals") else "bass" if name == "bass" else "other")
        out[key] += x
    for name, x in res.reverb.items():
        out["vocals" if name in ("lead", "backing") else "other"] += x
    return out
