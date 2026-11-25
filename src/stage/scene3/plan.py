"""The v3 mix plan: a point source for every leaf, placed by role, genre and song (decision 0024).

`build_plan_v3` is pure and deterministic given the analysis and the leaves; the renderer reads
nothing else, so the web app can edit plan.json and re-render without re-separating.

Placement comes from data: configs/placement/roles.json (the role defaults and their sources) and
the `v3` block of each genre template (configs/templates/*.json), scaled by the listener's
character setting. Positions are never chosen by code: this module only reads, scales and clamps.

Time-varying position (`object_paths`) is the one function shared by the renderer and the
diagnostics, so what is measured is what is rendered:

    position(t) = base + breathing(t) + sum of the object's events at t

* *breathing*: objects marked `breathes` pull towards the front and down in quiet sections and
  open to their full azimuth and elevation in loud ones (verses intimate, choruses and drops the
  full sphere), by the section openness of the genre template, cross-faded over a bar;
* *events*: eased keyframe paths from stage.scene3.events.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import numpy as np
from numpy.typing import NDArray

from stage.config import load_json
from stage.scene.analysis import SongAnalysis
from stage.scene.plan import CHARACTERS, DEFAULT_GENRE, get_template, section_openness
from stage.scene3.events import detect_events, eased_path

PLAN_VERSION = 3
DEFAULT_SPACE = "dry_stage"
RETURN_RING = (("side", 90.0, 0.0), ("rear", 135.0, 0.0), ("height", 45.0, 45.0),
               ("height", 135.0, 45.0))
#: Stage multipliers of the three characters: (azimuth, elevation, returned ambience).
CHARACTER_STAGE = {"intimate": (0.8, 0.7, 0.6), "balanced": (1.0, 1.0, 1.0),
                   "immersive": (1.15, 1.25, 1.3)}
MAX_AZ = 170.0
MAX_EL = 80.0
SILENT_RMS = 1e-4


def roles_config() -> dict[str, Any]:
    return load_json("placement/roles.json")


def infer_role(leaf: str) -> str:
    """The placement role of a leaf from its name, for leaves the cascade did not label."""
    n = leaf.lower()
    table = (("lead", "lead_vocal"), ("backing", "backing_vocal"), ("kick", "kick"),
             ("snare", "snare"), ("drum", "drums"), ("bass", "bass"), ("hat", "cymbals"),
             ("cymbal", "cymbals"),
             ("tom", "toms"), ("guitar", "guitar"), ("piano", "keys"), ("keys", "keys"),
             ("pad", "pad"), ("fx", "fx"), ("vocal", "lead_vocal"))
    for key, role in table:
        if key in n:
            return role
    return "other"


def side_of(leaf: str) -> int:
    """+1 for a leaf named left (SOFA azimuth is positive to the left), -1 right, 0 neither."""
    n = leaf.lower().rstrip("0123456789")  # other_left2 is a second cluster on the left
    return 1 if n.endswith("_left") or n.endswith("_l") else -1 if (
        n.endswith("_right") or n.endswith("_r")) else 0


def _clamp(az: float, el: float) -> tuple[float, float]:
    return float(np.clip(az, -MAX_AZ, MAX_AZ)), float(np.clip(el, -10.0, MAX_EL))


def place(leaf: str, role: str, roles: dict[str, Any], genre_v3: dict[str, Any],
          character: str) -> dict[str, Any]:
    """One object (without events, feeds or ids) for a leaf."""
    r = copy.deepcopy(roles["roles"].get(role, roles["roles"]["other"]))
    az_k, el_k, _ = CHARACTER_STAGE[character]
    width = float(genre_v3.get("stage_width", 1.0)) * az_k
    height = float(genre_v3.get("height", 1.0)) * el_k
    rear = float(genre_v3.get("rear", 1.0))
    side = side_of(leaf)
    az = float(r["az"])
    mode = r["mode"]
    if role == "lead_vocal":
        el = r["el"] * height
        dist = r["dist"] * float(genre_v3.get("lead_dist", 1.0))
        az, el = _clamp(0.0, el)
        return {**r, "mode": "mono", "az": 0.0, "el": el, "spread": 0.0, "dist": round(dist, 2)}
    if mode == "pair" and side != 0:
        mode = "side"
        az = float(roles["single_side"].get(role, az)) * side
    elif mode == "pair" and leaf.lower().rstrip("0123456789").endswith("_centre"):
        mode, az = "mono", 0.0
        r["el"] = max(float(r["el"]), 55.0) if role == "pad" else r["el"]
    if role in ("pad", "fx") and abs(az) > 90.0:
        az = float(np.sign(az) * (90.0 + (abs(az) - 90.0) * rear)) if az else az
    if role in ("fx",) and az:
        az = 180.0
    if not r.get("protected"):
        az *= width
    az, el = _clamp(az, float(r["el"]) * (1.0 if r.get("protected") else height))
    out = {**r, "mode": mode, "az": round(az, 1), "el": round(el, 1),
           "dist": round(float(r["dist"]), 2)}
    out["spread"] = round(2.0 * abs(az), 1) if mode == "pair" else 0.0
    return out


def object_paths(obj: dict[str, Any], plan: dict[str, Any], times: NDArray, openness: NDArray
                 ) -> list[tuple[NDArray, NDArray]]:
    """(azimuth(t), elevation(t)) in degrees for each feed of an object at `times` (seconds).

    `openness` is the plan's openness curve sampled at `times` (0 quiet, 1 full).
    """
    t = np.asarray(times, dtype=np.float64)
    depth = float(plan.get("motion_depth", 1.0))
    scale_az = np.ones_like(t)
    scale_el = np.ones_like(t)
    if obj.get("breathes"):
        # Quiet sections pull a breathing object to 60 percent of its azimuth and elevation.
        k = 1.0 - 0.4 * depth * (1.0 - np.clip(openness, 0.0, 1.0))
        scale_az, scale_el = k, 0.5 + 0.5 * k
    d_az = np.zeros_like(t)
    d_el = np.zeros_like(t)
    for ev in obj.get("events", []):
        d_az += eased_path(ev["az"], t)
        d_el += eased_path(ev["el"], t)
    out = []
    for f in obj["feeds"]:
        az = f["az"] * scale_az
        # An event's azimuth offset is mirrored for the feed on the other side, so a pair sweeps
        # together and keeps its width.
        az = az + (d_az if f["az"] >= 0 else -d_az if obj["mode"] in ("pair", "upmix") else d_az)
        el = f["el"] * scale_el + d_el
        out.append(((az + 180.0) % 360.0 - 180.0, np.clip(el, -10.0, MAX_EL)))
    return out


def build_plan_v3(analysis: SongAnalysis, leaves: dict[str, NDArray], sample_rate: int, *,
                  track_id: str, genre: str | None, motion_depth: float = 0.5,
                  character: str = "balanced", space: str | None = None,
                  roles: dict[str, str] | None = None,
                  returns: dict[str, NDArray] | None = None, crossover_hz: float = 120.0,
                  hrtf: str = "D1", genre_source: str = "default",
                  genre_scores: dict[str, float] | None = None, bass_in_leaves: bool = True
                  ) -> dict[str, Any]:
    if not 0.0 <= motion_depth <= 1.0:
        raise ValueError("motion depth must be between 0 and 1")
    if character not in CHARACTERS:
        raise ValueError(f"character must be one of {sorted(CHARACTERS)}")
    genre = genre or DEFAULT_GENRE
    template = get_template(genre)
    g3 = template.get("v3", {})
    cfg = roles_config()
    roles_of = {k: (roles or {}).get(k) or infer_role(k) for k in leaves}
    tempo = analysis.tempo_bpm if analysis.tempo_bpm > 0 else 120.0
    sections = section_openness(analysis, template)
    ev_cfg = cfg["events"]
    events = detect_events(
        leaves, sample_rate, list(analysis.beats_s), [s["start_s"] for s in sections][1:],
        tempo, roles_of, max_speed=ev_cfg["max_deg_per_s"], max_range=ev_cfg["max_range_deg"],
        depth=motion_depth * float(g3.get("motion", 1.0)))
    objects: list[dict[str, Any]] = []
    for name, x in leaves.items():
        if float(np.sqrt(np.mean(np.asarray(x) ** 2))) < SILENT_RMS:
            continue
        role = roles_of[name]
        o = place(name, role, cfg, g3, character)
        o.update({"name": name, "leaf": name, "role": role, "kind": "object"})
        a = o["az"]
        # Decision 0031: never collapse a part to mono, never feed one part's centre to two
        # far-apart sources. A pair becomes an upmix (centre in front, each side out at +/-az);
        # a mono role with a side width keeps its own stereo width around its position.
        if o["mode"] == "pair":
            o["mode"] = "upmix"
            o["feeds"] = [{"ch": "C", "az": 0.0, "el": o["el"]},
                          {"ch": "Ls", "az": abs(a), "el": o["el"]},
                          {"ch": "Rs", "az": -abs(a), "el": o["el"]}]
        elif o["mode"] == "mono" and o.get("side_w"):
            w = float(o["side_w"])
            o["mode"] = "upmix"
            o["spread"] = round(2.0 * w, 1)
            o["feeds"] = [{"ch": "C", "az": a, "el": o["el"]},
                          {"ch": "Ls", "az": a + w, "el": o["el"]},
                          {"ch": "Rs", "az": a - w, "el": o["el"]}]
        else:
            o["feeds"] = [{"ch": "M", "az": a, "el": o["el"]}]
        o["events"] = [e for e in events if e["role"] == role or (
            e["role"] == "toms" and role == "toms")]
        o["events"] = [{k: v for k, v in e.items() if k != "role"} for e in o["events"]]
        if role in ("lead_vocal", "kick", "snare", "bass") or o.get("protected"):
            o["events"] = []
            o["breathes"] = False
        o["gain_db"] = float(o.get("gain_db", 0.0))
        e = np.sum(np.asarray(x, dtype=np.float64) ** 2, axis=1) + 1e-20
        o["ch_share"] = {"L": round(float(e[0] / e.sum()), 4), "R": round(float(e[1] / e.sum()), 4),
                         "M": 1.0}
        if o["mode"] == "upmix":
            from stage.spatial.upmix import centre_sides

            parts = centre_sides(np.asarray(x), sample_rate)
            ep = {k: float(np.sum(np.asarray(v, dtype=np.float64) ** 2)) for k, v in parts.items()}
            tot = sum(ep.values()) + 1e-20
            o["ch_share"].update({k: round(v / tot, 4) for k, v in ep.items()})
        objects.append(o)
    ret_gain = float(g3.get("return", 1.0)) * CHARACTER_STAGE[character][2]
    ret_cfg = cfg["returns"]
    for name in (returns or {}):
        w = {"side": ret_cfg["side"], "rear": ret_cfg["rear"], "height": ret_cfg["height"]}
        feeds = []
        for ch, sign in (("L", 1.0), ("R", -1.0)):
            for layer, az, el in RETURN_RING:
                share = w[layer] / (2.0 if layer == "height" else 1.0) / 2.0
                feeds.append({"ch": ch, "az": sign * az, "el": el, "weight": share})
        objects.append({"name": f"{name}~return", "leaf": f"{name}~return", "kind": "return",
                        "role": "return", "mode": "ring", "az": 0.0, "el": 0.0, "dist": 1.5,
                        "spread": 0.0, "protected": False, "breathes": False, "events": [],
                        "gain_db": round(20 * np.log10(max(ret_gain, 1e-3)), 2), "feeds": feeds,
                        "why": "The record's own reverb for this part, returned from the sides, "
                               "rear and above at its original level; none from the front."})
    first_downbeat = analysis.downbeats_s[0] if analysis.downbeats_s else 0.0
    plan: dict[str, Any] = {
        "version": PLAN_VERSION, "engine": "soundstage-v3", "track_id": track_id,
        "mode": "objects", "genre": genre, "genre_source": genre_source,
        "style": {k: round(float(v), 4) for k, v in (genre_scores or {}).items()},
        "template": template.get("label", genre),
        "space": space or g3.get("space", DEFAULT_SPACE), "hrtf": hrtf,
        "character": character, "motion_depth": round(float(motion_depth), 3),
        "crossover_hz": float(crossover_hz), "tempo_bpm": round(float(tempo), 3),
        "first_downbeat_s": round(float(first_downbeat), 3), "sections": sections,
        "stage": {k: g3.get(k) for k in ("stage_width", "height", "rear", "return", "motion")},
        "stems": objects,  # named `stems` as in v2, so the diagnostics and the web app read both
        "protected": [o["name"] for o in objects if o.get("protected")],
        "events": [e for e in events],
        "early": {"order": 2, "note": "reflections come from the plan's space; none after 80 ms"},
    }
    plan["analysis_sample_rate"] = int(sample_rate)
    add_energy_feeds(plan)
    return plan


def add_energy_feeds(plan: dict[str, Any], seconds: float | None = None) -> None:
    """Give each object `energy_feeds`: where its energy sits, for the diagnostics.

    Weights are the object's energy shares over its feeds averaged over the song (positions
    sampled once a second, merged into 10 degree cells), so a moving object shows where it
    spends its time. The direct and early shares come from the impulse response of the plan's
    space at each position (a return is all late: the record's own reverb, none of it direct).
    """
    from stage.scene3.render import direct_early_shares, openness_at

    dur = seconds if seconds is not None else max(
        [s["end_s"] for s in plan["sections"]] + [10.0])
    t = np.arange(0.0, dur, 1.0)
    op = openness_at(plan, t)
    for o in plan["stems"]:
        if o["kind"] == "return":
            o["energy_feeds"] = [{"az": f["az"], "el": f["el"], "weight": f["weight"],
                                  "direct": 0.0, "early": 0.0} for f in o["feeds"]]
            continue
        paths = object_paths(o, plan, t, op)
        cells: dict[tuple[int, int], float] = {}
        share = o.get("ch_share", {})
        for feed, (az_t, el_t) in zip(o["feeds"], paths, strict=True):
            # A pair's two sources carry the leaf's left and right channel energy, so a source
            # panned hard left is mostly in its left feed.
            w_feed = share.get(feed["ch"], 1.0)
            for a, e in zip(az_t, el_t, strict=True):
                key = (round(float(a) / 10.0), round(float(e) / 10.0))
                cells[key] = cells.get(key, 0.0) + w_feed / len(az_t)
        feeds = []
        for (ca, ce), w in sorted(cells.items()):
            direct, early = direct_early_shares(plan, ca * 10.0, ce * 10.0, o["dist"])
            feeds.append({"az": ca * 10.0, "el": ce * 10.0, "weight": round(w, 5),
                          "direct": round(direct, 4), "early": round(early, 4)})
        o["energy_feeds"] = feeds


def plan_json(plan: dict[str, Any]) -> str:
    return json.dumps(plan, indent=2, sort_keys=True)
