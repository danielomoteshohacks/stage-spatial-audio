"""Time one pipeline run on a generated test track and report peak memory, in a fresh process.

Usage:
    python benchmarks/pipeline_run.py [--seconds 10] [--mode lite] [--profile max] [--out-dir DIR]

The test track (tones and noise bursts panned left, centre and right) and the outputs go to a
temporary folder that is deleted afterwards unless --out-dir is given. Peak memory is the
process's maximum resident set size. It includes the interpreter and the imported libraries,
reported separately as peak_rss_mb_before_run, so it is an upper bound on what the run needs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import resource
import sys
import tempfile
import time
from pathlib import Path

import soundfile as sf

from stage.pipeline import run

_spec = importlib.util.spec_from_file_location(
    "make_test_signal", Path(__file__).resolve().parents[1] / "scripts" / "make_test_signal.py"
)
make_test_signal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_test_signal)


def _peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports kilobytes, macOS bytes.
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--mode", default="lite")
    parser.add_argument("--profile", default="max")
    parser.add_argument("--beta", type=float, default=2.0)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(args.out_dir) if args.out_dir else Path(tmp) / "out"
        src = Path(tmp) / "test.wav"
        sf.write(str(src), make_test_signal.make_test_signal(args.seconds).T, 44100,
                 subtype="PCM_24")
        before = _peak_rss_mb()
        t0 = time.perf_counter()
        result = run(src, mode=args.mode, profile=args.profile, beta=args.beta, out_dir=out)
        wall = time.perf_counter() - t0
        sizes = {p.name: p.stat().st_size for p in out.rglob("*.flac")}
        print(json.dumps({
            "seconds_of_audio": args.seconds,
            "mode": result.mode,
            "profile": args.profile,
            "ok": result.ok,
            "wall_s": round(wall, 3),
            "real_time_factor": round(args.seconds / wall, 2),
            "stages_s": {s.name: round(s.duration_s, 3) for s in result.stages},
            "peak_rss_mb_before_run": round(before, 1),
            "peak_rss_mb": round(_peak_rss_mb(), 1),
            "flac_bytes": sizes,
            "python": platform.python_version(),
            "machine": platform.machine(),
        }, indent=2))


if __name__ == "__main__":
    main()
