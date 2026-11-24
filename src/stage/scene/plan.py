"""The spatial mix plan: the contract between analysis, the listener's settings and the renderer.

Decisions 0017 and 0018. `build_plan` turns a genre template, the song analysis and the settings
(space, motion depth, genre override) into plan.json (schemas/plan.schema.json). It is pure and
deterministic: the same inputs always give the same plan, and the renderer reads nothing else,
so the web app can edit a plan and send it back for a re-render without re-separating.

Motion rules (0018):
* the lead vocal, the bass and the kit are protected and never move;
* paths are locked to the bar grid: a period is a whole number of bars, phase zero on the first
  downbeat, and every path is a smooth sinusoid or a constant-speed turn (no corners);
* the angular speed is capped at MAX_DEG_PER_S; a path that would exceed it has its period
  doubled until it does not;
* motion depth (0 to 1, the listener's control) scales every path; 0 is a static scene.
"""

from __future__ import annotations

import copy
import json
import math
from typing import Any

from stage.config import config_dir, load_json
from stage.scene.analysis import SongAnalysis

PLAN_VERSION = 2
#: Character: how far the scene opens around the listener. Multipliers for the bed (ambience,
#: heights) and every object's room send. "balanced" is the template as written.
CHARACTERS = {"intimate": (0.6, 0.5, 0.6), "balanced": (1.0, 1.0, 1.0),
              "immersive": (1.35, 1.4, 1.3)}
#: Speed cap for moving sources. Rotating sound fields can induce illusory self-motion (auditory
#: vection) and discomfort in some listeners, with effects reported for rotation speeds of tens of
#: degrees per second and above (Valjamae 2009, "Auditorily-induced illusory self-motion: a
#: review", Brain Research Reviews 61(2)). 45 degrees per second keeps a full orbit at 8 s or
#: slower. SPECULATIVE as a threshold: chosen conservatively, not measured here.
MAX_DEG_PER_S = 45.0
DEFAULT_GENRE = "pop"
#: Lite renders the whole mix: the direct part as the front stage, the ambient part as the bed.
LITE_OBJECTS = [
    {"name": "front", "source": "mix.direct", "az": 0.0, "el": 0.0, "dist": 2.0, "spread": 60.0,
     "room_send": 0.3, "orig_blend": 0.0, "protected": True,
     "why": "The whole mix's direct sound on the front stage, where the stereo image was made."},
    {"name": "ambience", "source": "mix.ambient", "az": 0.0, "el": 0.0, "dist": 3.0,
     "spread": 0.0, "room_send": 0.6, "orig_blend": 0.0, "protected": False,
     "why": "The mix's ambience opened into the surround and height bed."},
]


def templates() -> dict[str, dict[str, Any]]:
    folder = config_dir() / "templates"
    return {p.stem: load_json(f"templates/{p.name}") for p in sorted(folder.glob("*.json"))}


def get_template(genre: str) -> dict[str, Any]:
    all_t = templates()
    if genre not in all_t:
        raise ValueError(f"unknown genre {genre!r}; known: {sorted(all_t)}")
    return copy.deepcopy(all_t[genre])


def _period_s(bars: float, tempo_bpm: float) -> float:
    return bars * 4.0 * 60.0 / tempo_bpm


def cap_motion(motion: dict[str, Any], tempo_bpm: float, depth_scale: float
               ) -> dict[str, Any] | None:
    """Scale a template path by the motion depth and lengthen its period until it is under the cap.

    Returns None when the scaled depth is zero (a static object).
    """
    depth = float(motion.get("depth", 0.0)) * depth_scale
    if depth <= 0.0:
        return None
    path = motion.get("path", "sway")
    bars = float(motion.get("period_bars", 8))
    # A full turn needs the whole depth; anything less than a turn is a sway of that width.
    if path == "orbit" and depth < 360.0:
        path = "sway"
    for _ in range(8):
        period = _period_s(bars, tempo_bpm)
        speed = 360.0 / period if path == "orbit" else math.pi * depth / period
        if speed <= MAX_DEG_PER_S:
            break
        bars *= 2.0
    return {"path": path, "period_bars": bars, "depth": round(depth, 2),
            "max_deg_per_s": round(speed, 2)}


