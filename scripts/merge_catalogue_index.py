"""Merge the per-part index files written by render_catalogue.py into one index.json.

    python scripts/merge_catalogue_index.py dist/catalogue [--upload]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

REPO = "danieltesh/soundstage-catalogue"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()
    folder = Path(args.folder)
    merged: dict = {"tracks": {}}
    for p in sorted(folder.rglob("index.part*.json")):
        merged["tracks"].update(json.loads(p.read_text())["tracks"])
    (folder / "index.json").write_text(json.dumps(merged, indent=1), encoding="utf-8")
    print(f"{len(merged['tracks'])} tracks in the index")
    if args.upload:
        from huggingface_hub import HfApi

        HfApi(token=os.environ["HF_TOKEN"]).upload_file(
            path_or_fileobj=str(folder / "index.json"), path_in_repo="index.json", repo_id=REPO,
            repo_type="dataset", commit_message="Update the index")


if __name__ == "__main__":
    main()
