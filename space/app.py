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
from stage.pipeline import MODES, STAGES  # noqa: E402
from stage.render.sectors import WIDEN_BETA_MAX, WIDEN_BETA_MIN  # noqa: E402
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


def process(audio_file, mode, profile, beta, start, seconds):
    """Stream stage progress, then return original, spatial, spatial stems and run.json."""
    stages = {n: {"stage": n, "status": "pending", "duration_s": 0.0, "error": None}
              for n in STAGES}
    if not audio_file:
        yield _progress(stages, done=True, error="No file was uploaded."), None, None, None, None
        return
    path = audio_file if isinstance(audio_file, str) else getattr(audio_file, "name", audio_file)
    # Start and length arrive as text (or numbers from older clients); empty means the default
    # and the service validates both, so a bad value comes back as a message, not a crash.
    options = ServiceOptions(
        mode=mode or "lite", profile=profile or DEFAULT_PROFILE,
        beta=float(beta) if beta is not None else 2.0,
        start=start, seconds=seconds,
    )
    yield _progress(stages, done=False, error=None), None, None, None, None
    for event in stream_process_upload(path, options, separator=chain_separate):
        if event["type"] == "stage":
            stages[event["stage"]] = {k: event[k] for k in ("stage", "status", "duration_s",
                                                             "error")}
            yield _progress(stages, done=False, error=None), None, None, None, None
        elif event["type"] == "error":
            yield _progress(stages, done=True, error=event["message"]), None, None, None, None
        else:
            res = event["result"]
            stems = [str(res.stems_spatial[k]) for k in sorted(res.stems_spatial)] or None
            yield (
                _progress(stages, done=True, error=None if res.ok else "Rendering failed; see "
                          "the stage list for the reason.", run=res.run, notes=res.notes,
                          report=_read_json(res.report_json),
                          expires_in_s=round(res.expires_at - time.time())),
                str(res.original) if res.original else None,
                str(res.spatial) if res.spatial else None,
                stems,
                str(res.run_json) if res.run_json else None,
            )


def build() -> gr.Blocks:
    with gr.Blocks(title="SoundStage backend", delete_cache=(600, int(DEFAULT_TTL_S))) as demo:
        gr.Markdown(
            f"## SoundStage backend {__version__}\n"
            "This is the processing API for the SoundStage listening bench. Tracks are processed "
            "and then deleted; use audio you own or may use."
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
                                 label="Width (beta)")
                # Text boxes, not gr.Number: a Number shows 0 when it is empty, which reads as a
                # choice and would send a 0-second length. Empty here means the default.
                start = gr.Textbox(value="", label="Start (seconds)", placeholder="auto",
                                   info="Empty starts at the loudest part of the track.")
                seconds = gr.Textbox(value="", label="Excerpt length (seconds)",
                                     placeholder=f"{DEFAULT_SECONDS:.0f}",
                                     info=f"Empty for {DEFAULT_SECONDS:.0f} s; "
                                          f"{MIN_EXCERPT_S:.0f} to {MAX_EXCERPT_S:.0f} s.")
                go = gr.Button("Process", variant="primary")
            with gr.Column():
                progress = gr.JSON(label="Progress and run report")
                original = gr.File(label="original.flac")
                spatial = gr.File(label="spatial.flac")
                stems = gr.File(label="Spatial stems", file_count="multiple")
                run_json = gr.File(label="run.json")
        go.click(process, [audio, mode, profile, beta, start, seconds],
                 [progress, original, spatial, stems, run_json], api_name="process",
                 concurrency_limit=1)
    # One job at a time: a render holds whole-signal arrays, and the GPU quota is per visitor.
    demo.queue(default_concurrency_limit=1, max_size=16)
    return demo


demo = build()

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
        weights = fetch_weights()
        print(f"SoundStage Separator weights: {weights or 'not published yet; the teacher runs'}",
              flush=True)

    threading.Thread(target=work, name="soundstage-assets", daemon=True).start()


if __name__ == "__main__":
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    start_sweeper()
    fetch_assets()
    demo.launch(server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
                allowed_paths=[str(WORK_ROOT)], show_error=True)
