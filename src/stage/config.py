"""Find the data files in configs/ (thresholds, templates, room presets) wherever the code runs.

The Hugging Face Space bundle (space/bundle.sh) copies configs/ to stage/configs/, because the
Space has only the package; a repository checkout has it at the root. The bundled copy is tried
first (it only exists in a bundle), so both runtimes read the same files.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_PACKAGE = Path(__file__).resolve().parent
CANDIDATES = (_PACKAGE / "configs", _PACKAGE.parents[1] / "configs")


def config_dir() -> Path:
    for path in CANDIDATES:
        if path.is_dir():
            return path
    raise FileNotFoundError(
        "configs/ was not found next to the package or in the repository; "
        f"looked in {', '.join(str(p) for p in CANDIDATES)}"
    )


@lru_cache(maxsize=64)
def load_json(relative: str) -> Any:
    """Parse configs/<relative>. Cached: these files are read on every render."""
    return json.loads((config_dir() / relative).read_text(encoding="utf-8"))


def threshold_values(relative: str = "thresholds/guard.json") -> dict[str, float]:
    """The `value` of every {value, why} entry; keys starting with "_" are documentation."""
    raw = load_json(relative)
    return {k: float(v["value"]) for k, v in raw.items() if not k.startswith("_")}
