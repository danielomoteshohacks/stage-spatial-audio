"""Ground-truth benchmark: object songs with known 3D positions, folded to stereo, re-spatialised.

    python scripts/benchmark_groundtruth.py [--engines v2,v3] [--seconds 30] [--songs 2]
                                            [--separator oracle,dsp] [--out groundtruth.json]

For each generated object song (stage.groundtruth): the truth is every leaf dry through the HRTF
at its true position; the release is the stereo fold; the engine under test sees only the release
(and the separator's stems of it) and renders a binaural scene. Scores:

* separation: plain SDR per leaf, after matching each leaf to the estimate that holds most of it;
* the direction-energy map of the render against the truth's: sector shares and the earth mover's
  distance in degrees (stage.metrics.separation.map_distance_deg);
* per-leaf angular error: the RMS, over the feeds of the objects that carry the leaf's stem, of
  the angle from the leaf's true direction (energy weighted). Spread copies of one leaf around
  its true place count as error, which is what a listener hears as a source in the wrong place;
* per-object direct-to-reverberant ratio, IACC, and the guard verdict.

Separators: `oracle` hands over the true four stems (an upper bound on what any four-stem
separator can give, isolating the renderer); `dsp` hands the true four stems to the model-free
cascade levels of stage.separation.cascade (azimuth split, kit rules and the post-processing
layer); neural levels need the Space's GPU and are scored by running this script there
(docs/research/separation-v3.md).
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stage.groundtruth import ObjectSong, make_object_song  # noqa: E402
from stage.guard.report import build_report  # noqa: E402
from stage.metrics.separation import map_distance_deg, sdr_db  # noqa: E402
from stage.metrics.spatial import (  # noqa: E402
    DirectionMap,
    angular_distance_deg,
    diagnose,
    direction_map,
    feeds_for_object,
    iacc,
    object_spread,
    sector_shares,
)
from stage.scene.analysis import analyse_song  # noqa: E402
from stage.scene.plan import build_plan  # noqa: E402
from stage.scene.render import render_scene  # noqa: E402

SONGS = ((0, 112.0), (1, 124.0), (2, 98.0))


def truth_map(song: ObjectSong, a: int, b: int) -> DirectionMap:
    """The truth's direction map: each leaf at its true position, all of it direct."""
    from scipy.signal import butter, sosfilt

    # Above the bass crossover, like the renderer's maps: below it the record passes untouched.
    sos = butter(2, 120.0, btype="highpass", fs=song.sample_rate, output="sos")
    az, el, d, own = [], [], [], []
    for s in song.specs:
        e = float(np.sum(sosfilt(sos, song.mono[s.name][a:b]) ** 2)) / max(s.dist, 0.5)
        az.append(s.az)
        el.append(s.el)
        d.append(e)
        own.append(s.name)
    z = np.zeros(len(d))
    return DirectionMap(az=np.array(az), el=np.array(el), direct=np.array(d), room=z, late=z,
                        objects=own, owner=own)


def leaf_errors(song: ObjectSong, a: int, b: int, plan: dict, stems: dict[str, np.ndarray]
                ) -> dict[str, float]:
    """RMS angular error (degrees) of where each leaf's stem is rendered, against its truth."""
    from stage.metrics.separation import best_stem_for

    by_stem: dict[str, list[dict]] = {}
    for obj in plan["stems"]:
        by_stem.setdefault(str(obj.get("source", "mix.direct")).split(".")[0], []).append(obj)
    out = {}
    for s in song.specs:
        ref = song.stereo[s.name][:, a:b]
        stem = best_stem_for(ref, stems)
        sq, w_sum = 0.0, 0.0
        for obj in by_stem.get(stem, []):
            for f in feeds_for_object(obj, plan):
                w = f.weight * f.direct
                sq += w * angular_distance_deg(s.az, s.el, f.az, f.el) ** 2
                w_sum += w
        out[s.name] = float(np.sqrt(sq / max(w_sum, 1e-12)))
    return out


