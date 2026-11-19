"""Fidelity guard: alignment, downmix, low-end, loudness, true peak, mono and artifact checks.

Implemented so far: alignment, loudness (RMS), timbre deviation and low end (`stage.guard.checks`).
Downmix, true peak, mono sum and artifact flags are planned.
"""

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

__all__ = [
    "AlignmentResult",
    "GuardReport",
    "LoudnessResult",
    "LowEndResult",
    "TimbreResult",
    "check_alignment",
    "check_loudness",
    "check_low_end",
    "check_timbre",
    "format_report",
    "guard_report",
    "third_octave_bands",
]
