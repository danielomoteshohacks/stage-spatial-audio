"""SoundStage backend: a thin Gradio app over stage.service, for a laptop or a ZeroGPU Space.

Run locally from the repository root:
    python space/app.py                         # http://127.0.0.1:7860
    GRADIO_SERVER_NAME=0.0.0.0 python space/app.py   # reachable from a phone on the same Wi-Fi

One API endpoint, /process, streams one progress update per pipeline stage and then returns the
files. Only the separation call asks for a GPU: on ZeroGPU the free quota is charged per visitor
(a few GPU minutes a day), so rendering, which is CPU work, must not hold the GPU.
"""

from __future__ import annotations

import os
import sys
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
from stage.pipeline import MODES, STAGES  # noqa: E402
from stage.render.profiles import PROFILES  # noqa: E402
from stage.render.sectors import WIDEN_BETA_MAX, WIDEN_BETA_MIN  # noqa: E402
from stage.separation.demucs_sep import Separation, separate  # noqa: E402
from stage.service import (  # noqa: E402
    ALLOWED_EXTENSIONS,
    DEFAULT_TTL_S,
    MAX_EXCERPT_S,
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
    options = ServiceOptions(
        mode=mode or "lite", profile=profile or "max",
        beta=float(beta) if beta is not None else 2.0,
        start=None if start is None or start == "" else float(start),
        seconds=None if seconds is None or seconds == "" else float(seconds),
    )
    yield _progress(stages, done=False, error=None), None, None, None, None
    for event in stream_process_upload(path, options, separator=gpu_separate):
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
                profile = gr.Dropdown(sorted(PROFILES), value="max", label="Profile")
                beta = gr.Slider(WIDEN_BETA_MIN, WIDEN_BETA_MAX, value=2.0, step=0.05,
                                 label="Width (beta)")
                start = gr.Number(value=None, label="Start (s); empty for the default")
                seconds = gr.Number(value=None, label=f"Length (s, at most {MAX_EXCERPT_S:.0f})")
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

if __name__ == "__main__":
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    start_sweeper()
    demo.launch(server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
                allowed_paths=[str(WORK_ROOT)], show_error=True)