def run_engine(engine: str, song: ObjectSong, a: int, b: int, separator: str) -> dict:
    sr = song.sample_rate
    mix = song.mix[:, a:b]
    if separator == "oracle":
        stems = {k: v[:, a:b] for k, v in song.four_stems().items()}
        leaves = {k: v[:, a:b] for k, v in song.stereo.items()}
        mode = "stems"
    else:
        from stage.separation.cascade.dsp import dsp_cascade

        stems = {k: v[:, a:b] for k, v in song.four_stems().items()}
        casc = dsp_cascade(mix, sr, stems)
        leaves = casc.leaves
        mode = "stems"
    t0 = time.perf_counter()
    if engine == "v2":
        analysis = analyse_song(mix, sr, stems)
        plan = build_plan(analysis, track_id="gt", mode=mode, genre="pop", space="living_room",
                          motion_depth=0.5)
        plan["analysis_sample_rate"] = sr
        res = render_scene(mix, sr, plan, stems)
        objects, render = res.objects, res.binaural
    else:
        from stage.scene3.plan import build_plan_v3
        from stage.scene3.render import render_v3

        analysis = analyse_song(mix, sr, stems)
        plan = build_plan_v3(analysis, leaves, sr, track_id="gt", genre="pop", motion_depth=0.5)
        plan["analysis_sample_rate"] = sr
        res = render_v3(mix, sr, plan, leaves)
        objects, render = res.objects, res.binaural
    dt = time.perf_counter() - t0
    dm = direction_map(plan, objects, sr)
    truth = truth_map(song, a, b)
    sec = sector_shares(dm)
    rep = build_report(mix, render, sr, {"engine": engine})
    diag = diagnose(plan, objects, render, sr)
    errs = leaf_errors(song, a, b, plan, stems if engine == "v2" else leaves)
    seps = {}
    for s in song.specs:
        ref = song.stereo[s.name][:, a:b]
        if separator == "oracle":
            seps[s.name] = None  # the true stems were given; there is nothing to score
        else:
            from stage.metrics.separation import best_stem_for

            seps[s.name] = sdr_db(ref, leaves[best_stem_for(ref, leaves)]) \
                if engine == "v3" else sdr_db(ref, stems[best_stem_for(ref, stems)])
    return {
        "engine": engine, "separator": separator, "render_s": round(dt, 2),
        "sectors": {k: round(v, 4) for k, v in sec.items()},
        "object_spread": object_spread(dm),
        "map_distance_deg": round(map_distance_deg(dm, truth), 2),
        "leaf_angular_error_deg": {k: round(v, 1) for k, v in errs.items()},
        "angular_error_rms_deg": round(float(np.sqrt(np.mean(np.square(list(errs.values()))))), 1),
        "drr_db_median": diag["drr_db_median"], "late_energy_share": diag["late_energy_share"],
        "iacc": round(iacc(render, sr), 3),
        "timbre_dev_db": rep["timbre_deviation_db"], "artifact_flags": len(rep["artifact_flags"]),
        "low_end_corr": rep["low_end"]["identity_corr"], "verdict": rep["verdict"],
        "leaf_sdr_db": {k: None if v is None else round(v, 2) for k, v in seps.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--engines", default="v2")
    ap.add_argument("--separator", default="oracle")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--songs", type=int, default=2)
    ap.add_argument("--start", type=float, default=20.0)
    ap.add_argument("--out", default="groundtruth.json")
    args = ap.parse_args()
    rows = []
    for seed, tempo in SONGS[: args.songs]:
        song = make_object_song(seed=seed, tempo_bpm=tempo)
        sr = song.sample_rate
        a, b = int(args.start * sr), int((args.start + args.seconds) * sr)
        truth = truth_map(song, a, b)
        tsec = {k: round(v, 3) for k, v in sector_shares(truth).items()}
        print(f"song {seed}: truth sectors {json.dumps(tsec)}", flush=True)
        for engine in args.engines.split(","):
            for sep in args.separator.split(","):
                row = run_engine(engine, song, a, b, sep)
                row["song"] = seed
                rows.append(row)
                print(json.dumps({k: v for k, v in row.items()
                                  if k not in ("leaf_angular_error_deg", "leaf_sdr_db")}),
                      flush=True)
    Path(args.out).write_text(json.dumps({"machine": platform.processor() or platform.machine(),
                                          "rows": rows}, indent=2))


if __name__ == "__main__":
    main()
