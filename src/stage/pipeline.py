"""One track in, an A/B listening set out: load, separate (stems mode), render, levels, write.

Every stage records its status, duration and error, and no stage failure escapes `run`: a
listener who uploads a track should always get either a playable result or a report that says
exactly which stage failed and why. If separation fails or is unavailable, the whole mix is
rendered in Lite instead and the fallback is recorded, so the screen never presents a Lite
render as a stems render.

The renderer itself (`stage.render`) is the reviewed reference and is only called from here.
"""

from __future__ import annotations

import copy
import json
import math
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

from stage import __version__
from stage.analysis.excerpt import auto_start
from stage.engines import DEFAULT_PROFILE, check_profile, is_v2
from stage.engines import render as render_engine
from stage.guard.levels import limit_peak, peak_gain, rms
from stage.guard.report import build_report
from stage.io import read_audio, to_stereo
from stage.render.sectors import WIDEN_BETA_MAX, WIDEN_BETA_MIN
from stage.scene.analysis import analyse_song
from stage.scene.genre import detect_genre
from stage.scene.plan import build_plan, plan_json, templates, validate_plan
from stage.scene.render import render_scene
from stage.separation.chain import separate_chain
from stage.separation.demucs_sep import STEM_NAMES, Separation
from stage.spatial.neutral import split_low_high

MODES = ("lite", "stems")
STAGES = ("load", "separate", "analyse", "render", "levels", "guard", "write")
#: The default motion depth of the plan (0 is a static scene, 1 the template's full motion).
DEFAULT_MOTION = 0.5
#: 24-bit FLAC: lossless like WAV at roughly half the size, which matters on mobile data.
FLAC_SUBTYPE = "PCM_24"
RUN_SCHEMA_VERSION = 1

Separator = Callable[[NDArray[np.float64], int], Separation]
StageCallback = Callable[[dict[str, Any]], None]


@dataclass
class StageRecord:
    name: str
    status: str = "pending"  # pending, running, ok, failed, skipped
    duration_s: float = 0.0
    error: str | None = None


@dataclass
class RunResult:
    """What one run produced. `ok` is True when spatial.flac was written."""

    out_dir: Path
    ok: bool
    requested_mode: str
    mode: str
    stages: list[StageRecord]
    report: dict[str, Any]
    outputs: dict[str, Any] = field(default_factory=dict)
    fallback: dict[str, str] | None = None

    def stage(self, name: str) -> StageRecord:
        return next(s for s in self.stages if s.name == name)


class _Stages:
    """Times each stage and turns any exception into a failed record instead of a crash."""

    def __init__(self, names: tuple[str, ...], on_stage: StageCallback | None) -> None:
        self.records = {n: StageRecord(n) for n in names}
        self.order = names
        self.on_stage = on_stage

    def emit(self, rec: StageRecord) -> None:
        if self.on_stage is None:
            return
        event = {"stage": rec.name, "index": self.order.index(rec.name), "total": len(self.order),
                 **{k: v for k, v in asdict(rec).items() if k != "name"}}
        try:
            self.on_stage(event)
        except Exception:  # a broken progress display must not take the run down with it
            pass

    def skip(self, name: str, reason: str) -> None:
        rec = self.records[name]
        rec.status, rec.error = "skipped", reason
        self.emit(rec)

    def run(self, name: str, fn: Callable[[], Any]) -> tuple[bool, Any]:
        rec = self.records[name]
        rec.status = "running"
        self.emit(rec)
        t0 = time.perf_counter()
        try:
            value = fn()
        except Exception as exc:
            rec.duration_s = time.perf_counter() - t0
            rec.status = "failed"
            rec.error = f"{type(exc).__name__}: {exc}"
            self.emit(rec)
            return False, None
        rec.duration_s = time.perf_counter() - t0
        rec.status = "ok"
        self.emit(rec)
        return True, value


def _db(x: float) -> float | None:
    return round(20.0 * math.log10(x), 3) if x > 0 else None


def _finite(x: float) -> float | None:
    """JSON has no infinity; a perfect split is reported as null with a note instead."""
    return round(x, 3) if math.isfinite(x) else None


