"""The processing service behind the web app: validate an upload, run the pipeline, expire outputs.

Pure Python with no Gradio import, so it is tested on its own and the Gradio app in space/ stays a
thin adapter. Nothing is stored permanently: every run gets its own folder under a work root, and
folders older than the time-to-live are deleted on every call and by `start_sweeper`.
"""

from __future__ import annotations

import math
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import soundfile as sf

from stage import pipeline
from stage.engines import DEFAULT_PROFILE, profile_names
from stage.pipeline import MODES, Separator
from stage.render.sectors import WIDEN_BETA_MAX, WIDEN_BETA_MIN

ALLOWED_EXTENSIONS = (".wav", ".flac", ".mp3", ".ogg", ".m4a")
MAX_TRACK_S = 12 * 60.0
#: An upload larger than this is refused before decoding; 12 minutes of 24-bit 96 kHz stereo WAV
#: is about 415 MB, so this admits every allowed track in a compressed or 16/24-bit 48 kHz form.
MAX_UPLOAD_BYTES = 450 * 1024 * 1024
DEFAULT_SECONDS = 30.0
#: The render keeps whole-signal arrays (about 3 GB for 4 minutes), and a free GPU quota is a few
#: minutes a day, so one request renders at most this much.
MAX_EXCERPT_S = 120.0
MIN_EXCERPT_S = 1.0
DEFAULT_TTL_S = 30 * 60.0
WORK_ROOT = Path(tempfile.gettempdir()) / "soundstage-runs"


class ValidationError(ValueError):
    """The upload or the options were refused. The message is written for the person uploading."""


@dataclass
class ServiceOptions:
    mode: str = "lite"
    profile: str = DEFAULT_PROFILE
    beta: float = 2.0
    start: float | str | None = "auto"  # "auto" or None: the loudest window; else seconds
    seconds: float | str | None = None  # None or "": DEFAULT_SECONDS


@dataclass
class ServiceResult:
    run_dir: Path
    ok: bool
    original: Path | None
    spatial: Path | None
    stems_spatial: dict[str, Path]
    stems: dict[str, Path]
    run_json: Path | None
    run: dict[str, Any]
    report_json: Path | None
    expires_at: float
    notes: list[str] = field(default_factory=list)


def sweep_expired(root: Path = WORK_ROOT, ttl_s: float = DEFAULT_TTL_S,
                  now: float | None = None) -> list[Path]:
    """Delete run folders whose last change is older than `ttl_s`; return what was deleted."""
    if not root.exists():
        return []
    now = time.time() if now is None else now
    removed = []
    for child in root.iterdir():
        try:
            if now - child.stat().st_mtime > ttl_s:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                removed.append(child)
        except FileNotFoundError:  # another sweep got there first
            continue
    return removed


def start_sweeper(root: Path = WORK_ROOT, ttl_s: float = DEFAULT_TTL_S,
                  every_s: float = 60.0) -> threading.Thread:
    """Sweep in a daemon thread, so outputs expire even when nobody uploads anything new."""
    def loop() -> None:
        while True:
            sweep_expired(root, ttl_s)
            time.sleep(every_s)

    thread = threading.Thread(target=loop, name="soundstage-sweeper", daemon=True)
    thread.start()
    return thread


def _decode_to_flac(src: Path, dst: Path) -> None:
    """Decode with ffmpeg when libsndfile cannot (m4a/AAC, some mp3s), losslessly into FLAC."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ValidationError(
            f"This server cannot decode {src.suffix} files (no decoder is installed). "
            "Convert the track to WAV or FLAC and upload it again."
        )
    proc = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(src), "-vn", "-c:a", "flac",
         "-sample_fmt", "s32", str(dst)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    if proc.returncode != 0 or not dst.exists():
        detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "unknown error"
        raise ValidationError(f"The file could not be decoded as audio ({detail}).")


def validate_upload(path: str | Path, work_dir: Path) -> tuple[Path, float, list[str]]:
    """Check type, size and length; return a path soundfile can read, its duration, and notes."""
    src = Path(path)
    ext = src.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"{ext or 'Files without an extension'} is not supported. "
            f"Upload one of: {', '.join(e[1:] for e in ALLOWED_EXTENSIONS)}."
        )
    if not src.is_file():
        raise ValidationError("The upload did not arrive. Try again.")
    size = src.stat().st_size
    if size == 0:
        raise ValidationError("The file is empty.")
    if size > MAX_UPLOAD_BYTES:
        raise ValidationError(f"The file is {size / 2**20:.0f} MB; the limit is "
                              f"{MAX_UPLOAD_BYTES / 2**20:.0f} MB.")
    notes: list[str] = []
    readable = src
    try:
        info = sf.info(str(src))
    except Exception:
        readable = work_dir / "decoded.flac"
        _decode_to_flac(src, readable)
        notes.append(f"decoded {ext} with ffmpeg")
        try:
            info = sf.info(str(readable))
        except Exception as exc:
            raise ValidationError(f"The file could not be read as audio ({exc}).") from exc
    if info.channels not in (1, 2):
        raise ValidationError(f"The track has {info.channels} channels; upload mono or stereo.")
    duration = info.frames / info.samplerate if info.samplerate else 0.0
    if duration <= 0:
        raise ValidationError("The file contains no audio.")
    if duration > MAX_TRACK_S:
        raise ValidationError(f"The track is {duration / 60:.1f} minutes long; the limit is "
                              f"{MAX_TRACK_S / 60:.0f} minutes.")
    return readable, duration, notes


def parse_start(value: Any) -> float | str:
    """Read the start field: empty or "auto" means the loudest window; otherwise seconds >= 0.

    The web app and the Gradio form both send text, and older clients send numbers, so both are
    accepted. Anything else is refused with a message for the person filling the form.
    """
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "auto")):
        return "auto"
    try:
        start = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"The start time {value!r} is not a number of seconds. Leave it "
                              "empty to start at the loudest part.") from None
    if not math.isfinite(start) or start < 0:
        raise ValidationError("The start time must be zero or more seconds.")
    return start


def parse_seconds(value: Any) -> float:
    """Read the length field: empty means DEFAULT_SECONDS; otherwise MIN..MAX_EXCERPT_S.

    A 0-second length is never accepted: it has nothing to render, and a form that shows 0 for an
    empty field must not be able to send it as if it were a choice.
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return DEFAULT_SECONDS
    try:
        length = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"The length {value!r} is not a number of seconds.") from None
    if not math.isfinite(length) or not MIN_EXCERPT_S <= length <= MAX_EXCERPT_S:
        raise ValidationError(f"The excerpt length must be between {MIN_EXCERPT_S:.0f} and "
                              f"{MAX_EXCERPT_S:.0f} seconds; leave it empty for "
                              f"{DEFAULT_SECONDS:.0f}.")
    return length


