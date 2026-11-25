"""Real-time factor of the renderers per stage, v2 against v3, cold and warm.

    python benchmarks/render_times_v3.py [--seconds 30] [--engines v2,v3] [--src PATH]
                                         [--no-objects]

`--src` puts another checkout's `src` first on the path, which is how the "before" column of
decision 0027 was measured (the commit before the optimisations). Cold is the first render in
the process, which builds every position's early-reflection response; warm is the second, with
those cached (a long-lived Space is warm after its first song). Real-time factor is
render seconds per second of audio: below 1 is faster than real time. Stages are the
renderer's own `stage_s`.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--engines", default="v2,v3")
    ap.add_argument("--src", default=str(ROOT / "src"))
    ap.add_argument("--no-objects", action="store_true", help="v3 without per-object stems")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    sys.path.insert(0, args.src)
    from stage.groundtruth import make_object_song
    from stage.scene.analysis import analyse_song

    song = make_object_song(seed=0)
    sr = song.sample_rate
    a, b = int(26 * sr), int((26 + args.seconds) * sr)
    mix = song.mix[:, a:b]
    four = {k: v[:, a:b] for k, v in song.four_stems().items()}
    leaves = {k: v[:, a:b] for k, v in song.stereo.items()}
    analysis = analyse_song(mix, sr, four)
    rows = []
    for engine in args.engines.split(","):
        if engine == "v2":
            from stage.scene.plan import build_plan
            from stage.scene.render import render_scene

            plan2 = build_plan(analysis, track_id="b", mode="stems", genre="pop",
                               space="living_room", motion_depth=0.5)

            def run(plan=plan2):
                return render_scene(mix, sr, plan, four)
        else:
            from stage.scene3.plan import build_plan_v3
            from stage.scene3.render import render_v3

            plan3 = build_plan_v3(analysis, leaves, sr, track_id="b", genre="pop")
            kw = {"want_objects": False} if args.no_objects else {}

            def run(plan=plan3, kw=kw):
                try:
                    return render_v3(mix, sr, plan, leaves, **kw)
                except TypeError:  # an older checkout has no want_objects
                    return render_v3(mix, sr, plan, leaves)
        for label in ("cold", "warm"):
            t0 = time.perf_counter()
            res = run()
            dt = time.perf_counter() - t0
            rows.append({"engine": engine + (" no-stems" if args.no_objects else ""),
                         "run": label, "seconds": round(dt, 2),
                         "rtf": round(dt / args.seconds, 3),
                         "stages": res.info.get("stage_s")})
            print(json.dumps(rows[-1]), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps({"machine": platform.processor() or
                                              platform.machine(), "cores": __import__("os")
                                              .cpu_count(), "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
