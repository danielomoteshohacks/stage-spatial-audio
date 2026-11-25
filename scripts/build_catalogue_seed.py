"""Build the catalogue seed: openly licensed tracks, verified, placed on shelves.

    python scripts/build_catalogue_seed.py [--out data/catalogue/seed.json] [--pages 2]
                                           [--allow-nc] [--no-verify]

Runs against the live sources (Openverse, and Jamendo when JAMENDO_CLIENT_ID is set), so it needs
the network; the committed seed is the result of one such run, with its date and counts. Metadata
only: no audio is stored. Every track has its licence, attribution line and links, and a check
that its audio URL answered with audio.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stage.catalogue.build import build_catalogue  # noqa: E402
from stage.catalogue.sources import Jamendo, Openverse  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "data" / "catalogue" / "seed.json"))
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--allow-nc", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()
    cat = build_catalogue(Openverse(), Jamendo(), pages=args.pages, verify=not args.no_verify,
                          allow_nc=args.allow_nc, log=lambda m: print(m, file=sys.stderr))
    cat["built_utc"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cat["counts"] = {"tracks": len(cat["tracks"]),
                     "per_shelf": {k: len(v["tracks"]) for k, v in cat["shelves"].items()},
                     "per_licence": {}, "per_source": {}}
    for t in cat["tracks"].values():
        for key, v in (("per_licence", t["licence"]["label"]), ("per_source", t["source"])):
            cat["counts"][key][v] = cat["counts"][key].get(v, 0) + 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(cat, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(cat["counts"], indent=1))


if __name__ == "__main__":
    main()
