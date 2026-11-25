"""Pre-render the curated catalogue tracks and publish them to the Hugging Face dataset.

    python scripts/render_catalogue.py --out dist/catalogue [--preset cpu] [--per-shelf 5]
                                       [--part 0 --of 4] [--upload]

For each curated track (the first `per-shelf` of every shelf in configs/catalogue/seed.json) it
downloads the audio, runs the same whole-song job the web app runs on demand, and writes under
`renders/<id>/`: the Opus segments, plan.json, report.json, run.json and manifest.json (the job
state, with the track's licence and attribution beside it). `index.json` lists what exists. A
track already rendered is skipped, so the job is resumable and a weekly run only adds.

With --upload (and HF_TOKEN in the environment) the folder is pushed to the dataset repo
danieltesh/soundstage-catalogue. Curated tracks then play spatially at once, with no GPU quota:
the web app finds them through the dataset index. Share-alike: a render of a CC BY-SA track is
published under CC BY-SA, said in its manifest and in the dataset card.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stage.catalogue.fetch import download, suffix_for  # noqa: E402
from stage.catalogue.model import Track  # noqa: E402
from stage.stream.job import JobOptions, new_job, run_job  # noqa: E402

REPO = "danieltesh/soundstage-catalogue"
CARD = """---
license: other
pretty_name: SoundStage catalogue renders
tags: [audio, spatial-audio, music]
---

# SoundStage catalogue renders

Spatial (object-based binaural) renderings of openly licensed music, made by SoundStage
(github.com/danielomoteshohacks/stage-spatial-audio). Each folder under `renders/` holds the
Opus segments of one track and a `manifest.json` with the track's title, creator, source link,
licence and the exact attribution line. **The licence of a render is the licence of its source
track** (CC BY or CC BY-SA, or CC0): a render of a CC BY-SA track is shared under CC BY-SA. The
audio was changed (separated into parts and rendered to binaural); it is not endorsed by the
creators. Only tracks whose licence permits adaptation are included.
"""


def safe(tid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", tid)[:120]


def curated(seed: dict, per_shelf: int) -> list[str]:
    ids: list[str] = []
    for sh in seed["shelves"].values():
        for tid in sh["tracks"][:per_shelf]:
            if tid not in ids:
                ids.append(tid)
    return ids


def render_track(track: Track, out: Path, preset: str, provider=None) -> dict:
    """Render one track into out/renders/<id>/ and return its index entry."""
    dest = out / "renders" / safe(track.id)
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = download(track, Path(tmp) / f"source{suffix_for(track)}")
        job = new_job(Path(tmp), JobOptions(preset=preset))
        run_job(job, src, provider)
        st = job.snapshot()
        if st["status"] != "done":
            raise RuntimeError(st.get("error") or "the job failed")
        for f in (job.dir / "seg").iterdir():
            (dest / f.name).write_bytes(f.read_bytes())
        for name in ("plan.json", "report.json", "run.json"):
            (dest / name).write_bytes((job.dir / name).read_bytes())
    manifest = {k: st[k] for k in ("segments", "duration_s", "sample_rate", "tempo_bpm", "genre",
                                   "plan", "guard", "run") if k in st}
    manifest.update(
        track=track.as_dict(), preset=preset, files_base=f"renders/{safe(track.id)}/",
        licence_note=("Shared under " + track.licence.label + (
            " (share-alike: this render is under the same licence)" if track.licence.share_alike
            else "")), rendered_utc=datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"))
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return {"manifest": f"renders/{safe(track.id)}/manifest.json", "preset": preset,
            "duration_s": manifest["duration_s"], "verdict": manifest["guard"]["verdict"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", default=str(ROOT / "configs" / "catalogue" / "seed.json"))
    ap.add_argument("--out", default="dist/catalogue")
    ap.add_argument("--preset", default="cpu")
    ap.add_argument("--per-shelf", type=int, default=5)
    ap.add_argument("--part", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()
    seed = json.loads(Path(args.seed).read_text(encoding="utf-8"))
    ids = curated(seed, args.per_shelf)[args.part :: args.of]
    if args.limit:
        ids = ids[: args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    provider = None
    if args.preset != "model-free":
        from stage.server.providers import default_provider_factory

        provider = default_provider_factory()(args.preset)
    index_path = out / f"index.part{args.part}.json"
    index = json.loads(index_path.read_text()) if index_path.is_file() else {"tracks": {}}
    for tid in ids:
        if tid in index["tracks"] and (out / index["tracks"][tid]["manifest"]).is_file():
            continue
        try:
            index["tracks"][tid] = render_track(Track.from_dict(seed["tracks"][tid]), out,
                                                args.preset, provider)
            print(f"rendered {tid}", flush=True)
        except Exception as exc:  # one bad track must not stop the rest
            print(f"FAILED {tid}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    if args.upload:
        import os

        from huggingface_hub import HfApi

        token = os.environ.get("HF_TOKEN")
        if not token:
            raise SystemExit("HF_TOKEN is not set: nothing uploaded")
        (out / "README.md").write_text(CARD, encoding="utf-8")
        api = HfApi(token=token)
        api.create_repo(REPO, repo_type="dataset", exist_ok=True)
        api.upload_folder(repo_id=REPO, repo_type="dataset", folder_path=str(out),
                          allow_patterns=["renders/**", "README.md"],
                          commit_message=f"Render part {args.part} of {args.of}")
        print(f"uploaded to {REPO}")


if __name__ == "__main__":
    main()
