"""Blind listening test for the spatialisation spike (decision 0007): render, shuffle, rank.

Make a session (renders one clip with every profile, loudness-matched, under shuffled numbers):
    python scripts/make_abx.py render path/to/clip.wav [--start 30] [--seconds 15] [--beta 2.0]
                                      [--profiles V0 V1 V2 V3 V4 V5] [--out-dir abx]

Record one listener's blind ranking (appends to experiments/results.csv):
    python scripts/make_abx.py rank --session abx --listener L01 --order "3 1 6 2 5 4"
                                    --outside 3 --natural 1 [--headphones "model"]
Leave out --order, --outside or --natural to be asked for them.

The key (which number is which profile) is in <session>/key.json. The person running the test may
look at it; listeners must not. Use only audio you own or may use, and keep the WAVs out of Git.
See experiments/ABX.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

# PEAK_CEILING stays importable from here: callers and tests read it as make_abx.PEAK_CEILING.
from stage.guard.levels import PEAK_CEILING, match_rms, peak_gain, rms  # noqa: F401
from stage.io import read_audio, to_stereo
from stage.render import render_stereo

DEFAULT_PROFILES = ("V0", "V1", "V2", "V3", "V4", "V5")
RESULTS_CSV = Path(__file__).resolve().parents[1] / "experiments" / "results.csv"
CSV_FIELDS = (
    "timestamp_utc", "session_id", "clip_sha256", "clip_start_s", "clip_seconds", "beta",
    "listener", "headphones", "ranking_best_to_worst", "most_outside_head", "most_natural",
    "file_order", "notes",
)


def equalise(renders: dict[str, np.ndarray], target_rms: float) -> dict[str, np.ndarray]:
    """Match every render to `target_rms`, then apply one common peak-safety gain to all.

    One shared gain (not one per file) keeps them at equal loudness: a louder version tends to
    win a comparison on loudness alone.
    """
    matched = {k: match_rms(v, target_rms) for k, v in renders.items()}
    gain = peak_gain(max(float(np.max(np.abs(v))) for v in matched.values()))
    return {k: v * gain for k, v in matched.items()}


def shuffle_assignment(names: list[str], rng: np.random.Generator) -> dict[str, str]:
    """Map file numbers "01", "02", ... to profile names in random order."""
    order = rng.permutation(len(names))
    return {f"{i + 1:02d}": names[j] for i, j in enumerate(order)}


def decode(choice: str, key: dict[str, str]) -> str:
    num = f"{int(choice):02d}"
    if num not in key:
        raise ValueError(f"no file number {choice}; valid: {', '.join(sorted(key))}")
    return key[num]


def decode_ranking(order: list[str], key: dict[str, str]) -> list[str]:
    """File numbers best-to-worst to profile names; every file exactly once."""
    nums = [f"{int(o):02d}" for o in order]
    if sorted(nums) != sorted(key):
        raise ValueError(f"rank every file exactly once: {', '.join(sorted(key))}; got {order}")
    return [key[n] for n in nums]


def append_result(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def cmd_render(args: argparse.Namespace) -> None:
    audio, sr = read_audio(args.path, start_s=args.start, duration_s=args.seconds)
    audio = to_stereo(audio)
    if audio.shape[1] == 0 or rms(audio) == 0.0:
        raise SystemExit("The requested range is empty or silent.")
    renders = {}
    for name in args.profiles:
        print(f"rendering {name} ...")
        renders[name] = render_stereo(audio, sr, beta=args.beta, profile=name)
    renders = equalise(renders, rms(audio))

    seed = secrets.randbits(32) if args.seed is None else args.seed
    key = shuffle_assignment(list(args.profiles), np.random.default_rng(seed))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("[0-9][0-9].wav"):
        old.unlink()  # never leave files of an earlier session under the same numbers
    for num, name in key.items():
        sf.write(str(out / f"{num}.wav"), renders[name].T, sr, subtype="PCM_24")
    meta = {
        "session_id": f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{seed:08x}",
        "clip_sha256": hashlib.sha256(Path(args.path).read_bytes()).hexdigest(),
        "clip_start_s": args.start,
        "clip_seconds": round(audio.shape[1] / sr, 3),
        "beta": args.beta,
        "files": key,
    }
    (out / "key.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {len(key)} files to {out}: {', '.join(f'{n}.wav' for n in key)}")
    print("listeners must not open key.json. Then run: python scripts/make_abx.py rank "
          f"--session {out} --listener <id>")


def _ask(value: str | None, prompt: str) -> str:
    return value if value is not None else input(prompt).strip()


def cmd_rank(args: argparse.Namespace) -> None:
    meta = json.loads((Path(args.session) / "key.json").read_text(encoding="utf-8"))
    key = meta["files"]
    nums = " ".join(sorted(key))
    order = _ask(args.order, f"Rank files best to worst ({nums}): ").replace(",", " ").split()
    ranking = decode_ranking(order, key)
    outside = decode(_ask(args.outside, "Which file sounded most outside your head? "), key)
    natural = decode(_ask(args.natural, "Which file sounded most natural? "), key)
    append_result(Path(args.results), {
        "timestamp_utc": f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
        "session_id": meta["session_id"],
        "clip_sha256": meta["clip_sha256"],
        "clip_start_s": str(meta["clip_start_s"]),
        "clip_seconds": str(meta["clip_seconds"]),
        "beta": str(meta["beta"]),
        "listener": args.listener,
        "headphones": args.headphones or "",
        "ranking_best_to_worst": ">".join(ranking),
        "most_outside_head": outside,
        "most_natural": natural,
        "file_order": " ".join(f"{int(o):02d}" for o in order),
        "notes": args.notes or "",
    })
    # The listener's answer is stored; the decoded names are not shown, so the next listener
    # in the room does not learn the key from the screen.
    print(f"recorded for {args.listener} in {args.results}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="render, loudness-match and shuffle one clip")
    r.add_argument("path")
    r.add_argument("--start", type=float, default=0.0)
    r.add_argument("--seconds", type=float, default=15.0)
    r.add_argument("--beta", type=float, default=2.0)
    r.add_argument("--profiles", nargs="+", default=list(DEFAULT_PROFILES))
    r.add_argument("--out-dir", default="abx")
    r.add_argument("--seed", type=int, default=None, help="only for tests; default is random")
    r.set_defaults(func=cmd_render)
    k = sub.add_parser("rank", help="record one listener's blind ranking")
    k.add_argument("--session", default="abx")
    k.add_argument("--listener", required=True, help="an ID, not a full name")
    k.add_argument("--order")
    k.add_argument("--outside")
    k.add_argument("--natural")
    k.add_argument("--headphones")
    k.add_argument("--notes")
    k.add_argument("--results", default=str(RESULTS_CSV))
    k.set_defaults(func=cmd_rank)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
