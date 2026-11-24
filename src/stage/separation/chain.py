"""The separator fallback chain: our engine, then the teacher, then nothing (Lite).

Decision 0015. The SoundStage Separator runs first, on the CPU through ONNX Runtime, but only
when its weights are present *and* their model card records a museval evaluation at or above
htdemucs; until then it is skipped with the reason. The teacher (htdemucs through the demucs
package, the only part that may use a GPU) runs next. If both are unavailable the pipeline
renders the whole mix in Lite. Every attempt is recorded, so run.json always says which
separator produced the stems and why the others did not.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

from stage.separation.demucs_sep import (
    STEM_NAMES,
    Separation,
    SeparationUnavailable,
    residual_snr_db,
    separate,
)

Teacher = Callable[[NDArray[np.float64], int], Separation]


def _teacher_default(audio: NDArray, sample_rate: int) -> Separation:
    return separate(audio, sample_rate, model="htdemucs", device="auto")


def try_ssep(audio: NDArray, sample_rate: int, require_baseline: bool = True
             ) -> tuple[Separation | None, str]:
    from stage.separation.ssep.infer import find_weights

    path = find_weights()
    if path is None:
        return None, "SoundStage Separator weights are not published yet"
    try:
        from stage.separation.ssep.infer import OnnxSeparator, read_card
    except ImportError as exc:
        return None, f"onnxruntime is not installed ({exc})"
    card = read_card(path)
    if require_baseline and not card.meets_baseline:
        ev = card.evaluation or {}
        return None, (f"below the htdemucs baseline (average SDR {ev.get('ssep_avg_sdr_db')} "
                      f"against {ev.get('htdemucs_avg_sdr_db')} dB)")
    sep = OnnxSeparator(path)
    stems, info = sep.separate(audio, sample_rate)
    stems = {k: stems[k] for k in STEM_NAMES}
    notes = [f"CPU {info['cpu_seconds']} s ({info['seconds_per_30s']} s per 30 s of audio)"]
    return Separation(stems=stems, sample_rate=int(sample_rate),
                      residual_snr_db=residual_snr_db(audio, stems), model="ssep",
                      device="cpu (onnxruntime)", notes=notes,
                      details={"leakage_db": info["leakage_db"],
                               "raw_residual_snr_db": info["raw_residual_snr_db"],
                               "seconds_per_30s": info["seconds_per_30s"]}), "ok"


def separate_chain(audio: NDArray, sample_rate: int, teacher: Teacher | None = None,
                   require_baseline: bool = True) -> Separation:
    """Run the chain; raise SeparationUnavailable listing every attempt if none worked."""
    attempts: list[dict[str, Any]] = []
    try:
        sep, reason = try_ssep(audio, sample_rate, require_baseline)
    except Exception as exc:  # a broken engine must not stop the teacher from running
        sep, reason = None, f"{type(exc).__name__}: {exc}"
    attempts.append({"name": "ssep", "status": "ok" if sep else "skipped", "reason": reason})
    if sep is None:
        try:
            sep = (teacher or _teacher_default)(audio, sample_rate)
            attempts.append({"name": "teacher", "status": "ok", "reason": sep.model})
        except Exception as exc:
            attempts.append({"name": "teacher", "status": "failed",
                             "reason": f"{type(exc).__name__}: {exc}"})
            raise SeparationUnavailable(
                "; ".join(f"{a['name']}: {a['reason']}" for a in attempts)) from exc
    sep.chain = attempts
    return sep
