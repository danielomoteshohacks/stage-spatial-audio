"""The v3 job routes: upload a song, watch it render, fetch its segments while it does.

    POST /v3/jobs                     multipart: `file`, `options` (JSON)  ->  {"id": ...}
    GET  /v3/jobs/{id}                state: stage, chunks, segments ready, plan, guard
    GET  /v3/jobs/{id}/seg/{name}     one encoded segment (Opus or AAC)
    GET  /v3/jobs/{id}/file/{name}    spatial.flac, plan.json, report.json, run.json
    GET  /v3/health                   version, formats, whether neural levels are on

Jobs run one at a time on a worker thread (a render holds whole-signal arrays and a Space has one
GPU); a queue deeper than `MAX_QUEUE` answers 429. Finished jobs and their files are deleted
after the time-to-live. Nothing is kept permanently and nothing is logged about the audio.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from stage import __version__
from stage.service import ValidationError, validate_upload
from stage.stream import codec
from stage.stream.job import Job, JobOptions, Provider, iter_job, new_job

MAX_QUEUE = 4
TTL_S = 45 * 60.0
ALLOWED_FILES = {"spatial.flac": "audio/flac", "plan.json": "application/json",
                 "report.json": "application/json", "run.json": "application/json"}
OPTION_KEYS = {"preset", "genre", "motion", "character", "head", "space", "fmt", "start_s",
               "seconds", "stems", "chunk_s", "first_s", "overlap_s"}


class JobStore:
    def __init__(self, root: Path | None = None, ttl_s: float = TTL_S) -> None:
        self.root = root or Path(tempfile.gettempdir()) / "soundstage-runs"
        self.ttl_s = ttl_s
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="soundstage-job")
        self.pending = 0

    def sweep(self) -> None:
        now = time.time()
        with self.lock:
            old = [j for j in self.jobs.values() if now - j.created > self.ttl_s and
                   j.state.get("done")]
            for j in old:
                self.jobs.pop(j.id, None)
                shutil.rmtree(j.dir, ignore_errors=True)

    def get(self, jid: str) -> Job:
        with self.lock:
            job = self.jobs.get(jid)
        if job is None:
            raise HTTPException(404, "unknown or expired job")
        return job


def parse_options(text: str | None) -> JobOptions:
    raw: dict[str, Any] = json.loads(text) if text else {}
    bad = set(raw) - OPTION_KEYS
    if bad:
        raise ValueError(f"unknown options: {sorted(bad)}")
    return JobOptions(**raw)


def create_router(store: JobStore | None = None,
                  provider_factory: Callable[[str], Provider] | None = None,
                  background: bool = True) -> tuple[APIRouter, JobStore]:
    """The router, and its store. `background=False` leaves running to the caller (the Space
    runs `iter_job` inside a Gradio event for ZeroGPU quota; see space/app.py)."""
    store = store or JobStore()
    router = APIRouter(prefix="/v3")

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"version": __version__, "engine": "soundstage-v3",
                "formats": codec.available_formats(), "queue": store.pending,
                "neural": os.environ.get("SOUNDSTAGE_NEURAL") == "1"}

    @router.get("/bench")
    def bench(seconds: float = 10.0) -> dict[str, Any]:
        """Real-time factor of the renderer on this machine (the Space's own hardware), cold
        then warm, with and without per-object stems: the numbers of decision 0027's table."""
        import numpy as np

        from stage.groundtruth import make_object_song
        from stage.scene.analysis import analyse_song
        from stage.scene3.plan import build_plan_v3
        from stage.scene3.render import render_v3

        seconds = float(np.clip(seconds, 4.0, 30.0))
        song = make_object_song(seed=0)
        sr = song.sample_rate
        a, b = int(26 * sr), int((26 + seconds) * sr)
        mix = song.mix[:, a:b]
        leaves = {k: v[:, a:b] for k, v in song.stereo.items()}
        plan = build_plan_v3(analyse_song(mix, sr), leaves, sr, track_id="bench", genre="pop")
        rows = []
        for stems in (True, False):
            for label in ("cold", "warm"):
                t0 = time.perf_counter()
                res = render_v3(mix, sr, plan, leaves, want_objects=stems)
                dt = time.perf_counter() - t0
                rows.append({"stems": stems, "run": label, "seconds": round(dt, 2),
                             "rtf": round(dt / seconds, 3), "stages": res.info["stage_s"]})
        return {"audio_s": seconds, "cores": os.cpu_count(), "rows": rows}

    @router.post("/jobs")
    async def create(file: Annotated[UploadFile, File()],
                     options: Annotated[str, Form()] = "") -> JSONResponse:
        store.sweep()
        try:
            opts = parse_options(options)
            opts.validate()
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, f"The settings were not understood: {exc}") from exc
        if store.pending >= MAX_QUEUE:
            raise HTTPException(429, "The server is busy; try again in a minute.")
        job = new_job(store.root, opts)
        suffix = Path(file.filename or "upload").suffix.lower() or ".bin"
        src = job.dir / f"upload{suffix}"
        with open(src, "wb") as fh:
            while chunk := await file.read(1 << 20):
                fh.write(chunk)
        try:
            readable, duration, notes = validate_upload(src, job.dir)
        except ValidationError as exc:
            shutil.rmtree(job.dir, ignore_errors=True)
            raise HTTPException(400, str(exc)) from exc
        job.update(notes=notes, source_duration_s=round(duration, 2))
        with store.lock:
            store.jobs[job.id] = job
        if background:
            provider = provider_factory(opts.preset) if provider_factory else None
            store.pending += 1

            def work() -> None:
                try:
                    for _ in iter_job(job, readable, provider):
                        pass
                finally:
                    store.pending -= 1

            store.pool.submit(work)
        return JSONResponse({"id": job.id})

    @router.get("/jobs/{jid}")
    def state(jid: str) -> JSONResponse:
        return JSONResponse(store.get(jid).snapshot(), headers={"Cache-Control": "no-store"})

    @router.get("/jobs/{jid}/seg/{name}")
    def segment(jid: str, name: str) -> FileResponse:
        job = store.get(jid)
        if "/" in name or ".." in name or not name[:4].isdigit():
            raise HTTPException(404, "no such segment")
        path = job.dir / "seg" / name
        if not path.is_file():
            raise HTTPException(404, "that segment is not ready")
        ext = path.suffix[1:]
        media = {"opus": "audio/ogg", "m4a": "audio/mp4", "flac": "audio/flac"}.get(ext)
        return FileResponse(path, media_type=media,
                            headers={"Cache-Control": "private, max-age=600"})

    @router.get("/jobs/{jid}/file/{name}")
    def file_(jid: str, name: str) -> FileResponse:
        job = store.get(jid)
        if name not in ALLOWED_FILES or not (job.dir / name).is_file():
            raise HTTPException(404, "that file is not ready")
        return FileResponse(job.dir / name, media_type=ALLOWED_FILES[name],
                            filename=name if name.endswith(".flac") else None)

    return router, store
