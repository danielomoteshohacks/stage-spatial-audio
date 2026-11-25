"""Write the catalogue shelves into the web app (web/src/data/catalogue.json).

The web app shows these shelves at once, before the server answers and when it is asleep or
down, so Home and Browse are never empty. The server's /catalog/shelves stays the source of
truth when it answers (it can carry refreshed tracks and pre-render flags); this file is the
committed seed, served as-is. Run after the seed changes; a test fails when they differ.

Usage: python scripts/export_web_catalogue.py
"""

from __future__ import annotations

import json
from pathlib import Path

from stage.catalogue.store import Catalogue, load_seed

OUT = Path(__file__).resolve().parents[1] / "web" / "src" / "data" / "catalogue.json"


def web_catalogue() -> dict:
    seed = load_seed()
    cat = Catalogue(seed=seed)
    return {"shelves": cat.shelves(), "built_utc": seed.get("built_utc"), "source": "seed"}


def main() -> None:
    OUT.write_text(json.dumps(web_catalogue(), ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
