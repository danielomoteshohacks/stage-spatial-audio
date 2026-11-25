"""The fidelity guard for a whole song (decision 0027).

`build_report` holds whole-signal spectrograms and long FFTs, and costs about a third of real time
on a four-minute song (81 s for 163 s here), which would hold up the end of a streamed job. Songs
longer than `MAX_FULL_S` are therefore checked in `n_windows` windows of `window_s` seconds spread
evenly over the song (the first, the last, and the rest between), each with the complete guard,
plus the two measures that are cheap and global: integrated loudness over the whole song and the
true peak over the whole song. The report that comes back is the worst window's, with the global
measures substituted, the reasons of every window that was not clean, and a `coverage` entry that
says exactly what was checked, so a pass never claims more than was measured.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

from stage.config import threshold_values
from stage.guard.loudness import integrated_loudness, true_peak_dbtp
from stage.guard.report import build_report

MAX_FULL_S = 45.0
ORDER = {"pass": 0, "review": 1, "fail": 2}


def guard_windows(original: NDArray, render: NDArray, sample_rate: int, versions: dict[str, str],
                  n_windows: int = 5, window_s: float = 20.0) -> dict[str, Any]:
    n = original.shape[1]
    if n <= MAX_FULL_S * sample_rate:
        rep = build_report(original, render, sample_rate, versions)
        rep["coverage"] = {"windows": [[0.0, round(n / sample_rate, 2)]],
                           "analysed_s": round(n / sample_rate, 2),
                           "song_s": round(n / sample_rate, 2), "full": True}
        return rep
    w = int(window_s * sample_rate)
    starts = np.linspace(0, n - w, n_windows).astype(int)
    reps = []
    for s in starts:
        r = build_report(original[:, s : s + w], render[:, s : s + w], sample_rate, versions)
        r["_start_s"] = float(s) / sample_rate
        reps.append(r)
    worst = max(reps, key=lambda r: (ORDER[r["verdict"]], abs(r["alignment_ms"])))
    out = {k: v for k, v in worst.items() if k != "_start_s"}
    t = threshold_values()
    lu_o = integrated_loudness(original, sample_rate)
    lu_r = integrated_loudness(render, sample_rate)
    tp = true_peak_dbtp(render, sample_rate)
    fails: list[str] = []
    reviews: list[str] = []
    d = lu_r - lu_o
    if np.isfinite(d):
        if abs(d) > t["loudness_fail_lu"]:
            fails.append(f"Loudness differs by {d:+.1f} LU over the whole song.")
        elif abs(d) > t["loudness_review_lu"]:
            reviews.append(f"Loudness differs by {d:+.1f} LU over the whole song.")
    if tp > t["true_peak_fail_dbtp"]:
        fails.append(f"The true peak is {tp:+.1f} dBTP, which can clip after conversion.")
    out["loudness_lufs"] = {"original": round(float(lu_o), 2), "render": round(float(lu_r), 2)}
    out["true_peak_db"] = round(float(tp), 2)
    reasons: list[str] = []
    for r in reps:
        if r["verdict"] != "pass":
            reasons += [f"At {r['_start_s']:.0f} s: {x}" for x in r["reasons"]]
    out["reasons"] = (fails + reviews + reasons) or [
        "Every measure is inside its threshold in every window checked."]
    verdicts = [r["verdict"] for r in reps] + (["fail"] if fails else ["review"] if reviews
                                               else ["pass"])
    out["verdict"] = max(verdicts, key=lambda v: ORDER[v])
    out["coverage"] = {"windows": [[round(r["_start_s"], 2), round(r["_start_s"] + window_s, 2)]
                                   for r in reps],
                       "analysed_s": round(window_s * len(reps), 2),
                       "song_s": round(n / sample_rate, 2), "full": False}
    return out
