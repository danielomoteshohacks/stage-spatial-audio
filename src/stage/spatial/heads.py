"""Which measured head renders the scene (decision 0026).

SADIE II (University of York, Apache-2.0) measured two dummy heads (D1, a Neumann KU100, and D2,
a KEMAR) and human subjects. Non-individual HRTFs cost localisation accuracy and raise front-back
confusion for listeners whose ears differ from the measured head (a KEMAR gave 17 percent
front-back confusion against 8 percent for measured individual HRTFs in a recent VR study,
arXiv 2606.30114), so the listener can choose: by hand, or by the calibration game in the web app
(`select_head`), which picks the head that best matches where they say sounds came from.

Packs are built by the `hrtf-heads` workflow into the release `hrtf-heads-v1` with an index,
`heads.json`, that lists each head's file, size and SHA-256. A head is downloaded on first use and
verified against that checksum; D1 is also the pack of the original release and the offline
fallback (the analytic head) is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from stage.spatial.hrtf import PACK_FILE, _download, cache_dir, find_pack

HEADS_BASE = ("https://github.com/danielomoteshohacks/stage-spatial-audio/releases/download/"
              "hrtf-heads-v1/")
DEFAULT_HEAD = "D1"
#: SHA-256 of the published index (release hrtf-heads-v1); a different index is refused, so a
#: head's checksum can only come from the index that was reviewed.
INDEX_SHA256 = "659987a606fd48051c3a1dec71cc0a79c3b0bd8c4110a485d310158a0460d5a6"
#: Heads the first build published (D2, the KEMAR, and H8 failed to build: their archive layout
#: differs from the others and is still to be looked at).
PUBLISHED = ("D1", "H3", "H4", "H5", "H6", "H7")
#: What the dummy heads are; the human subjects are labelled by the listener short name in their
#: own SOFA files (SADIE II documents H3 to H20 as human subjects).
KNOWN = {"D1": "Neumann KU100 dummy head", "D2": "KEMAR dummy head"}


def head_label(head: str, listener: str = "") -> str:
    return KNOWN.get(head) or f"Human subject {head}" + (f" ({listener})" if listener else "")


def heads_dir() -> Path:
    return cache_dir() / "hrtf"


def pack_path(head: str) -> Path:
    return heads_dir() / (PACK_FILE if head == DEFAULT_HEAD else f"sadie2-{head.lower()}.npz")


def fetch_index(timeout_s: float = 30.0) -> dict[str, Any]:
    req = urllib.request.Request(HEADS_BASE + "heads.json", headers={"User-Agent": "soundstage"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read()
    if hashlib.sha256(raw).hexdigest() != INDEX_SHA256:
        raise ValueError("the heads index does not match its pinned checksum")
    return json.loads(raw)


def ensure_head(head: str, timeout_s: float = 120.0) -> Path:
    """The pack for `head`, downloaded and checked against the published index if needed."""
    head = head.upper()
    if head == DEFAULT_HEAD and find_pack() is not None:
        return find_pack()  # type: ignore[return-value]
    idx = fetch_index()["heads"]
    if head not in idx:
        raise ValueError(f"unknown head {head!r}; published: {sorted(idx)}")
    entry = idx[head]
    return _download(HEADS_BASE + entry["file"], entry["sha256"], pack_path(head), timeout_s)


def available_heads() -> list[str]:
    """Heads whose packs are already on this machine (D1 first)."""
    out = [h for h in ("D1", "D2") if pack_path(h).is_file()]
    out += sorted(p.stem.split("-")[1].upper() for p in heads_dir().glob("sadie2-h*.npz"))
    return out


# --- Choosing a head from the listener's answers -------------------------------------------------


@dataclass
class Trial:
    """One calibration trial: a sound played from a direction, and where the listener tapped."""

    az: float
    el: float
    answer_az: float
    answer_el: float


def angular_error_deg(az1: float, el1: float, az2: float, el2: float) -> float:
    a1, e1, a2, e2 = (np.radians(v) for v in (az1, el1, az2, el2))
    c = np.sin(e1) * np.sin(e2) + np.cos(e1) * np.cos(e2) * np.cos(a1 - a2)
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def is_front_back_confusion(az: float, answer_az: float, tolerance_deg: float = 25.0) -> bool:
    """The answer is the mirror of the true direction about the interaural axis (front for back)
    and not near the true direction itself. The mirror of az is 180 - az."""
    mirror = ((180.0 - az) + 180.0) % 360.0 - 180.0
    d_true = abs((answer_az - az + 180.0) % 360.0 - 180.0)
    d_mirror = abs((answer_az - mirror + 180.0) % 360.0 - 180.0)
    return d_mirror < tolerance_deg and d_true > tolerance_deg and abs(abs(az) - 90.0) > 20.0


def score_trials(trials: list[Trial]) -> dict[str, float]:
    """Mean angular error, and the share of front-back confusions, of one head's trials."""
    if not trials:
        return {"mean_error_deg": float("inf"), "front_back_rate": 1.0, "n": 0}
    errs = [angular_error_deg(t.az, t.el, t.answer_az, t.answer_el) for t in trials]
    fb = [is_front_back_confusion(t.az, t.answer_az) for t in trials]
    return {"mean_error_deg": float(np.mean(errs)), "front_back_rate": float(np.mean(fb)),
            "n": len(trials)}


def select_head(results: dict[str, list[Trial]], fb_weight: float = 60.0) -> tuple[str, dict]:
    """The head whose trials score best: mean angular error plus `fb_weight` degrees for each
    unit of front-back confusion rate (a confusion is a 180 degree mistake, so it is weighted
    above its share of the plain mean; 60 is a design choice, SPECULATIVE). Ties go to the
    default head."""
    scores = {h: score_trials(t) for h, t in results.items()}
    best = min(scores, key=lambda h: (scores[h]["mean_error_deg"]
                                      + fb_weight * scores[h]["front_back_rate"],
                                      h != DEFAULT_HEAD))
    return best, scores