def _validate_separation(sep: Separation, n: int) -> Separation:
    if set(sep.stems) != set(STEM_NAMES):
        raise ValueError(f"separator returned stems {sorted(sep.stems)}, expected {STEM_NAMES}")
    for name, stem in sep.stems.items():
        if stem.shape != (2, n):
            raise ValueError(f"stem {name} has shape {stem.shape}, expected (2, {n})")
        if not np.all(np.isfinite(stem)):
            raise ValueError(f"stem {name} contains NaN or infinite samples")
    return sep


def _write_flac(path: Path, x: NDArray[np.float64], sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Integer FLAC cannot hold samples beyond full scale. The renders are already peak-limited;
    # clipping here only guards an original whose float source went over 0 dBFS.
    sf.write(str(path), np.clip(x, -1.0, 1.0).T, int(sample_rate), format="FLAC",
             subtype=FLAC_SUBTYPE)


# --- The track cache -----------------------------------------------------------------------------
# Separation is the expensive, GPU-bound step, and the analysis and the genre tagger take
# seconds; a listener who changes the space, the character, the motion or the plan should not pay
# for them again. They are kept per track (a content hash, decided by stage.service) for the
# service's time-to-live, as float32 stems in an .npz and the analysis as JSON.


def _load_stems(cache: Path | None, sr: int, n: int) -> Separation | None:
    if cache is None or not (cache / "stems.npz").is_file():
        return None
    try:
        meta = json.loads((cache / "separation.json").read_text(encoding="utf-8"))
        with np.load(cache / "stems.npz", allow_pickle=False) as z:
            stems = {k: z[k].astype(np.float64) for k in STEM_NAMES}
    except (OSError, ValueError, KeyError):
        return None
    if meta.get("sample_rate") != sr or any(s.shape != (2, n) for s in stems.values()):
        return None
    return Separation(stems=stems, sample_rate=sr, residual_snr_db=meta["residual_snr_db"],
                      model=meta["model"], device=meta["device"],
                      notes=[*meta.get("notes", []), "stems from the track cache"],
                      chain=meta.get("chain", []), details=meta.get("details", {}))


def _save_stems(cache: Path | None, sep: Separation) -> None:
    if cache is None:
        return
    np.savez(cache / "stems.npz", **{k: v.astype(np.float32) for k, v in sep.stems.items()})
    (cache / "separation.json").write_text(json.dumps({
        "sample_rate": sep.sample_rate, "model": sep.model, "device": sep.device,
        "residual_snr_db": sep.residual_snr_db if math.isfinite(sep.residual_snr_db) else 1e9,
        "notes": sep.notes, "chain": sep.chain, "details": sep.details}), encoding="utf-8")


def _load_analysis(cache: Path | None, with_stems: bool):
    from stage.scene.analysis import Section, SongAnalysis

    path = None if cache is None else cache / f"analysis_{'stems' if with_stems else 'mix'}.json"
    if path is None or not path.is_file():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    d["sections"] = [Section(**s) for s in d["sections"]]
    return SongAnalysis(**d)


def _save_analysis(cache: Path | None, song, with_stems: bool) -> None:
    if cache is not None:
        (cache / f"analysis_{'stems' if with_stems else 'mix'}.json").write_text(
            json.dumps(song.as_dict()), encoding="utf-8")


def _cached_genre(cache: Path | None) -> dict[str, Any] | None:
    if cache is None or not (cache / "genre.json").is_file():
        return None
    return json.loads((cache / "genre.json").read_text(encoding="utf-8"))


def _save_genre(cache: Path | None, chosen: dict[str, Any]) -> None:
    if cache is not None and not (cache / "genre.json").exists():
        (cache / "genre.json").write_text(json.dumps(chosen), encoding="utf-8")


def run(
    path: str | Path,
    *,
    mode: str = "lite",
    profile: str = DEFAULT_PROFILE,
    beta: float = 2.0,
    start: float | str | None = "auto",
    seconds: float | None = None,
    out_dir: str | Path,
    separator: Separator | None = None,
    on_stage: StageCallback | None = None,
    genre: str | None = None,
    motion: float = DEFAULT_MOTION,
    plan: dict[str, Any] | None = None,
    export_bed: bool = False,
    tag_genre: bool = True,
    cache_dir: str | Path | None = None,
    track_id: str | None = None,
) -> RunResult:
    """Process one file and write original.flac, spatial.flac, stems (stems mode) and run.json.

    Args:
        path: an audio file soundfile can read.
        mode: "lite" renders the whole mix; "stems" separates first and renders each stem.
        profile: a name from `stage.engines.profile_names()` ("space:<name>" for v2).
        beta: widen strength, 1.0 to 2.4.
        start: seconds into the file, None for the beginning, or "auto" for the loudest window
            of length `seconds` (the chorus or drop, see stage.analysis.excerpt).
        seconds: the excerpt length; None means the rest of the file.
        out_dir: created if needed; existing files of the same names are replaced.
        separator: called as separator(audio, sample_rate) -> Separation. Defaults to Demucs.
        on_stage: called with a dict per stage transition (running, then ok/failed/skipped).
        genre: a template name, or None to let the tagger choose (or the default template).
        motion: motion depth 0 to 1 for the v2 scene.
        plan: an edited plan.json to render instead of building one (the /rerender path).
        export_bed: also write the 7.1.4 bed and objects as a 12-channel WAV.
        tag_genre: run the AudioSet tagger when no genre is given (where it is installed).
        cache_dir: the track's cache folder (stage.service): separated stems, the analysis and
            the excerpt are kept there, so a re-render with other settings never re-separates.
        track_id: the cache key, written to run.json for /rerender.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    check_profile(profile)
    if not 0.0 <= float(motion) <= 1.0:
        raise ValueError(f"motion must be between 0 and 1, got {motion}")
    if plan is not None:
        validate_plan(plan)
    if not WIDEN_BETA_MIN <= beta <= WIDEN_BETA_MAX:
        raise ValueError(f"beta must be in [{WIDEN_BETA_MIN}, {WIDEN_BETA_MAX}], got {beta}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    start_mode = "auto" if start == "auto" else ("file" if start is None else "manual")
    auto_info: dict[str, float] | None = None
    if start == "auto":
        if seconds is None:
            start = 0.0  # the whole file: there is no window to choose
        else:
            try:
                found = auto_start(path, float(seconds))
                start = found.start_s
                auto_info = {"loudness_lufs": found.loudness_lufs}
            except Exception:
                # An unreadable file is reported by the load stage with its own error.
                start = 0.0
    start = float(start or 0.0)
    sep_fn: Separator = separator or separate_chain
    track_id = track_id or f"{Path(path).stem[:40]}-{start:.1f}s"
    cache = Path(cache_dir) if cache_dir is not None else None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
    st = _Stages(STAGES, on_stage)
    effective_mode = mode
    fallback: dict[str, str] | None = None
    report: dict[str, Any] = {
        "schema_version": RUN_SCHEMA_VERSION,
        "app": "SoundStage",
        "stage_version": __version__,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input": {"name": Path(path).name, "start_s": start, "start_mode": start_mode,
                  "auto_start": auto_info,
                  "requested_seconds": None if seconds is None else float(seconds)},
        "track_id": track_id,
        "requested_mode": mode,
        "profile": profile,
        "beta": float(beta),
        "separation": None,
        "levels": None,
        "guard": None,
        "engine": None,
        "analysis": None,
    }
    outputs: dict[str, Any] = {}

    # load
    def _load() -> tuple[NDArray[np.float64], int, int]:
        audio, sr = read_audio(path, start_s=start, duration_s=seconds)
        channels = audio.shape[0]
        audio = to_stereo(audio)
        if audio.shape[1] == 0:
            raise ValueError("the requested excerpt is empty (start is past the end of the file)")
        return audio, sr, channels

    ok, loaded = st.run("load", _load)
    audio: NDArray[np.float64] | None = None
    sr = 0
    if ok:
        audio, sr, channels = loaded
        report["input"].update(sample_rate=int(sr), channels=int(channels),
                               duration_s=round(audio.shape[1] / sr, 6))

    # separate
    sep: Separation | None = None
    if audio is None:
        st.skip("separate", "nothing was loaded")
    elif mode != "stems":
        st.skip("separate", "lite mode renders the whole mix")
    else:
        n = audio.shape[1]
        cached = _load_stems(cache, sr, n)

        def _separate() -> Separation:
            if cached is not None:
                return cached
            result = _validate_separation(sep_fn(audio, sr), n)
            _save_stems(cache, result)
            return result

        ok, sep = st.run("separate", _separate)
        if not ok:
            effective_mode = "lite"
            fallback = {"from": "stems", "to": "lite", "reason": st.records["separate"].error}
        else:
            report["separation"] = {
                "model": sep.model, "device": sep.device, "stems": list(STEM_NAMES),
                "residual_snr_db": _finite(sep.residual_snr_db),
                "residual_is_zero": sep.residual_snr_db == float("inf"),
                "notes": list(sep.notes),
                "chain": list(sep.chain),
                "details": dict(sep.details),
            }

    # analyse: song analysis, genre and the plan (v2 only)
    scene_plan: dict[str, Any] | None = None
    if audio is None:
        st.skip("analyse", "nothing was loaded")
    elif not is_v2(profile):
        st.skip("analyse", "the v1 profiles have no plan")
    else:
        def _analyse() -> dict[str, Any]:
            stems = sep.stems if sep is not None else None
            song = _load_analysis(cache, sep is not None)
            if song is None:
                song = analyse_song(audio, sr, stems)
                _save_analysis(cache, song, sep is not None)
            report["analysis"] = {"tempo_bpm": round(song.tempo_bpm, 2),
                                  "sections": len(song.sections),
                                  "beats": len(song.beats_s), "method": song.method}
            if plan is not None:
                given = copy.deepcopy(plan)
                given["mode"] = "stems" if sep is not None else "lite"
                report["analysis"]["genre"] = {"genre": given.get("genre"), "source": "plan"}
                return given
            if genre:
                chosen = {"genre": genre, "scores": {}, "source": "user", "detail": None}
            elif tag_genre:
                chosen = _cached_genre(cache) or detect_genre(audio, sr, templates())
                _save_genre(cache, chosen)
            else:
                chosen = {"genre": None, "scores": {}, "source": "default",
                          "detail": "tagging off"}
            report["analysis"]["genre"] = chosen
            return build_plan(song, track_id=track_id, mode="stems" if sep else "lite",
                              genre=chosen["genre"], space=profile[len("space:"):],
                              motion_depth=float(motion), genre_source=chosen["source"],
                              genre_scores=chosen["scores"]), song
        ok, made = st.run("analyse", _analyse)
        if ok:
            scene_plan, song = made if isinstance(made, tuple) else (made, None)
            if song is not None:
                report["analysis"]["song"] = song.as_dict()

    # render
    spatial: NDArray[np.float64] | None = None
    spatial_stems: dict[str, NDArray[np.float64]] = {}
    scene_objects: dict[str, NDArray[np.float64]] = {}
    bed: NDArray[np.float64] | None = None
    if audio is None:
        st.skip("render", "nothing was loaded")
    elif is_v2(profile) and scene_plan is None:
        st.skip("render", "there is no plan to render")
    else:
        def _render() -> NDArray[np.float64]:
            nonlocal bed
            if scene_plan is not None:
                res = render_scene(audio, sr, scene_plan, sep.stems if sep else None,
                                   export_bed=export_bed)
                report["engine"] = res.info
                low, _ = split_low_high(audio, sr, float(scene_plan.get("crossover_hz", 120.0)))
                # The untouched low band is an object of its own, so the object stems sum to the
                # render exactly and soloing them in the player stays honest.
                scene_objects["low_end"] = low
                scene_objects.update(res.objects)
                bed = res.bed
                return res.binaural
            if sep is None:
                y, info = render_engine(audio, sr, profile, beta)
                report["engine"] = info
                return y
            # One stem at a time: the renderer's working arrays (STFT, analysis, sector
            # outputs) dominate memory, so rendering in sequence and keeping only the
            # finished (2, n) outputs keeps the peak near that of a single Lite render.
            total = np.zeros_like(audio)
            for name in STEM_NAMES:
                y, info = render_engine(sep.stems[name], sr, profile, beta)
                report["engine"] = info
                total += y
                spatial_stems[name] = y
            return total

        ok, spatial = st.run("render", _render)
        if not ok:
            spatial_stems.clear()

    # levels
    if spatial is None:
        st.skip("levels", "there is no render to level")
    else:
        def _levels() -> NDArray[np.float64]:
            target = rms(audio)
            raw = rms(spatial)
            if is_v2(profile):
                # v2 is loudness-matched inside the renderer with the bass passed through, so
                # an RMS match here would move the record's bass with the rest; only the peak
                # safety applies.
                scale = 1.0
            else:
                scale = 1.0 if raw == 0.0 else target / raw
            matched = spatial * scale
            # One shared gain for the full render and every stem, so soloing and muting stems
            # in the player sums back to exactly spatial.flac; it also keeps each stem file
            # below the ceiling on its own.
            peaks = [float(np.max(np.abs(matched)))]
            peaks += [scale * float(np.max(np.abs(y))) for y in spatial_stems.values()]
            peaks += [scale * float(np.max(np.abs(y))) for y in scene_objects.values()]
            gain = peak_gain(max(peaks))
            for name in list(spatial_stems):
                spatial_stems[name] = spatial_stems[name] * (scale * gain)
            for name in list(scene_objects):
                scene_objects[name] = scene_objects[name] * (scale * gain)
            leveled = matched * gain
            report["levels"] = {
                "original_rms_dbfs": _db(target),
                "spatial_raw_rms_dbfs": _db(raw),
                "spatial_rms_dbfs": _db(rms(leveled)),
                "peak_gain_db": round(20.0 * math.log10(gain), 3),
                "peak_limited": gain < 1.0,
            }
            return leveled

        ok, leveled = st.run("levels", _levels)
        spatial = leveled if ok else None

    # guard
    guard_report: dict[str, Any] | None = None
    if spatial is None:
        st.skip("guard", "there is no render to check")
    else:
        def _guard() -> dict[str, Any]:
            return build_report(audio, spatial, sr, {"engine": __version__, "profile": profile,
                                                     "mode": effective_mode})

        ok, guard_report = st.run("guard", _guard)
        if ok:
            report["guard"] = {"verdict": guard_report["verdict"],
                               "reasons": guard_report["reasons"]}

    # write
    if audio is None:
        st.skip("write", "nothing was loaded")
    else:
        def _write() -> None:
            _write_flac(out / "original.flac", audio, sr)
            outputs["original"] = "original.flac"
            if cache is not None and not (cache / "original.flac").exists():
                _write_flac(cache / "original.flac", audio, sr)
            if spatial is None:
                return
            _write_flac(out / "spatial.flac", spatial, sr)
            outputs["spatial"] = "spatial.flac"
            if guard_report is not None:
                (out / "report.json").write_text(json.dumps(guard_report, indent=2),
                                                 encoding="utf-8")
                outputs["report"] = "report.json"
            if scene_plan is not None:
                (out / "plan.json").write_text(plan_json(scene_plan), encoding="utf-8")
                outputs["plan"] = "plan.json"
            if scene_objects:
                outputs["objects"] = {}
                for name, y in scene_objects.items():
                    _write_flac(out / "objects" / f"{name}.flac", y, sr)
                    outputs["objects"][name] = f"objects/{name}.flac"
            if bed is not None:
                # The 7.1.4 export for producers: a 12-channel 24-bit WAV in the ITU-R BS.2051
                # System J order (L R C LFE Ls Rs Lrs Rrs Ltf Rtf Ltr Rtr), with its own peak
                # safety because loudspeaker feeds sum differently from headphone signals.
                data, _ = limit_peak(bed)
                path = out / "bed_7_1_4.wav"
                sf.write(str(path), data.T, sr, subtype="PCM_24")
                outputs["bed_7_1_4"] = "bed_7_1_4.wav"
            if sep is not None and spatial_stems:
                outputs["stems"], outputs["stems_spatial"] = {}, {}
                for name in STEM_NAMES:
                    _write_flac(out / "stems" / f"{name}.flac", sep.stems[name], sr)
                    outputs["stems"][name] = f"stems/{name}.flac"
                    _write_flac(out / "stems_spatial" / f"{name}.flac", spatial_stems[name], sr)
                    outputs["stems_spatial"][name] = f"stems_spatial/{name}.flac"

        st.run("write", _write)

    stages = [st.records[n] for n in STAGES]
    ok_run = "spatial" in outputs
    report.update(
        mode=effective_mode,
        fallback=fallback,
        stages=[{"name": s.name, "status": s.status, "duration_s": round(s.duration_s, 4),
                 "error": s.error} for s in stages],
        outputs={"run": "run.json", **outputs},
        ok=ok_run,
    )
    try:
        (out / "run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError:
        # The report is still returned in memory; the caller sees ok and the stages.
        report["outputs"].pop("run", None)
        report.setdefault("errors", []).append(traceback.format_exc(limit=1).strip())
    return RunResult(
        out_dir=out, ok=ok_run, requested_mode=mode, mode=effective_mode, stages=stages,
        report=report, outputs=outputs, fallback=fallback,
    )
