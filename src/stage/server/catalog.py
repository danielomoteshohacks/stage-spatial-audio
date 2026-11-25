"""Catalogue routes (decision 0028):

    GET /catalog/shelves                     the shelves, each with its tracks
    GET /catalog/search?q=&creator=&page=    the seed, then live results from the sources
    GET /catalog/genre/{key}?page=           one shelf, with more of its genre from the sources
    GET /catalog/artist?name=                one artist's tracks
    GET /catalog/track/{id}                  one track, with its licence, attribution and whether
                                             a pre-rendered spatial version exists
    GET /audio/{id}                          the original audio, proxied (Range supported), so the
                                             browser's A/B switch can read it without CORS limits
    GET /catalog/legal                       what is offered, from where, under which licences
    POST /v3/jobs/from-catalog               render a catalogue track on demand (the server
                                             downloads it; nothing is uploaded by the listener)

Keys (JAMENDO_CLIENT_ID) stay in the server's environment. Only tracks this process listed can be
fetched. Responses carry no personal data and nothing is logged about who listened to what.
"""

from __future__ import annotations

import json
import shutil
import urllib.request
from collections import Counter
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from stage.catalogue.fetch import FetchRefused, download, iter_stream, open_stream, suffix_for
from stage.catalogue.sources import UA
from stage.catalogue.store import Catalogue
from stage.server.api import JobStore, parse_options
from stage.service import ValidationError, validate_upload
from stage.stream.job import Provider, iter_job, new_job

PRERENDER_BASE = "https://huggingface.co/datasets/danieltesh/soundstage-catalogue/resolve/main/"
PRERENDER_INDEX = "index.json"


def prerendered_index(timeout: float = 8.0) -> dict[str, Any]:
    """The dataset's index of pre-rendered tracks; empty when the dataset does not exist yet."""
    try:
        req = urllib.request.Request(PRERENDER_BASE + PRERENDER_INDEX, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"tracks": {}}


def legal(cat: Catalogue) -> dict[str, Any]:
    tracks = list(cat.registry.values())
    return {
        "what": "Only music offered under an open licence that permits adaptation. Spatialising "
                "a recording is an adaptation, so every track under a NoDerivatives licence is "
                "excluded, and so (unless the operator enables them) are NonCommercial licences.",
        "sources": [
            {"name": "Openverse", "url": "https://openverse.org",
             "note": "A search index of openly licensed media (WordPress). Used for search; the "
                     "audio itself is served by the original host named on each track."},
            {"name": "Jamendo", "url": "https://www.jamendo.com",
             "note": "Independent artists' music. The Jamendo API is free for non-commercial use "
                     "with a client id; tracks whose download is not allowed are skipped."},
            {"name": "Wikimedia Commons", "url": "https://commons.wikimedia.org",
             "note": "Freely licensed and public-domain recordings, reached through Openverse."}],
        "licences": dict(Counter(t.licence.label for t in tracks)),
        "obligations": {
            "CC BY": "Credit the creator, link the licence, say the audio was changed.",
            "CC BY-SA": "As CC BY, and the spatial render is shared under CC BY-SA too.",
            "CC0 and Public Domain Mark": "No conditions; credit is shown anyway."},
        "streaming": "Original audio is streamed through this server so the Original / "
                     "Spatial switch can be sample-locked; it is not stored. Pre-rendered "
                     "spatial versions are stored in a public dataset with the licence and "
                     "attribution of each track beside it.",
        "contact": "Report a track that should not be here and it is removed.",
        "tracks_listed": len(tracks)}


def create_catalog_router(cat: Catalogue, store: JobStore,
                          provider_factory: Any = None, background: bool = True) -> APIRouter:
    router = APIRouter()

    @router.get("/catalog/shelves")
    def shelves() -> dict[str, Any]:
        return {"shelves": cat.shelves(), "built_utc": cat.data.get("built_utc"),
                "jamendo": cat.jamendo.available}

    @router.get("/catalog/search")
    def search(q: str = "", creator: str = "", page: int = 1) -> dict[str, Any]:
        if len(q) > 80 or len(creator) > 80 or not 1 <= page <= 20:
            raise HTTPException(400, "query too long or page out of range")
        return {"q": q, "tracks": cat.search(q, page=page, creator=creator)[:60]}

    @router.get("/catalog/genre/{key}")
    def genre(key: str, page: int = 1) -> dict[str, Any]:
        try:
            return cat.genre(key, page=max(1, min(page, 20)))
        except KeyError as exc:
            raise HTTPException(404, "unknown genre") from exc

    @router.get("/catalog/artist")
    def artist(name: str) -> dict[str, Any]:
        if not name or len(name) > 80:
            raise HTTPException(400, "give an artist name")
        return cat.artist(name)

    @router.get("/catalog/legal")
    def legal_page() -> dict[str, Any]:
        return legal(cat)

    @router.get("/catalog/track/{tid:path}")
    def track(tid: str) -> dict[str, Any]:
        t = cat.track(tid)
        if t is None:
            raise HTTPException(404, "unknown track")
        idx = prerendered_index().get("tracks", {})
        d = t.as_dict()
        d["prerendered"] = idx.get(tid)
        return d

    @router.get("/audio/{tid:path}")
    def audio(tid: str, range: str | None = Header(default=None)) -> StreamingResponse:  # noqa: A002
        t = cat.track(tid)
        if t is None:
            raise HTTPException(404, "unknown track")
        try:
            resp = open_stream(t, range)
        except FetchRefused as exc:
            raise HTTPException(403, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"the source did not answer: {type(exc).__name__}") from exc
        headers = {k: v for k, v in resp.headers.items()
                   if k.lower() in ("content-length", "content-range", "accept-ranges")}
        headers["Cache-Control"] = "public, max-age=3600"
        return StreamingResponse(iter_stream(resp), status_code=resp.status,
                                 media_type=resp.headers.get("Content-Type", "audio/mpeg"),
                                 headers=headers)

    @router.post("/v3/jobs/from-catalog")
    def from_catalog(body: dict[str, Any]) -> JSONResponse:
        t = cat.track(str(body.get("id", "")))
        if t is None:
            raise HTTPException(404, "unknown track")
        try:
            opts = parse_options(json.dumps(body.get("options") or {}))
            opts.validate()
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, f"The settings were not understood: {exc}") from exc
        if store.pending >= 4:
            raise HTTPException(429, "The server is busy; try again in a minute.")
        job = new_job(store.root, opts)
        dest = job.dir / f"source{suffix_for(t)}"
        try:
            download(t, dest)
            readable, duration, notes = validate_upload(dest, job.dir)
        except (FetchRefused, ValidationError) as exc:
            shutil.rmtree(job.dir, ignore_errors=True)
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            shutil.rmtree(job.dir, ignore_errors=True)
            raise HTTPException(502, f"could not fetch the track: {type(exc).__name__}") from exc
        job.update(notes=notes, source_duration_s=round(duration, 2), track=t.as_dict())
        with store.lock:
            store.jobs[job.id] = job
        if background:
            provider: Provider | None = provider_factory(opts.preset) if provider_factory else None
            store.pending += 1

            def work() -> None:
                try:
                    for _ in iter_job(job, readable, provider):
                        pass
                finally:
                    store.pending -= 1

            store.pool.submit(work)
        return JSONResponse({"id": job.id})

    return router
