"""A streamed whole-song job: separate, place and render in overlapping chunks, emit as they finish.

Decision 0027. One job is one song. Its life:

1. load the whole file and analyse the whole mix (tempo, beats, sections; half a second for four
   minutes), tag the genre from a short excerpt;
2. for each chunk (the first is short, so sound starts early): separate it with a little context
   on both sides (the cascade caches per content hash, so a re-run is free), build the plan from
   the first chunk's leaves, detect that chunk's events, render it with the song's clock,
   cross-fade it into the previous chunk (stage.stream.segments) and encode the finished part as a
   segment with codec context on both sides (stage.stream.codec);
3. when the last chunk is done: the whole render is written as FLAC, the fidelity guard runs on the
   whole song, and run.json records stage times, the real-time factor and the time to first sound.

State is a plain dict that the HTTP layer serves as JSON while the job runs, so a client can show
progress per chunk and start playing the first segment as soon as it exists.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

from stage.io.audio import read_audio, to_stereo
from stage.scene.analysis import SongAnalysis, analyse_song
from stage.scene.plan import CHARACTERS, DEFAULT_GENRE
from stage.scene3.events import detect_events
from stage.scene3.plan import build_plan_v3, infer_role, plan_json, roles_config
from stage.scene3.render import render_v3
from stage.stream import codec
from stage.stream.guard import guard_windows
from stage.stream.segments import Assembler, chunk_spans

CONTEXT_S = 2.0  # audio either side of a chunk given to the separator, trimmed afterwards
Provider = Callable[[NDArray, int], tuple[dict[str, NDArray], dict[str, NDArray], dict[str, Any]]]


@dataclass
class JobOptions:
    preset: str = "fast"
    genre: str | None = None
    motion: float = 0.5
    character: str = "balanced"
    head: str = "D1"
    space: str | None = None  # None: the genre's (the dry stage)
    fmt: str = "opus"
    start_s: float = 0.0
    seconds: float | None = None  # None: the whole song
    chunk_s: float = 20.0
    first_s: float = 8.0
    overlap_s: float = 1.5
    stems: bool = False  # also write the per-object stems of the whole song at the end

    def validate(self) -> None:
        if self.character not in CHARACTERS:
            raise ValueError(f"character must be one of {sorted(CHARACTERS)}")
        if not 0.0 <= self.motion <= 1.0:
            raise ValueError("motion must be between 0 and 1")
        if self.fmt not in codec.available_formats():
            raise ValueError(f"format {self.fmt!r} is not available; use "
                             f"{codec.available_formats()}")
        if self.seconds is not None and self.seconds < 1.0:
            raise ValueError("seconds must be at least 1")


@dataclass
class Job:
    id: str
    dir: Path
    options: JobOptions
    state: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    created: float = field(default_factory=time.time)

    def update(self, **kw: Any) -> None:
        with self.lock:
            self.state.update(kw)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.state, default=float))


def new_job(root: Path, options: JobOptions) -> Job:
    options.validate()
    jid = uuid.uuid4().hex[:12]
    d = root / "v3" / jid
    (d / "seg").mkdir(parents=True, exist_ok=True)
    job = Job(jid, d, options)
    job.state = {"id": jid, "status": "queued", "stage": "queued", "segments": [], "done": False,
                 "error": None, "chunks_total": 0, "chunks_done": 0, "plan": None,
                 "options": {k: v for k, v in options.__dict__.items()}, "timings": {},
                 "formats": codec.available_formats()}
    return job


# --- Leaf providers -------------------------------------------------------------------------------


def lite_leaves(audio: NDArray, sr: int) -> tuple[dict, dict, dict]:
    """Model-free leaves when no separator is available: bass, percussive centre and sides,
    harmonic centre, harmonic left and right. Honest and weak; run.json says so."""
    from scipy.signal import butter, sosfiltfilt

    from stage.scene.render import hpss
    from stage.separation.cascade.adress import azimuth_split

    x = np.asarray(audio, dtype=np.float64)
    sos = butter(4, 160.0, "lowpass", fs=sr, output="sos")
    bass = sosfiltfilt(sos, x, axis=-1)
    rest = x - bass
    harm, perc = hpss(rest)
    leaves: dict[str, NDArray] = {"bass": bass}
    for name, part in (("harm", harm), ("perc", perc)):
        outs, centres, _ = azimuth_split(part, [-0.6, 0.0, 0.6])
        labels = ("left", "centre", "right")
        for lab, o in zip(labels, outs[:-1], strict=True):
            leaves[f"{name}_{lab}"] = o
        leaves[f"{name}_centre"] = leaves[f"{name}_centre"] + outs[-1]
    roles = {"harm_centre": "lead_vocal", "perc_centre": "snare", "perc_left": "cymbals",
             "perc_right": "cymbals", "harm_left": "guitar", "harm_right": "guitar"}
    info = {"provider": "model-free (no separator available)", "roles": roles}
    return leaves, {}, info


def make_cascade_provider(preset: str, engines: dict | None, cache_dir: Path | None,
                          separator: Callable | None) -> Provider:
    """The cascade over a separator's stems.

    The separator runs ONCE over the whole song (`prepare`), and each chunk then takes its slice
    of those stems. Separating chunk by chunk asked the GPU for a fresh allocation per chunk: on a
    ZeroGPU Space each request reserves its full duration from the visitor's small daily quota, so
    a five-minute song ran out of quota after two chunks, the later chunks fell back to the
    model-free leaves under other names, and the job failed. One whole-song call is also faster
    (one model load, no edge effects between chunks)."""
    from stage.separation.cascade.tree import Cascade

    state: dict[str, Any] = {"whole": None, "error": None}

    def prepare(audio: NDArray, sr: int) -> None:
        if separator is None:
            return
        try:
            sep = separator(audio.astype(np.float64), sr)
            state["whole"] = {k: np.asarray(v, dtype=np.float32) for k, v in sep.stems.items()}
            state["model"] = getattr(sep, "model", None)
        except Exception as exc:  # recorded; every chunk then uses the model-free leaves
            state["error"] = f"{type(exc).__name__}: {exc}"

    def provide(audio: NDArray, sr: int, span: tuple[int, int] | None = None
                ) -> tuple[dict, dict, dict]:
        casc = Cascade(preset, engines=engines or {}, cache_dir=cache_dir)
        fallback = None
        if state["whole"] is not None and span is not None:
            fallback = {k: v[:, span[0] : span[1]] for k, v in state["whole"].items()}
        elif state["error"] is not None:
            leaves, ret, info = lite_leaves(audio, sr)
            info["separator_error"] = state["error"]
            return leaves, ret, info
        elif separator is not None:
            try:
                sep = separator(audio.astype(np.float64), sr)
                fallback = {k: np.asarray(v, dtype=np.float32) for k, v in sep.stems.items()}
            except Exception as exc:  # no separator: the model-free decomposition
                leaves, ret, info = lite_leaves(audio, sr)
                info["separator_error"] = f"{type(exc).__name__}: {exc}"
                return leaves, ret, info
        res = casc.run(audio, sr, fallback_stems=fallback)
        info = {"provider": f"cascade:{preset}", "report": res.report, "roles": res.roles,
                "quality": {k: q.as_dict() for k, q in res.quality.items()},
                "separator": state.get("model")}
        return res.leaves, res.reverb, info

    provide.prepare = prepare  # type: ignore[attr-defined]
    return provide


def route_leaves(leaves: dict[str, NDArray], plan: dict[str, Any]) -> dict[str, NDArray]:
    """Map a chunk's leaves onto the plan's objects: a name the plan does not know is added to
    the object of the same role (a cluster that appears only in a later chunk is not lost)."""
    known = {o["leaf"]: o for o in plan["stems"] if o["kind"] == "object"}
    out: dict[str, NDArray] = {}
    for name, x in leaves.items():
        target = name
        if name not in known:
            role = infer_role(name)
            same = [o["leaf"] for o in known.values() if o["role"] == role]
            # Never drop audio: a leaf with no object of its role goes to the plan's largest
            # unprotected object (or any object), so an instrument is never silently missing.
            others = [o["leaf"] for o in known.values() if not o.get("protected")] or list(known)
            if not same and not others:
                continue
            target = same[0] if same else others[0]
        out[target] = out[target] + x if target in out else x
    return out


# --- The run --------------------------------------------------------------------------------------


def run_job(job: Job, audio_path: Path, provider: Provider | None = None,
            genre_fn: Callable[[NDArray, int], dict[str, Any]] | None = None) -> None:
    """Run a job to the end, publishing state as it goes; never raises."""
    for _ in iter_job(job, audio_path, provider, genre_fn):
        pass


def iter_job(job: Job, audio_path: Path, provider: Provider | None = None,
             genre_fn: Callable[[NDArray, int], dict[str, Any]] | None = None):
    """The job as a generator that yields after each stage and each chunk.

    A Hugging Face ZeroGPU Space charges a visitor's quota only for GPU calls made inside the
    Gradio event that visitor started, so the Space runs this generator inside its event handler
    (and streams the snapshots it yields), while the HTTP routes serve the segments from disk.
    Elsewhere `run_job` just drains it. Never raises: a failure ends in state `failed`.
    """
    opt = job.options
    t_job = time.perf_counter()
    timings: dict[str, float] = {}
    try:
        job.update(status="running", stage="load")
        yield job
        audio, sr = read_audio(str(audio_path), start_s=opt.start_s, duration_s=opt.seconds)
        audio = to_stereo(audio).astype(np.float32)
        n = audio.shape[1]
        if n == 0:
            raise ValueError("the file contains no audio")
        job.update(duration_s=round(n / sr, 3), sample_rate=int(sr))

        job.update(stage="analyse")
        yield job
        t = time.perf_counter()
        analysis: SongAnalysis = analyse_song(audio, sr)
        genre_info = genre_fn(audio, sr) if genre_fn else {
            "genre": opt.genre or DEFAULT_GENRE, "scores": {}, "source": "user" if opt.genre
            else "default"}
        if opt.genre:
            genre_info = {"genre": opt.genre, "scores": {}, "source": "user"}
        timings["analyse"] = time.perf_counter() - t

        spans = chunk_spans(n, sr, opt.chunk_s, opt.overlap_s, opt.first_s)
        job.update(chunks_total=len(spans), tempo_bpm=round(analysis.tempo_bpm, 2),
                   genre=genre_info["genre"])
        provide = provider or (lambda a, s: lite_leaves(a, s))
        prepare = getattr(provide, "prepare", None)
        if prepare is not None:
            job.update(stage="separate")
            yield job
            t = time.perf_counter()
            prepare(audio, sr)
            timings["separate_whole"] = time.perf_counter() - t
        asm = Assembler(n, int(opt.overlap_s * sr))
        out = np.zeros((2, n), dtype=np.float32)
        plan: dict[str, Any] | None = None
        pad = int(codec.PAD_S * sr)
        provider_infos: list[dict[str, Any]] = []
        beats = list(analysis.beats_s)
        bounds = [s.start_s for s in analysis.sections][1:]
        ctx = int(CONTEXT_S * sr)
        render_s = sep_s = enc_s = 0.0
        released = 0
        for span in spans:
            job.update(stage=f"chunk {span.index + 1} of {len(spans)}")
            yield job
            a0, a1 = max(0, span.start - ctx), min(n, span.end + ctx)
            t = time.perf_counter()
            leaves_c, returns_c, info = (provide(audio[:, a0:a1], sr, span=(a0, a1))
                                         if prepare is not None else provide(audio[:, a0:a1], sr))
            lo, hi = span.start - a0, span.start - a0 + (span.end - span.start)
            leaves = {k: np.asarray(v, dtype=np.float32)[:, lo:hi] for k, v in leaves_c.items()}
            returns = {k: np.asarray(v, dtype=np.float32)[:, lo:hi] for k, v in returns_c.items()}
            sep_s += time.perf_counter() - t
            provider_infos.append({k: v for k, v in info.items() if k != "report"})
            if plan is None:
                roles = {k: info.get("roles", {}).get(k) or infer_role(k) for k in leaves}
                plan = build_plan_v3(analysis, leaves, sr, track_id=job.id, genre=genre_info[
                    "genre"], motion_depth=opt.motion, character=opt.character, space=opt.space,
                    roles=roles, returns=returns, hrtf=opt.head,
                    genre_source=genre_info.get("source", "default"),
                    genre_scores=genre_info.get("scores"))
                plan["analysis_sample_rate"] = int(sr)
                plan["events"] = []
                job.update(plan=plan)
            # Events of this chunk, on the song's clock, added once.
            cfg = roles_config()["events"]
            role_of = {o["leaf"]: o["role"] for o in plan["stems"] if o["kind"] == "object"}
            routed = route_leaves(leaves, plan)
            for ev in detect_events(
                    routed, sr, [b - span.start / sr for b in beats],
                    [b - span.start / sr for b in bounds], analysis.tempo_bpm, role_of,
                    cfg["max_deg_per_s"], cfg["max_range_deg"],
                    opt.motion * float(plan["stage"].get("motion") or 1.0)):
                shifted = {**ev, "t0": ev["t0"] + span.start / sr, "t1": ev["t1"] + span.start / sr,
                           "az": [[t_ + span.start / sr, v] for t_, v in ev["az"]],
                           "el": [[t_ + span.start / sr, v] for t_, v in ev["el"]]}
                role = shifted.pop("role")
                if not any(abs(e["t0"] - shifted["t0"]) < 0.5 and e["type"] == shifted["type"]
                           for e in plan["events"]):
                    plan["events"].append(shifted)
                    for o in plan["stems"]:
                        if o["role"] == role and not o.get("protected"):
                            o["events"].append({k: v for k, v in shifted.items()})
            t = time.perf_counter()
            res = render_v3(audio[:, span.start : span.end], sr, plan, routed, returns=returns,
                            want_objects=False, t0_s=span.start / sr)
            render_s += time.perf_counter() - t
            start, final = asm.push(span, res.binaural)
            out[:, start : start + final.shape[1]] = final
            end = start + final.shape[1]
            # Codec context: the song before the segment (final) and the chunk's own render after.
            pre = min(pad, start)
            post = 0
            tail = np.zeros((2, 0), np.float32)
            if not span.last:
                post = min(pad, span.end - end)
                tail = res.binaural[:, end - span.start : end - span.start + post]
            pcm = np.concatenate([out[:, start - pre : start], final, tail], axis=1)
            t = time.perf_counter()
            enc = codec.encode_segment(pcm, sr, opt.fmt, pre=pre, post=tail.shape[1])
            enc_s += time.perf_counter() - t
            idx = span.index
            name = f"{idx:04d}.{codec.FORMATS[opt.fmt][1]}"
            (job.dir / "seg" / name).write_bytes(enc.data)
            seg = {"index": idx, "file": name, "start_s": round(start / sr, 4),
                   "duration_s": round((end - start) / sr, 4), "pre": enc.pre, "post": enc.post,
                   "samples": enc.samples, "sample_rate": enc.sample_rate, "fmt": opt.fmt,
                   "bytes": len(enc.data), "ready_s": round(time.perf_counter() - t_job, 2)}
            with job.lock:
                job.state["segments"].append(seg)
                job.state["chunks_done"] = idx + 1
                if idx == 0:
                    job.state["time_to_first_sound_s"] = seg["ready_s"]
                job.state["plan"] = json.loads(json.dumps(plan))
            released = end
            yield job
        timings.update(separate=sep_s, render=render_s, encode=enc_s)
        assert released == n, (released, n)

        job.update(stage="guard")
        yield job
        t = time.perf_counter()
        report = guard_windows(audio, out, sr, {"engine": "v3", "preset": opt.preset})
        timings["guard"] = time.perf_counter() - t
        job.update(stage="write")
        yield job
        sf.write(str(job.dir / "spatial.flac"), out.T, sr, subtype="PCM_24")
        (job.dir / "plan.json").write_text(plan_json(plan), encoding="utf-8")
        (job.dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        total = time.perf_counter() - t_job
        run = {"engine": "soundstage-v3", "audio_s": round(n / sr, 2), "wall_s": round(total, 2),
               "rtf": round(total / (n / sr), 3), "timings_s": {k: round(v, 2) for k, v in
                                                                 timings.items()},
               "render_rtf": round(render_s / (n / sr), 3), "chunks": len(spans),
               "time_to_first_sound_s": job.state.get("time_to_first_sound_s"),
               "providers": provider_infos[:1], "format": opt.fmt,
               "guard": {"verdict": report["verdict"], "reasons": report["reasons"]}}
        (job.dir / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
        job.update(status="done", stage="done", done=True, run=run, timings=run["timings_s"],
                   guard=run["guard"], files={"spatial": "spatial.flac", "plan": "plan.json",
                                              "report": "report.json", "run": "run.json"})
        yield job
    except Exception as exc:
        job.update(status="failed", stage="failed", done=True,
                   error=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc(limit=3))
        yield job