def section_openness(analysis: SongAnalysis, template: dict[str, Any]) -> list[dict[str, Any]]:
    table = template.get("sections", {})
    return [{"start_s": round(s.start_s, 3), "end_s": round(s.end_s, 3), "label": s.label,
             "openness": float(table.get(s.label, 0.5))} for s in analysis.sections]


def build_plan(analysis: SongAnalysis, *, track_id: str, mode: str, genre: str | None,
               space: str | None, motion_depth: float, crossover_hz: float = 120.0,
               genre_source: str = "default", genre_scores: dict[str, float] | None = None,
               character: str = "balanced") -> dict[str, Any]:
    """The plan for one excerpt. `mode` is "stems" or "lite"; `space` None takes the template's."""
    if not 0.0 <= motion_depth <= 1.0:
        raise ValueError("motion depth must be between 0 and 1")
    if character not in CHARACTERS:
        raise ValueError(f"character must be one of {sorted(CHARACTERS)}")
    bed_k, height_k, room_k = CHARACTERS[character]
    genre = genre or DEFAULT_GENRE
    template = get_template(genre)
    tempo = analysis.tempo_bpm if analysis.tempo_bpm > 0 else 120.0
    objects = copy.deepcopy(template["objects"]) if mode == "stems" else copy.deepcopy(
        LITE_OBJECTS)
    out_objects = []
    for o in objects:
        o.pop("why", None)
        motion = o.pop("motion", None)
        if motion and not o.get("protected"):
            capped = cap_motion(motion, tempo, motion_depth)
            if capped:
                o["motion"] = capped
        o.setdefault("mono_below_hz", crossover_hz)
        o["room_send"] = round(min(1.0, float(o["room_send"]) * room_k), 3)
        out_objects.append(o)
    bed = dict(template.get("bed", {"ambience": 1.0, "heights": 0.5}))
    bed = {"ambience": round(min(2.0, bed.get("ambience", 1.0) * bed_k), 3),
           "heights": round(min(2.0, bed.get("heights", 0.5) * height_k), 3)}
    first_downbeat = analysis.downbeats_s[0] if analysis.downbeats_s else 0.0
    return {
        "version": PLAN_VERSION,
        "track_id": track_id,
        "engine": "soundstage-v2",
        "mode": mode,
        "intensity": round(float(motion_depth), 3),
        "genre": genre,
        "genre_source": genre_source,
        "style": {k: round(float(v), 4) for k, v in (genre_scores or {}).items()},
        "template": template.get("label", genre),
        "space": space or template.get("space", "studio"),
        "motion_depth": round(float(motion_depth), 3),
        "crossover_hz": float(crossover_hz),
        "tempo_bpm": round(float(tempo), 3),
        "first_downbeat_s": round(float(first_downbeat), 3),
        "sections": section_openness(analysis, template),
        "character": character,
        "bed": bed,
        "stems": out_objects,
        "protected": [o["name"] for o in out_objects if o.get("protected")],
        "room": {"predelay_ms": 0.0},
    }


def plan_json(plan: dict[str, Any]) -> str:
    """Canonical text of a plan (sorted keys), so equal plans are byte-identical."""
    return json.dumps(plan, indent=2, sort_keys=True)


def validate_plan(plan: dict[str, Any]) -> None:
    """Check a plan against schemas/plan.schema.json when jsonschema is installed, and always
    check what the renderer relies on (known space, known source parts, protected objects still)."""
    from stage.spatial.room import spaces

    try:
        import jsonschema

        schema = json.loads((config_dir().parent / "schemas" / "plan.schema.json").read_text(
            encoding="utf-8")) if (config_dir().parent / "schemas").is_dir() else None
        if schema is not None:
            jsonschema.validate(plan, schema)
    except ImportError:
        pass
    if plan.get("space") not in spaces():
        raise ValueError(f"unknown space {plan.get('space')!r}")
    for o in plan.get("stems", []):
        stem, _, part = str(o.get("source", "mix.direct")).partition(".")
        if stem not in ("vocals", "drums", "bass", "other", "mix") or part not in (
                "direct", "ambient", "mid", "high", "all"):
            raise ValueError(f"object {o.get('name')!r} has an unknown source {o.get('source')!r}")
        if o.get("protected") and o.get("motion"):
            raise ValueError(f"object {o.get('name')!r} is protected and cannot move")
