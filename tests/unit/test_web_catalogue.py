"""The web app's committed catalogue must match the seed the server serves."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_web_catalogue_matches_the_seed():
    path = ROOT / "scripts" / "export_web_catalogue.py"
    spec = importlib.util.spec_from_file_location("exp", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    committed = json.loads((ROOT / "web" / "public" / "catalogue.json").read_text("utf-8"))
    assert committed == mod.web_catalogue(), "run python scripts/export_web_catalogue.py"
    assert sum(len(s["tracks"]) for s in committed["shelves"]) >= 60
