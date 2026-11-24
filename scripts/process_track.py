"""Process one track into an A/B listening set with the SoundStage pipeline.

Usage:
    python scripts/process_track.py path/to/track.flac [--mode lite|stems] [--profile max]
                                    [--beta 2.0] [--start 30] [--seconds 30] [--out-dir runs/x]

Writes original.flac, spatial.flac (RMS-matched to the original, then peak-limited), run.json and,
in stems mode, stems/<name>.flac and stems_spatial/<name>.flac. Stems mode needs the separation
extra (torch and demucs); without it the run falls back to Lite and says so. Use only audio you
own or may use, and keep the output out of Git (*.flac is ignored).
"""

from __future__ import annotations

import argparse
import sys

from stage.pipeline import MODES, run
from stage.render.profiles import PROFILES


def _summary(result) -> str:
    lines = [f"{'stage':<10}{'status':<9}{'time':>9}  note"]
    for s in result.stages:
        lines.append(f"{s.name:<10}{s.status:<9}{s.duration_s:>8.2f}s  {s.error or ''}".rstrip())
    rep = result.report
    lines.append("")
    lines.append(f"mode: {result.mode} (asked for {result.requested_mode}), profile "
                 f"{rep['profile']}, beta {rep['beta']}")
    if result.fallback:
        reason = result.fallback['reason']
        lines.append(f"fallback: rendered the whole mix in Lite because {reason}")
    if rep.get("separation"):
        snr = rep["separation"]["residual_snr_db"]
        lines.append(f"separation: {rep['separation']['model']} on {rep['separation']['device']}, "
                     f"residual SNR {'exact' if snr is None else f'{snr:.1f} dB'}")
    if rep.get("levels"):
        lv = rep["levels"]
        lines.append(f"levels: original {lv['original_rms_dbfs']} dBFS RMS, spatial "
                     f"{lv['spatial_rms_dbfs']} dBFS RMS, peak gain {lv['peak_gain_db']} dB")
    lines.append(f"wrote to {result.out_dir}: {', '.join(sorted(rep['outputs']))}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("path")
    parser.add_argument("--mode", choices=MODES, default="lite")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="max")
    parser.add_argument("--beta", type=float, default=2.0, help="widen strength, 1.0 to 2.4")
    parser.add_argument("--start", default="auto",
                        help='excerpt start in seconds, or "auto" (default) for the loudest part')
    parser.add_argument("--seconds", type=float, default=None, help="excerpt length in seconds")
    parser.add_argument("--out-dir", default="runs/latest")
    args = parser.parse_args(argv)
    try:
        result = run(args.path, mode=args.mode, profile=args.profile, beta=args.beta,
                     start=args.start if args.start == "auto" else float(args.start),
                     seconds=args.seconds, out_dir=args.out_dir)
    except ValueError as exc:
        parser.error(str(exc))
    print(_summary(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
