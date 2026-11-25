"""SoundStage backend: a thin Gradio app over stage.service, for a laptop or a ZeroGPU Space.

Run locally from the repository root:
    python space/app.py                         # http://127.0.0.1:7860
    GRADIO_SERVER_NAME=0.0.0.0 python space/app.py   # reachable from a phone on the same Wi-Fi

One API endpoint, /process, streams one progress update per pipeline stage and then returns the
files. Only the separation call asks for a GPU: on ZeroGPU the free quota is charged per visitor
(a few GPU minutes a day), so rendering, which is CPU work, must not hold the GPU.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
# The deployed Space bundle has stage/ next to this file; a repository checkout has it in ../src.
for _candidate in (HERE, HERE.parent / "src"):
    if (_candidate / "stage" / "__init__.py").is_file():
        sys.path.insert(0, str(_candidate))
        break

import gradio as gr  # noqa: E402

from stage import __version__  # noqa: E402
from stage.engines import DEFAULT_PROFILE, profile_names  # noqa: E402
from stage.pipeline import DEFAULT_MOTION, MODES, STAGES  # noqa: E402
from stage.render.sectors import WIDEN_BETA_MAX, WIDEN_BETA_MIN  # noqa: E402
from stage.scene.plan import CHARACTERS, templates  # noqa: E402
from stage.separation.chain import separate_chain  # noqa: E402
from stage.separation.demucs_sep import Separation, separate  # noqa: E402
from stage.service import (  # noqa: E402
    ALLOWED_EXTENSIONS,
    DEFAULT_SECONDS,
    DEFAULT_TTL_S,
    MAX_EXCERPT_S,
    MIN_EXCERPT_S,
    WORK_ROOT,
    ServiceOptions,
    start_sweeper,
    stream_process_upload,
    stream_rerender,
)

try:
    import spaces  # present on Hugging Face Spaces; absent on a laptop
except ImportError:
    spaces = None

#: Seconds of GPU time requested per separation. ZeroGPU charges the requested duration against
#: the visitor's daily quota, and htdemucs separates a 2 minute excerpt well inside this.
GPU_DURATION_S = 60


def _separate(audio, sample_rate: int) -> Separation:
    return separate(audio, sample_rate, model="htdemucs", device="auto")


gpu_separate = spaces.GPU(duration=GPU_DURATION_S)(_separate) if spaces is not None else _separate


def chain_separate(audio, sample_rate: int) -> Separation:
    """Our separator on the CPU first; only the teacher fallback asks ZeroGPU for a GPU."""
    return separate_chain(audio, sample_rate, teacher=gpu_separate)


def _read_json(path) -> Any:
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _progress(stages: dict[str, dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"stages": [stages[name] for name in STAGES], **extra}


def _options(mode, profile, beta, genre, motion, plan_text, export_bed, start=None,
             seconds=None, character="balanced") -> ServiceOptions:
    """Form values to service options. Text and numbers are both accepted (older clients send
    numbers); the service validates everything and answers with a message, never a crash."""
    plan = None
    if plan_text not in (None, ""):
        plan = plan_text if isinstance(plan_text, dict) else json.loads(plan_text)
    return ServiceOptions(
        mode=mode or "lite", profile=profile or DEFAULT_PROFILE,
        beta=float(beta) if beta is not None else 2.0, start=start, seconds=seconds,
        genre=None if genre in (None, "", "auto") else str(genre),
        motion=DEFAULT_MOTION if motion in (None, "") else float(motion),
        plan=plan, export_bed=bool(export_bed), character=character or "balanced",
    )


def _respond(events, stages):
    """Turn service events into the five streamed outputs."""
    nothing = (None, None, None, None)
    for event in events:
        if event["type"] == "stage":
            stages[event["stage"]] = {k: event[k] for k in ("stage", "status", "duration_s",
                                                             "error")}
            yield (_progress(stages, done=False, error=None), *nothing)
        elif event["type"] == "error":
            yield (_progress(stages, done=True, error=event["message"]), *nothing)
        else:
            res = event["result"]
            # v2 returns its per-object spatial stems (lead vocal, percussion, pads, low end...),
            # which sum to spatial.flac; v1 returns its four spatial stems.
            parts = res.objects or res.stems_spatial
            stems = [str(parts[k]) for k in sorted(parts)] or None
            files = {k: str(v) for k, v in (("plan", res.plan_json), ("report", res.report_json),
                                            ("bed_7_1_4", res.bed)) if v is not None}
            yield (
                _progress(stages, done=True, error=None if res.ok else "Rendering failed; see "
                          "the stage list for the reason.", run=res.run, notes=res.notes,
                          report=_read_json(res.report_json), plan=_read_json(res.plan_json),
                          track_id=res.track_id, files=files,
                          expires_in_s=round(res.expires_at - time.time())),
                str(res.original) if res.original else None,
                str(res.spatial) if res.spatial else None,
                stems,
                str(res.run_json) if res.run_json else None,
            )


def _fresh_stages() -> dict[str, dict[str, Any]]:
    return {n: {"stage": n, "status": "pending", "duration_s": 0.0, "error": None}
            for n in STAGES}


def process(audio_file, mode, profile, beta, start, seconds, genre="auto",
            motion=DEFAULT_MOTION, plan="", export_bed=False, character="balanced"):
    """Stream stage progress, then return original, spatial, spatial stems and run.json."""
    stages = _fresh_stages()
    if not audio_file:
        yield _progress(stages, done=True, error="No file was uploaded."), None, None, None, None
        return
    path = audio_file if isinstance(audio_file, str) else getattr(audio_file, "name", audio_file)
    try:
        options = _options(mode, profile, beta, genre, motion, plan, export_bed, start, seconds,
                           character)
    except (ValueError, TypeError) as exc:
        yield (_progress(stages, done=True, error=f"The settings were not understood: {exc}"),
               None, None, None, None)
        return
    yield _progress(stages, done=False, error=None), None, None, None, None
    yield from _respond(stream_process_upload(path, options, separator=chain_separate), stages)


def rerender(track_id, mode, profile, beta, genre="auto", motion=DEFAULT_MOTION, plan="",
             export_bed=False, character="balanced"):
    """Render a cached track again with new settings or an edited plan. No upload, no GPU."""
    stages = _fresh_stages()
    try:
        options = _options(mode, profile, beta, genre, motion, plan, export_bed,
                           character=character)
    except (ValueError, TypeError) as exc:
        yield (_progress(stages, done=True, error=f"The settings were not understood: {exc}"),
               None, None, None, None)
        return
    yield _progress(stages, done=False, error=None), None, None, None, None
    yield from _respond(stream_rerender(str(track_id or ""), options, separator=chain_separate),
                        stages)


def _v3_event(audio_file, options_json=""):
    yield from v3_process(audio_file, options_json)


def _v3_catalog_event(track_id, options_json=""):
    yield from v3_catalog(track_id, options_json)


def build() -> gr.Blocks:
    genres = [("auto (tagger)", "auto")] + [(t["label"], name) for name, t in templates().items()]
    with gr.Blocks(title="SoundStage backend", delete_cache=(600, int(DEFAULT_TTL_S))) as demo:
        gr.Markdown(
            f"## SoundStage backend {__version__}\n"
            "This is the processing API for the SoundStage web app. Tracks are processed and "
            "then deleted; use audio you own or may use."
        )
        with gr.Row():
            with gr.Column():
                audio = gr.File(label="Track", file_types=list(ALLOWED_EXTENSIONS),
                                type="filepath")
                mode = gr.Radio(list(MODES), value="lite", label="Mode")
                profile = gr.Dropdown(profile_names(), value=DEFAULT_PROFILE, label="Profile",
                                      info="space:<name> is the v2 engine; max and V0 to V5b "
                                           "are v1, kept for comparison.")
                beta = gr.Slider(WIDEN_BETA_MIN, WIDEN_BETA_MAX, value=2.0, step=0.05,
                                 label="Width (beta, v1 only)")
                # Text boxes, not gr.Number: a Number shows 0 when it is empty, which reads as a
                # choice and would send a 0-second length. Empty here means the default.
                start = gr.Textbox(value="", label="Start (seconds)", placeholder="auto",
                                   info="Empty starts at the loudest part of the track.")
                seconds = gr.Textbox(value="", label="Excerpt length (seconds)",
                                     placeholder=f"{DEFAULT_SECONDS:.0f}",
                                     info=f"Empty for {DEFAULT_SECONDS:.0f} s; "
                                          f"{MIN_EXCERPT_S:.0f} to {MAX_EXCERPT_S:.0f} s.")
                genre = gr.Dropdown(genres, value="auto", label="Genre")
                motion = gr.Slider(0.0, 1.0, value=DEFAULT_MOTION, step=0.05,
                                   label="Motion depth", info="0 is a still scene.")
                plan = gr.Textbox(value="", label="Plan (JSON, optional)", lines=2)
                export_bed = gr.Checkbox(value=False, label="Also write the 7.1.4 bed (WAV)")
                character = gr.Radio(list(CHARACTERS), value="balanced", label="Character",
                                     info="How far the scene opens around you.")
                go = gr.Button("Process", variant="primary")
                track_id = gr.Textbox(value="", label="Track id (for re-render)")
                again = gr.Button("Re-render")
            with gr.Column():
                progress = gr.JSON(label="Progress and run report")
                original = gr.File(label="original.flac")
                spatial = gr.File(label="spatial.flac")
                stems = gr.File(label="Spatial stems", file_count="multiple")
                run_json = gr.File(label="run.json")
        outputs = [progress, original, spatial, stems, run_json]
        go.click(process, [audio, mode, profile, beta, start, seconds, genre, motion, plan,
                           export_bed, character], outputs, api_name="process",
                 concurrency_limit=1)
        again.click(rerender, [track_id, mode, profile, beta, genre, motion, plan, export_bed,
                               character], outputs, api_name="rerender", concurrency_limit=1)
        with gr.Accordion("v3 (whole songs, streamed)", open=False):
            v3_file = gr.File(label="Track", file_types=list(ALLOWED_EXTENSIONS), type="filepath")
            v3_opts = gr.Textbox(value="", label="Options (JSON)")
            v3_out = gr.Textbox(label="Job state (JSON)")
            gr.Button("Start v3 job").click(_v3_event, [v3_file, v3_opts], [v3_out],
                                            api_name="v3_process", concurrency_limit=1)
            v3_track = gr.Textbox(label="Catalogue track id")
            gr.Button("Render a catalogue track").click(
                _v3_catalog_event, [v3_track, v3_opts], [v3_out], api_name="v3_catalog",
                concurrency_limit=1)
    # One job at a time: a render holds whole-signal arrays, and the GPU quota is per visitor.
    demo.queue(default_concurrency_limit=1, max_size=16)
    return demo


demo = build()

# --- v3: streamed whole-song jobs (decision 0027) -------------------------------------------------
# The job runs inside a Gradio event, because ZeroGPU charges a visitor's daily quota only for GPU
# calls made inside the event that visitor started. The event streams state snapshots; the
# segments themselves are fetched by the web app from the HTTP routes below, as they appear.

from stage.server.api import JobStore, create_router, parse_options  # noqa: E402
from stage.server.providers import default_provider_factory  # noqa: E402
from stage.service import ValidationError, validate_upload  # noqa: E402
from stage.stream.job import iter_job, new_job  # noqa: E402

GPU_JOB_S = 120
_gpu = (lambda fn: spaces.GPU(duration=GPU_JOB_S)(fn)) if spaces is not None else None
_router, STORE = create_router(JobStore(WORK_ROOT), background=False)
_provider_for = default_provider_factory(_gpu)


def v3_process(audio_file, options_json=""):
    """Stream the snapshots of one whole-song job; the first carries the job id."""
    if not audio_file:
        yield json.dumps({"done": True, "error": "No file was uploaded."})
        return
    path = audio_file if isinstance(audio_file, str) else getattr(audio_file, "name", audio_file)
    try:
        opts = parse_options(options_json)
        job = new_job(STORE.root, opts)
        readable, duration, notes = validate_upload(path, job.dir)
    except (ValueError, TypeError, ValidationError) as exc:
        yield json.dumps({"done": True, "error": f"The upload or settings were refused: {exc}"})
        return
    job.update(notes=notes, source_duration_s=round(duration, 2))
    with STORE.lock:
        STORE.jobs[job.id] = job
    for j in iter_job(job, readable, _provider_for(opts.preset)):
        yield json.dumps(j.snapshot())


from stage.catalogue.fetch import FetchRefused, download, suffix_for  # noqa: E402
from stage.catalogue.store import Catalogue  # noqa: E402
from stage.server.calibration import create_calibration_router  # noqa: E402
from stage.server.catalog import create_catalog_router  # noqa: E402

CATALOGUE = Catalogue()


def v3_catalog(track_id, options_json=""):
    """Render a catalogue track on demand: the server downloads it, so nothing is uploaded."""
    t = CATALOGUE.track(str(track_id or ""))
    if t is None:
        yield json.dumps({"done": True, "error": "That track is not in the catalogue."})
        return
    try:
        opts = parse_options(options_json)
        job = new_job(STORE.root, opts)
        dest = job.dir / f"source{suffix_for(t)}"
        download(t, dest)
        readable, duration, notes = validate_upload(dest, job.dir)
    except (ValueError, TypeError, ValidationError, FetchRefused) as exc:
        yield json.dumps({"done": True, "error": f"The track could not be prepared: {exc}"})
        return
    job.update(notes=notes, source_duration_s=round(duration, 2), track=t.as_dict())
    with STORE.lock:
        STORE.jobs[job.id] = job
    for j in iter_job(job, readable, _provider_for(opts.preset)):
        yield json.dumps(j.snapshot())


def build_app():
    """The Gradio demo plus the v3 HTTP routes, with CORS so the web app can fetch segments."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    api = FastAPI(title="SoundStage backend")
    api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"],
                       allow_headers=["*"])
    api.include_router(_router)
    api.include_router(create_calibration_router())
    api.include_router(create_catalog_router(CATALOGUE, STORE, background=False))
    return gr.mount_gradio_app(api, demo, path="/", allowed_paths=[str(WORK_ROOT)])