def resolve_excerpt(duration: float, start: Any,
                    seconds: Any) -> tuple[float | str, float, list[str]]:
    """Choose the excerpt: (start, length, notes). The start may stay "auto".

    "auto" (the default) is resolved by the pipeline to the loudest window of the requested
    length (stage.analysis.excerpt), so the run report records the chosen start and its loudness.
    """
    notes: list[str] = []
    length = parse_seconds(seconds)
    begin = parse_start(start)
    if length > duration:
        notes.append(f"the track is only {duration:.1f} s long, so all of it is used")
        length = duration
    if begin == "auto":
        return "auto", length, notes
    if begin >= duration:
        raise ValidationError(f"The start time ({begin:.1f} s) is past the end of the track "
                              f"({duration:.1f} s).")
    if begin + length > duration:
        length = duration - begin
        notes.append(f"the excerpt is shortened to {length:.1f} s at the end of the track")
    return begin, length, notes


def validate_options(options: ServiceOptions) -> None:
    if options.mode not in MODES:
        raise ValidationError(f"Mode must be one of: {', '.join(MODES)}.")
    if options.profile not in profile_names():
        raise ValidationError(f"Unknown profile {options.profile!r}. Known: "
                              f"{', '.join(profile_names())}.")
    if not WIDEN_BETA_MIN <= float(options.beta) <= WIDEN_BETA_MAX:
        raise ValidationError(f"Width (beta) must be between {WIDEN_BETA_MIN} and "
                              f"{WIDEN_BETA_MAX}.")


def process_upload(
    path: str | Path,
    options: ServiceOptions | None = None,
    *,
    separator: Separator | None = None,
    on_stage: pipeline.StageCallback | None = None,
    root: Path = WORK_ROOT,
    ttl_s: float = DEFAULT_TTL_S,
) -> ServiceResult:
    """Validate an upload and run the pipeline on it in a fresh folder that expires after `ttl_s`.

    Raises ValidationError for anything the person uploading can fix. Pipeline stage failures do
    not raise: they come back in `run` with ok False or a fallback.
    """
    options = options or ServiceOptions()
    validate_options(options)
    root.mkdir(parents=True, exist_ok=True)
    sweep_expired(root, ttl_s)
    run_dir = root / uuid.uuid4().hex
    run_dir.mkdir()
    try:
        readable, duration, notes = validate_upload(path, run_dir)
        start, seconds, excerpt_notes = resolve_excerpt(duration, options.start, options.seconds)
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    notes += excerpt_notes
    out = run_dir / "out"
    result = pipeline.run(
        readable, mode=options.mode, profile=options.profile, beta=float(options.beta),
        start=start, seconds=seconds, out_dir=out, separator=separator, on_stage=on_stage,
    )
    if readable != Path(path):
        readable.unlink(missing_ok=True)  # the decoded copy is not an output

    def existing(rel: str | None) -> Path | None:
        return None if rel is None or not (out / rel).exists() else out / rel

    outs = result.report.get("outputs", {})
    return ServiceResult(
        run_dir=run_dir,
        ok=result.ok,
        original=existing(outs.get("original")),
        spatial=existing(outs.get("spatial")),
        stems_spatial={k: out / v for k, v in outs.get("stems_spatial", {}).items()},
        stems={k: out / v for k, v in outs.get("stems", {}).items()},
        run_json=existing(outs.get("run")),
        run=result.report,
        report_json=existing(outs.get("report")),
        expires_at=time.time() + ttl_s,
        notes=notes,
    )


def stream_process_upload(
    path: str | Path,
    options: ServiceOptions | None = None,
    **kwargs: Any,
) -> Iterator[dict[str, Any]]:
    """Run `process_upload` in a worker thread and yield each stage event as it happens.

    Yields {"type": "stage", ...} events, then exactly one {"type": "result", "result": ...} or
    {"type": "error", "message": ...}. Lets a streaming endpoint show progress without the
    pipeline knowing anything about the web.
    """
    events: queue.Queue[dict[str, Any]] = queue.Queue()

    def work() -> None:
        try:
            res = process_upload(path, options, on_stage=lambda e: events.put(
                {"type": "stage", **e}), **kwargs)
            events.put({"type": "result", "result": res})
        except ValidationError as exc:
            events.put({"type": "error", "message": str(exc)})
        except Exception as exc:  # unexpected: report it rather than leave the client waiting
            events.put({"type": "error", "message": f"Processing failed: {type(exc).__name__}: "
                                                    f"{exc}"})

    thread = threading.Thread(target=work, name="soundstage-run", daemon=True)
    thread.start()
    while True:
        event = events.get()
        yield event
        if event["type"] in ("result", "error"):
            break
    thread.join()
