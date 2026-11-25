"""The catalogue the backend serves: the committed seed, refreshed from the sources in the
background, searched live with a cache, and a registry of every track it has shown.

The registry matters for safety: the audio proxy and the render-from-catalogue route only ever
fetch the audio URL of a track this process itself listed, so neither can be pointed at an
arbitrary address.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from stage.catalogue.build import build_catalogue, norm, shelf_config
from stage.catalogue.model import Track
from stage.catalogue.sources import Jamendo, Openverse
from stage.config import config_dir

SEED_FILE = "catalogue/seed.json"
SEARCH_TTL_S = 6 * 3600.0
MAX_CACHED_SEARCHES = 200


def load_seed() -> dict[str, Any]:
    p = config_dir() / SEED_FILE
    if not p.is_file():
        return {"shelves": {}, "tracks": {}, "built_utc": None}
    return json.loads(p.read_text(encoding="utf-8"))


class Catalogue:
    def __init__(self, openverse: Openverse | None = None, jamendo: Jamendo | None = None,
                 seed: dict[str, Any] | None = None, allow_nc: bool = False) -> None:
        self.openverse = openverse or Openverse()
        self.jamendo = jamendo or Jamendo()
        self.allow_nc = allow_nc
        self.lock = threading.Lock()
        self.data = seed if seed is not None else load_seed()
        self.registry: dict[str, Track] = {tid: Track.from_dict(t)
                                           for tid, t in self.data.get("tracks", {}).items()}
        self.cache: dict[tuple, tuple[float, list[str]]] = {}
        self.refreshed_utc: str | None = None

    # -- browsing ------------------------------------------------------------------------------
    def shelves(self) -> list[dict[str, Any]]:
        out = []
        for key, sh in self.data.get("shelves", {}).items():
            tracks = [self.registry[i].as_dict() for i in sh["tracks"] if i in self.registry]
            if tracks:
                out.append({"key": key, "title": sh["title"], "tracks": tracks})
        return out

    def track(self, tid: str) -> Track | None:
        return self.registry.get(tid)

    def genre(self, key: str, page: int = 1, page_size: int = 24) -> dict[str, Any]:
        cfg = shelf_config()["shelves"].get(key)
        if cfg is None:
            raise KeyError(key)
        listed = self.data.get("shelves", {}).get(key, {"tracks": []})["tracks"]
        ids = list(listed)
        # More of the genre, live: the shelf's own terms, deduplicated against what is listed.
        for term in cfg["terms"][:2]:
            for t in self._live(term, page=page):
                if t.id not in ids and norm(t.artist):
                    ids.append(t.id)
        start = (page - 1) * page_size
        return {"key": key, "title": cfg["title"], "page": page,
                "tracks": [self.registry[i].as_dict() for i in ids[start : start + page_size]
                           if i in self.registry]}

    def search(self, q: str, page: int = 1, creator: str = "") -> list[dict[str, Any]]:
        q = q.strip()
        local = [t for t in self.registry.values()
                 if q and (norm(q) in norm(t.title) or norm(q) in norm(t.artist)
                           or norm(q) in norm(" ".join(t.genres)))]
        ids = [t.id for t in local]
        for t in self._live(q, page=page, creator=creator):
            if t.id not in ids:
                ids.append(t.id)
        return [self.registry[i].as_dict() for i in ids]

    def artist(self, name: str) -> dict[str, Any]:
        tracks = [t for t in self.registry.values() if norm(t.artist) == norm(name)]
        for t in self._live("", creator=name):
            if norm(t.artist) == norm(name) and t.id not in {x.id for x in tracks}:
                tracks.append(self.registry[t.id])
        return {"name": name, "tracks": [t.as_dict() for t in tracks]}

    # -- live search with a cache --------------------------------------------------------------
    def _live(self, q: str, page: int = 1, creator: str = "") -> list[Track]:
        key = (q, page, creator, self.allow_nc)
        now = time.time()
        with self.lock:
            hit = self.cache.get(key)
        if hit and now - hit[0] < SEARCH_TTL_S:
            return [self.registry[i] for i in hit[1] if i in self.registry]
        found: list[Track] = []
        try:
            extra = {"creator": creator} if creator else None
            found += self.openverse.search(q or creator, page=page, allow_nc=self.allow_nc,
                                           extra=extra)
        except Exception:
            pass  # a source being down leaves the seed and the cache to answer
        if self.jamendo.available:
            try:
                found += self.jamendo.search(search=q or creator, allow_nc=self.allow_nc)
            except Exception:
                pass
        cfg = shelf_config()
        found = [t for t in found if cfg["min_duration_s"] <= t.duration_s <= cfg["max_duration_s"]]
        with self.lock:
            for t in found:
                self.registry.setdefault(t.id, t)
            if len(self.cache) >= MAX_CACHED_SEARCHES:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = (now, [t.id for t in found])
        return found

    # -- refresh -------------------------------------------------------------------------------
    def refresh(self, pages: int = 2) -> dict[str, Any]:
        cat = build_catalogue(self.openverse, self.jamendo, pages=pages, verify=True,
                              allow_nc=self.allow_nc)
        with self.lock:
            self.data = cat
            for tid, t in cat["tracks"].items():
                self.registry[tid] = Track.from_dict(t)
        self.refreshed_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return cat["policy"] | {"tracks": len(cat["tracks"])}

    def refresh_in_background(self, pages: int = 2) -> threading.Thread:
        th = threading.Thread(target=lambda: self._safe_refresh(pages), daemon=True,
                              name="soundstage-catalogue")
        th.start()
        return th

    def _safe_refresh(self, pages: int) -> None:
        try:
            self.refresh(pages)
        except Exception as exc:
            print(f"catalogue refresh failed, serving the seed: {exc}", flush=True)
