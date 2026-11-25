"""Generate the fixture the web screenshots and mobile profile run against.

    python scripts/make_web_fixture.py [--out web/e2e/fixture]

Runs the real whole-song job (stage.stream.job) on a generated song with the model-free leaves and
writes what the browser needs: the original as WAV, the job's final state with its Opus segments,
a calibration burst, and the committed catalogue seed. The mock server (web/e2e/mock-server.mjs)
replays these, so the screens show a real render, not a drawing of one. No recordings are used.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stage.groundtruth import make_object_song  # noqa: E402
from stage.server.calibration import burst  # noqa: E402
from stage.stream.job import JobOptions, new_job, run_job  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "web" / "e2e" / "fixture"))
    ap.add_argument("--seconds", type=float, default=45.0)
    args = ap.parse_args()
    out = Path(args.out)
    shutil.rmtree(out, ignore_errors=True)
    (out / "seg").mkdir(parents=True)
    song = make_object_song(seed=2, bars=(("intro", 2, 0.3), ("verse", 6, 0.55), ("chorus", 8, 1.0),
                                          ("outro", 2, 0.3)))
    n = int(args.seconds * song.sample_rate)
    mix = song.mix[:, :n]
    sf.write(str(out / "original.wav"), mix.T, song.sample_rate, subtype="PCM_16")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "s.flac"
        sf.write(str(src), mix.T, song.sample_rate, subtype="PCM_24")
        job = new_job(Path(tmp), JobOptions(chunk_s=14.0, first_s=6.0, overlap_s=1.0))
        run_job(job, src)
        state = job.snapshot()
        if state["status"] != "done":
            raise SystemExit(state.get("error"))
        for f in (job.dir / "seg").iterdir():
            shutil.copy(f, out / "seg" / f.name)
        for name in ("spatial.flac", "plan.json", "report.json", "run.json"):
            shutil.copy(job.dir / name, out / name)
    (out / "job.json").write_text(json.dumps(state), encoding="utf-8")
    from stage.catalogue.store import load_seed

    (out / "seed.json").write_text(json.dumps(load_seed()), encoding="utf-8")
    sf.write(str(out / "burst.wav"), burst()[:, None].repeat(2, axis=1), 48000, subtype="PCM_16")
    print(f"fixture in {out}: {len(state['segments'])} segments, guard {state['guard']['verdict']}")


if __name__ == "__main__":
    main()