def fetch_assets() -> None:
    """Download the measured HRTF pack once, on Hugging Face's servers, in the background.

    Until it arrives (or if the download fails) renders use the analytic head model, and run.json
    names the head that was used, so a render is never mislabelled.
    """
    from stage.separation.ssep.infer import fetch_weights
    from stage.spatial.hrtf import download_pack

    def work() -> None:
        try:
            print(f"HRTF pack ready: {download_pack()}", flush=True)
        except Exception as exc:  # the analytic fallback keeps the Space working
            print(f"HRTF pack unavailable, using the analytic head: {exc}", flush=True)
        try:
            from stage.scene.genre import _load as load_tagger

            load_tagger()
            print("genre tagger ready", flush=True)
        except Exception as exc:
            print(f"genre tagger unavailable, templates default to pop: {exc}", flush=True)
        try:
            from stage.spatial.heads import PUBLISHED, ensure_head

            for head in PUBLISHED:
                ensure_head(head)
            print("measured heads ready", flush=True)
        except Exception as exc:
            print(f"some measured heads unavailable: {exc}", flush=True)
        weights = fetch_weights()
        print(f"SoundStage Separator weights: {weights or 'not published yet; the teacher runs'}",
              flush=True)

    threading.Thread(target=work, name="soundstage-assets", daemon=True).start()


if __name__ == "__main__":
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    start_sweeper()
    fetch_assets()
    CATALOGUE.refresh_in_background()
    import uvicorn

    uvicorn.run(build_app(), host=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
                port=int(os.getenv("GRADIO_SERVER_PORT", "7860")))
