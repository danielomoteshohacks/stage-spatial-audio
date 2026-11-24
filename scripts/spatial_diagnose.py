"""Diagnose a spatial render from its plan and per-object renders.

    python scripts/spatial_diagnose.py RUN_DIR [--json out.json]

RUN_DIR is a pipeline output folder holding plan.json, spatial.flac and objects/*.flac (the v2
and v3 pipeline write them; the web app's "Download" gives the same files). Prints the
direction-energy map by sector, the direct-to-reverberant ratio per object, the late-energy share,
the interaural cross-correlation and the object spread (stage.metrics.spatial, decision 0022).

Nothing here is a perceptual result. It says where the renderer put the sound and how much of it
is direct, which is what "spatial audio, not reverb" is about.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stage.metrics.spatial import diagnose  # noqa: E402


def load_run(folder: Path) -> tuple[dict, dict[str, np.ndarray], np.ndarray | None, int]:
    plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
    objects: dict[str, np.ndarray] = {}
    sr = 0
    for p in sorted((folder / "objects").glob("*.flac")):
        x, sr = sf.read(str(p), dtype="float64", always_2d=True)
        objects[p.stem] = x.T
    render = None
    for name in ("spatial.flac", "spatial.wav"):
        if (folder / name).is_file():
            x, sr = sf.read(str(folder / name), dtype="float64", always_2d=True)
            render = x.T
            break
    if not objects:
        raise SystemExit(f"{folder}/objects has no stems: nothing to diagnose")
    plan["analysis_sample_rate"] = sr
    return plan, objects, render, sr


def table(report: dict) -> str:
    s = report["sectors"]
    lines = [
        f"engine {report['engine']}, space {report['space']}",
        "direct energy by direction: "
        + ", ".join(f"{k} {100 * s[k]:.1f}%" for k in ("front", "side", "rear", "height")),
        f"outside the front +/-30 deg (azimuth): {100 * s['outside_front_az']:.1f}%"
        f", mean elevation {s['mean_elevation_deg']:.1f} deg",
        f"independent directions with >= 5% of the direct energy: {report['object_spread']}",
        f"direct {100 * report['direct_energy_share']:.1f}% of the energy, "
        f"late (over 80 ms) {100 * report['late_energy_share']:.1f}%, "
        f"room (early + late) {100 * report['room_energy_share']:.1f}%",
        f"median object DRR {report['drr_db_median']:.1f} dB"
        + (f", IACC {report['iacc']:.3f}" if "iacc" in report else ""),
        "", "| object | share of direct | DRR (dB) |", "|---|---|---|",
    ]
    for k, v in report["per_object"].items():
        lines.append(f"| {k} | {100 * v['energy_share_direct']:.1f}% | {v['drr_db']:.1f} |")
    return "\n".join(lines)


def bench_v2(songs: int, seconds: float) -> dict:
    """Render the v2 benchmark songs and test each suspected cause of "stereo pushed back" by
    switching it off and reading the same measurements. See docs/log.md, v3 Phase 0."""
    from stage.metrics import spatial as sp
    from stage.scene import render as scene_render
    from stage.scene.analysis import analyse_song
    from stage.scene.plan import build_plan
    from stage.scene.render import render_scene
    from stage.testsongs import make_song

    variants = {
        "v2 default (living room)": {},
        "studio": {"space": "studio"},
        "no room send": {"send": 0.0},
        "no bed front share": {"bed_front": 0.0},
        "no ambient bed (all direct)": {"no_bed": True},
    }
    rows: dict[str, list[dict]] = {k: [] for k in variants}
    for seed, tempo in ((0, 112.0), (1, 124.0), (2, 98.0), (3, 106.0), (4, 118.0))[:songs]:
        song = make_song(seed=seed, tempo_bpm=tempo)
        sr = song.sample_rate
        a, b = int(20 * sr), int((20 + seconds) * sr)
        mix = song.mix[:, a:b]
        stems = {k: v[:, a:b] for k, v in song.stems.items()}
        analysis = analyse_song(mix, sr, stems)
        for name, opt in variants.items():
            plan = build_plan(analysis, track_id="d", mode="stems", genre="pop",
                              space=opt.get("space", "living_room"), motion_depth=0.5)
            plan["analysis_sample_rate"] = sr
            if "send" in opt:
                for o in plan["stems"]:
                    o["room_send"] = opt["send"]
            if opt.get("no_bed"):
                for o in plan["stems"]:
                    if o["source"].endswith(".ambient") and not o.get("spread"):
                        o["spread"] = 60.0  # rendered as a direct pair instead of the bed
            old = scene_render.BED_FRONT_SHARE, sp.BED_FRONT_SHARE_V2
            if "bed_front" in opt:
                scene_render.BED_FRONT_SHARE = sp.BED_FRONT_SHARE_V2 = opt["bed_front"]
            try:
                res = render_scene(mix, sr, plan, stems)
            finally:
                scene_render.BED_FRONT_SHARE, sp.BED_FRONT_SHARE_V2 = old
            d = diagnose(plan, res.objects, res.binaural, sr)
            d.pop("map")
            # Only template-direct objects: what share of the rear and height energy is the bed's?
            rows[name].append(d)
            print(seed, name, d["sectors"], d["object_spread"], d["drr_db_median"], flush=True)
    return rows


def bench_table(rows: dict[str, list[dict]]) -> str:
    out = ["| Variant | front | side | rear | height | outside front (az) | spread | median DRR dB"
           " | room share | late share | IACC |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, rs in rows.items():
        def m(f, rs=rs):
            return float(np.mean([f(r) for r in rs]))
        out.append(
            f"| {name} | {100 * m(lambda r: r['sectors']['front']):.1f}% "
            f"| {100 * m(lambda r: r['sectors']['side']):.1f}% "
            f"| {100 * m(lambda r: r['sectors']['rear']):.1f}% "
            f"| {100 * m(lambda r: r['sectors']['height']):.1f}% "
            f"| {100 * m(lambda r: r['sectors']['outside_front_az']):.1f}% "
            f"| {m(lambda r: r['object_spread']):.1f} | {m(lambda r: r['drr_db_median']):.1f} "
            f"| {100 * m(lambda r: r['room_energy_share']):.1f}% "
            f"| {100 * m(lambda r: r['late_energy_share']):.1f}% | {m(lambda r: r['iacc']):.3f} |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--json", help="write the full report here")
    ap.add_argument("--bench-v2", action="store_true",
                    help="render the v2 benchmark songs and test each suspected cause")
    ap.add_argument("--songs", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=30.0)
    args = ap.parse_args()
    if args.bench_v2:
        rows = bench_v2(args.songs, args.seconds)
        print(bench_table(rows))
        if args.json:
            Path(args.json).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return
    if not args.run_dir:
        ap.error("give a RUN_DIR or --bench-v2")
    plan, objects, render, sr = load_run(Path(args.run_dir))
    report = diagnose(plan, objects, render, sr)
    print(table(report))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
