"""Build the shelves from the sources: search, filter, place, de-duplicate, verify.

`build_catalogue` is what the harvest script, the nightly job and the backend's refresh all run.
For each shelf it searches every term on Openverse (and on Jamendo when a client_id is set),
keeps tracks with an accepted licence and a usable length, places each on the shelves whose genre
tags it carries (a term is also a tag: a track found by "gospel" belongs on the gospel shelf),
orders by how many of the shelf's terms found it and then by the source's own order, takes at most
`per_artist` tracks per artist, and finally checks each chosen track's audio URL is live.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from stage.catalogue.model import Track
from stage.catalogue.sources import Jamendo, Openverse, check_audio
from stage.config import load_json

SPATIAL_FIRST_TAGS = ("ambient", "cinematic", "orchestral", "electronic", "world", "newage")


def shelf_config() -> dict[str, Any]:
    return load_json("catalogue/shelves.json")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def usable(t: Track, cfg: dict[str, Any]) -> bool:
    return bool(t.title) and cfg["min_duration_s"] <= t.duration_s <= cfg["max_duration_s"]


def place(t: Track, shelves: dict[str, Any], found_by: set[str]) -> list[str]:
    """The shelves a track belongs on: by its own genre tags, never by a search hit alone. A
    track with no genre tags is placed by the shelf's term appearing in its title."""
    tags = {norm(g) for g in t.genres}
    title = norm(t.title)
    out = []
    for key, sh in shelves.items():
        if key == "made_for_spatial":
            continue
        shelf_tags = {norm(x) for x in sh["tags"]}
        bad = {norm(x) for x in sh.get("exclude", [])}
        if tags & bad:
            continue
        if tags & shelf_tags:
            out.append(key)
        elif not tags and key in found_by and any(norm(term) in title for term in sh["terms"]):
            out.append(key)
    return out


def shelf_score(t: Track, sh: dict[str, Any], hits: int) -> float:
    tags = {norm(g) for g in t.genres}
    own = len(tags & {norm(x) for x in sh["tags"]})
    return 2.0 * own + hits + (1.0 if t.artwork_url else 0.0) + 0.5 * bool(t.genres)


def build_catalogue(openverse: Openverse | None = None, jamendo: Jamendo | None = None,
                    pages: int = 2, verify: bool = True, allow_nc: bool = False,
                    log: Any = None) -> dict[str, Any]:
    cfg = shelf_config()
    shelves = cfg["shelves"]
    ov = openverse or Openverse()
    found: dict[str, Track] = {}
    found_by: dict[str, set[str]] = defaultdict(set)
    hits: dict[tuple[str, str], int] = defaultdict(int)
    for key, sh in shelves.items():
        for term in sh["terms"]:
            for page in range(1, pages + 1):
                try:
                    batch = ov.search(term, page=page, allow_nc=allow_nc)
                except Exception as exc:  # a source being down must not empty the catalogue
                    if log:
                        log(f"openverse {term!r} page {page}: {exc}")
                    break
                if not batch:
                    break
                for t in batch:
                    if usable(t, cfg):
                        found.setdefault(t.id, t)
                        found_by[t.id].add(key)
                        hits[(t.id, key)] += 1
            if jamendo is not None and jamendo.available:
                for t in jamendo.search(search=term, allow_nc=allow_nc):
                    if usable(t, cfg):
                        found.setdefault(t.id, t)
                        found_by[t.id].add(key)
                        hits[(t.id, key)] += 1
    by_shelf: dict[str, list[Track]] = defaultdict(list)
    for tid, t in found.items():
        for key in place(t, shelves, found_by[tid]):
            by_shelf[key].append(t)
    chosen: dict[str, Track] = {}
    out_shelves: dict[str, list[str]] = {}
    taken_artist: dict[str, int] = defaultdict(int)
    for key, sh in shelves.items():
        if key == "made_for_spatial":
            continue
        cand = sorted(by_shelf[key], key=lambda t: -shelf_score(t, sh, hits[(t.id, key)]))
        picked: list[Track] = []
        per_artist: dict[str, int] = defaultdict(int)
        for t in cand:
            if len(picked) >= sh["max"]:
                break
            if per_artist[norm(t.artist)] >= cfg["per_artist"] or t.id in out_shelves.get(key, []):
                continue
            if verify:
                if "ok" not in t.checked:
                    t.checked = check_audio(t.audio_url)
                if not t.checked.get("ok"):
                    continue
            picked.append(t)
            per_artist[norm(t.artist)] += 1
        out_shelves[key] = [t.id for t in picked]
        for t in picked:
            chosen.setdefault(t.id, t)
            if key not in t.shelves:
                t.shelves.append(key)
            taken_artist[norm(t.artist)] += 1
    # Made for spatial: the chosen tracks whose genres favour wide, layered arrangements.
    sp = shelves["made_for_spatial"]
    spatial_tags = {norm(x) for x in sp["tags"]}
    cand = sorted(chosen.values(), key=lambda t: (-len(spatial_tags & {norm(g) for g in t.genres}),
                                                  -t.duration_s))
    pick = [t for t in cand if spatial_tags & {norm(g) for g in t.genres}][: sp["max"]]
    out_shelves["made_for_spatial"] = [t.id for t in pick]
    for t in pick:
        t.shelves.append("made_for_spatial")
    return {"shelves": {k: {"title": shelves[k]["title"], "tracks": v}
                        for k, v in out_shelves.items()},
            "tracks": {tid: t.as_dict() for tid, t in chosen.items()},
            "policy": {"allow_nc": allow_nc, "min_duration_s": cfg["min_duration_s"],
                       "max_duration_s": cfg["max_duration_s"], "per_artist": cfg["per_artist"]}}
