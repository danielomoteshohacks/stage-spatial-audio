"""Render a clip with the Lite renderer and write an A/B pair you can listen to on headphones.

Usage:
    python scripts/render_clip.py path/to/clip.wav [--start 30] [--seconds 15] [--beta 2.0]
                                  [--out-dir renders] [--guard]

Writes input_stereo.wav (the original excerpt) and input_stage.wav (rendered), both 24-bit.
The rendered file is loudness-matched to the input's RMS first, because a louder version tends to
win an A/B test on loudness alone. Use only audio you own or may use, and keep the output out of
Git (*.wav is ignored).

--guard prints the fidelity-guard table (stage.guard) after rendering. It compares the file that is
written, after loudness matching and the peak safety, because that is what is listened to.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import soundfile as sf

# PEAK_CEILING stays importable from here: callers and tests read it as render_clip.PEAK_CEILING.
from stage.guard import format_report, guard_report
from stage.guard.levels import PEAK_CEILING, limit_peak, match_rms, rms  # noqa: F401
from stage.io import read_audio, to_stereo
from stage.render import render_stereo


def _db(ratio: float) -> float:
    return 20.0 * np.log10(ratio) if ratio > 0 else float("-inf")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("path")
    parser.add_argument("--start", type=float, default=0.0, help="start time in seconds")
    parser.add_argument("--seconds", type=float, default=15.0, help="length to render")
    parser.add_argument("--beta", type=float, default=2.0, help="widen strength, 1.0 to 2.4")
    parser.add_argument("--out-dir", default="renders", help="folder for the two WAV files")
    parser.add_argument("--guard", action="store_true", help="print the fidelity-guard report")
    args = parser.parse_args()

    audio, sample_rate = read_audio(args.path, start_s=args.start, duration_s=args.seconds)
    audio = to_stereo(audio)
    if audio.shape[1] == 0:
        raise SystemExit("Nothing to render: the requested range is empty.")
    if rms(audio) == 0.0:
        raise SystemExit("The clip is silent.")

    t0 = time.perf_counter()
    rendered = render_stereo(audio, sample_rate, beta=args.beta)
    elapsed = time.perf_counter() - t0

    rms_in, rms_raw = rms(audio), rms(rendered)
    matched, gain = limit_peak(match_rms(rendered, rms_in))
    rms_out = rms(matched)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_dir / "input_stereo.wav"), audio.T, sample_rate, subtype="PCM_24")
    sf.write(str(out_dir / "input_stage.wav"), matched.T, sample_rate, subtype="PCM_24")

    print(f"duration: {audio.shape[1] / sample_rate:.1f} s at {sample_rate} Hz, beta {args.beta}")
    print(f"RMS input:            {rms_in:.5f} ({_db(rms_in):+.1f} dBFS)")
    print(f"RMS render, raw:      {rms_raw:.5f} ({_db(rms_raw):+.1f} dBFS)")
    print(f"RMS render, matched:  {rms_out:.5f} ({_db(rms_out):+.1f} dBFS)")
    if gain < 1.0:
        print(f"peak safety lowered the render by {-_db(gain):.2f} dB, so it is now quieter than "
              f"the input by that much; trim the clip or lower beta for a strict match")
    print(f"render time: {elapsed:.2f} s ({audio.shape[1] / sample_rate / elapsed:.1f}x real time)")
    print(f"wrote {out_dir / 'input_stereo.wav'} and {out_dir / 'input_stage.wav'}")
    if args.guard:
        print()
        print(format_report(guard_report(audio, matched, sample_rate)))


if __name__ == "__main__":
    main()
