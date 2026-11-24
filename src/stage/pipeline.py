"""One track in, an A/B listening set out: load, separate (stems mode), render, levels, write.

Every stage records its status, duration and error, and no stage failure escapes `run`: a
listener who uploads a track should always get either a playable result or a report that says
exactly which stage failed and why. If separation fails or is unavailable, the whole mix is
rendered in Lite instead and the fallback is recorded, so the screen never presents a Lite
render as a stems render.

The renderer itself (`stage.render`) is the reviewed reference and is only called from here.
"""

from __future__ import annotations

import json
import math
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

from stage import __version__
from stage.analysis.excerpt import auto_start
from stage.engines import DEFAULT_PROFILE, check_profile, is_v2
from stage.engines import render as render_engine
from stage.guard.levels import peak_gain, rms
from stage.guard.report import build_report
from stage.io import read_audio, to_stereo
from stage.render.sectors import WIDEN_BETA_MAX, WIDEN_BETA_MIN
from stage.separation.demucs_sep import STEM_NAMES, Separation, separate

MODES = ("lite", "stems")
STAGES = ("load", "separate", "render", "levels", "guard", "write")
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
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    check_profile(profile)
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
    sep_fn: Separator = separator or partial(separate, model="htdemucs", device="auto")
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
        "requested_mode": mode,
        "profile": profile,
        "beta": float(beta),
        "separation": None,
        "levels": None,
        "guard": None,
        "engine": None,
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
        ok, sep = st.run("separate", lambda: _validate_separation(sep_fn(audio, sr), n))
        if not ok:
            effective_mode = "lite"
            fallback = {"from": "stems", "to": "lite", "reason": st.records["separate"].error}
        else:
            report["separation"] = {
                "model": sep.model, "device": sep.device, "stems": list(STEM_NAMES),
                "residual_snr_db": _finite(sep.residual_snr_db),
                "residual_is_zero": sep.residual_snr_db == float("inf"),
                "notes": list(sep.notes),
            }

    # render
    spatial: NDArray[np.float64] | None = None
    spatial_stems: dict[str, NDArray[np.float64]] = {}
    if audio is None:
        st.skip("render", "nothing was loaded")
    else:
        def _render() -> NDArray[np.float64]:
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
            gain = peak_gain(max(peaks))
            for name in list(spatial_stems):
                spatial_stems[name] = spatial_stems[name] * (scale * gain)
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
            if spatial is None:
                return
            _write_flac(out / "spatial.flac", spatial, sr)
            outputs["spatial"] = "spatial.flac"
            if guard_report is not None:
                (out / "report.json").write_text(json.dumps(guard_report, indent=2),
                                                 encoding="utf-8")
                outputs["report"] = "report.json"
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
