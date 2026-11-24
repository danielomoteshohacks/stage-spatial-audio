"""Choose the excerpt to render: the most energetic window of the track ("auto" start).

A listening test on the first 30 seconds of a song hears an intro; the part people judge a
spatial mix by is the chorus or the drop, which is nearly always the loudest sustained part. So
the default start is the window of the requested length with the highest K-weighted mean energy
(the ungated BS.1770 loudness of that excerpt), found from 100 ms step energies streamed from the
file, so a long track is never held in memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

from stage.guard.loudness import STEP_S, StreamingStepEnergies, loudest_window

#: Frames read per block while scanning; about 1.5 s at 44.1 kHz.
_SCAN_BLOCK = 65536


@dataclass(frozen=True)
class AutoStart:
    start_s: float
    loudness_lufs: float
    track_s: float


def auto_start(path: str | Path, seconds: float) -> AutoStart:
    """The start of the loudest `seconds`-long window in the file at `path`.

    Starts are on the 100 ms step grid. A track no longer than `seconds` starts at 0.
    """
    info = sf.info(str(path))
    meter = StreamingStepEnergies(info.samplerate, info.channels)
    for block in sf.blocks(str(path), blocksize=_SCAN_BLOCK, dtype="float64", always_2d=True):
        meter.push(block.T)
    track_s = info.frames / info.samplerate if info.samplerate else 0.0
    if track_s <= seconds:
        start, lufs = 0.0, loudest_window(meter.result(), track_s)[1]
    else:
        start, lufs = loudest_window(meter.result(), seconds)
        # The window grid ends a step short of the file; never start past the last full window.
        start = min(start, max(0.0, track_s - seconds))
    return AutoStart(start_s=round(start, 3), loudness_lufs=round(lufs, 2), track_s=track_s)


__all__ = ["STEP_S", "AutoStart", "auto_start"]
