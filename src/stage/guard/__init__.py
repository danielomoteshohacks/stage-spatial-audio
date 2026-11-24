"""Fidelity guard: alignment, downmix, low end, loudness, true peak, mono sum and artifact checks.

`build_report` produces report.json (schemas/report.schema.json) for every render; the individual
checks are importable for scripts and tests. `levels` holds the RMS match and peak safety used
before anything is written.
"""

from stage.guard.artifacts import Flag, detect_all
from stage.guard.checks import (
    AlignmentResult,
    GuardReport,
    LoudnessResult,
    LowEndResult,
    TimbreResult,
    check_alignment,
    check_loudness,
    check_low_end,
    check_timbre,
    format_report,
    guard_report,
    third_octave_bands,
)
from stage.guard.levels import PEAK_CEILING, limit_peak, match_rms, peak_gain, rms
from stage.guard.loudness import integrated_loudness, short_term_loudness, true_peak_dbtp
from stage.guard.report import build_report

__all__ = [
    "PEAK_CEILING",
    "AlignmentResult",
    "Flag",
    "GuardReport",
    "LoudnessResult",
    "LowEndResult",
    "TimbreResult",
    "build_report",
    "check_alignment",
    "check_loudness",
    "check_low_end",
    "check_timbre",
    "detect_all",
    "format_report",
    "guard_report",
    "integrated_loudness",
    "limit_peak",
    "match_rms",
    "peak_gain",
    "rms",
    "short_term_loudness",
    "third_octave_bands",
    "true_peak_dbtp",
]
