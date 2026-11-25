"""Where catalogue tracks come from, and the rules each source's terms ask us to follow.

* **Openverse** (api.openverse.org, WordPress; no key at low rates: anonymous 20 requests a
  minute and 200 a day, read from its response headers). It indexes openly licensed audio from
  Jamendo, Wikimedia Commons, Freesound and others. We ask for `category=music` and
  `license_type=commercial,modification` (the licences that allow adaptation and use by anyone),
  then check the licence again ourselves (`licences.accepted`) because a filter is not a
  guarantee.
* **Jamendo API v3** (api.jamendo.com): free for non-commercial use with a `client_id` (the
  owner's, read from the environment variable JAMENDO_CLIENT_ID, never committed). We use
  `audiodownload_allowed` and `audiodownload` as the API states them and skip a track that does
  not allow download; licences come from `license_ccurl`.
* The Free Music Archive and Wikimedia Commons directly were considered; FMA's API terms were not
  readable from the build environment and Commons music is already reached through Openverse, so
  neither is called directly.

Sources are plain classes over `urllib` so the backend, the harvest script and the tests share
them; a fetch function can be injected, which is how the tests run on recorded responses.
"""

from __future__ import annotations

import html
import json
import os
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from stage.catalogue.licences import Licence, accepted, from_openverse, parse_url
from stage.catalogue.model import Track

UA = ("soundstage-catalogue/1 (open-source research demo; "
      "github.com/danielomoteshohacks/stage-spatial-audio)")
Fetch = Callable[[str], Any]


def http_json(url: str, timeout: float = 40.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class RateLimiter:
    """Keeps requests under `per_minute`, for sources with a burst limit."""

    def __init__(self, per_minute: float) -> None:
        self.gap = 60.0 / per_minute
        self.last = 0.0

    def wait(self) -> None:
        d = self.last + self.gap - time.monotonic()
        if d > 0:
            time.sleep(d)
        self.last = time.monotonic()


class Openverse:
    base = "https://api.openverse.org/v1/audio/"

    def __init__(self, fetch: Fetch | None = None, per_minute: float = 18.0) -> None:
        self.fetch = fetch or http_json
        self.limit = RateLimiter(per_minute) if fetch is None else None

    def search(self, q: str, *, source: str | None = None, page: int = 1, page_size: int = 20,
               allow_nc: bool = False, extra: dict[str, str] | None = None) -> list[Track]:
        params = {"q": q, "category": "music", "page": str(page), "page_size": str(page_size),
                  "license_type": "modification" if allow_nc else "commercial,modification"}
        if source:
            params["source"] = source
        params.update(extra or {})
        if self.limit:
            self.limit.wait()
        data = self.fetch(self.base + "?" + urllib.parse.urlencode(params))
        return [t for r in data.get("results", []) if (t := self.to_track(r, allow_nc))]

    @staticmethod
    def to_track(r: dict[str, Any], allow_nc: bool = False) -> Track | None:
        lic = from_openverse(r.get("license"), r.get("license_version"))
        if not accepted(lic, allow_nc) or not r.get("url"):
            return None
        aset = r.get("audio_set") or {}
        return Track(
            id=f"{r.get('source') or r.get('provider')}:{r['id']}",
            title=html.unescape((r.get("title") or "").strip()),
            artist=html.unescape((r.get("creator") or "Unknown artist").strip()),
            audio_url=r["url"],
            landing_url=r.get("foreign_landing_url") or "", licence=lic,
            source=str(r.get("source") or r.get("provider")),
            duration_s=round(float(r.get("duration") or 0) / 1000.0, 1),
            artist_url=r.get("creator_url") or aset.get("creator_url") or "",
            album=aset.get("title") or "", artwork_url=r.get("thumbnail") or "",
            genres=[g.lower() for g in (r.get("genres") or [])],
            filetype=r.get("filetype") or "")


class Jamendo:
    """Jamendo API v3. Needs a client_id; without one `available` is False and nothing is called."""

    base = "https://api.jamendo.com/v3.0/tracks/"

    def __init__(self, client_id: str | None = None, fetch: Fetch | None = None) -> None:
        self.client_id = client_id or os.environ.get("JAMENDO_CLIENT_ID", "")
        self.fetch = fetch or http_json

    @property
    def available(self) -> bool:
        return bool(self.client_id)

    def search(self, *, tags: str = "", search: str = "", order: str = "popularity_month",
               limit: int = 20, offset: int = 0, allow_nc: bool = False) -> list[Track]:
        if not self.available:
            return []
        params = {"client_id": self.client_id, "format": "json", "limit": str(limit),
                  "offset": str(offset), "order": order, "audioformat": "mp32",
                  "include": "musicinfo licenses", "imagesize": "300", "boost": "popularity_month"}
        if tags:
            params["fuzzytags"] = tags
        if search:
            params["search"] = search
        data = self.fetch(self.base + "?" + urllib.parse.urlencode(params))
        return [t for r in data.get("results", []) if (t := self.to_track(r, allow_nc))]

    @staticmethod
    def to_track(r: dict[str, Any], allow_nc: bool = False) -> Track | None:
        if not r.get("audiodownload_allowed", False):
            return None  # the API says this track may not be downloaded: respect it
        lic: Licence = parse_url(r.get("license_ccurl"))
        if not accepted(lic, allow_nc) or not r.get("audiodownload"):
            return None
        tags = (r.get("musicinfo") or {}).get("tags") or {}
        genres = [g.lower() for g in (tags.get("genres") or [])]
        return Track(
            id=f"jamendo:{r['id']}", title=r.get("name", "").strip(),
            artist=r.get("artist_name", "Unknown artist"), audio_url=r["audiodownload"],
            landing_url=r.get("shareurl") or f"https://www.jamendo.com/track/{r['id']}",
            licence=lic, source="jamendo", duration_s=float(r.get("duration") or 0),
            artist_url=f"https://www.jamendo.com/artist/{r.get('artist_id')}",
            album=r.get("album_name", ""), artwork_url=r.get("image") or r.get("album_image") or "",
            genres=genres, filetype="mp3")


def check_audio(url: str, timeout: float = 30.0) -> dict[str, Any]:
    """Is the audio URL live and audio? A ranged GET of the first bytes (HEAD is refused by some
    storage hosts); returns status, content type and size when the server says."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1023"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type", "")
            total = resp.headers.get("Content-Range", "").split("/")[-1] or resp.headers.get(
                "Content-Length", "")
            head = resp.read(16)
            looks_audio = head[:3] == b"ID3" or head[:2] == b"\xff\xfb" or head[:4] in (
                b"OggS", b"fLaC", b"RIFF") or head[:2] in (b"\xff\xf3", b"\xff\xf2") or \
                head[4:8] == b"ftyp"
            return {"ok": resp.status in (200, 206) and (ct.startswith("audio") or looks_audio),
                    "status": resp.status, "content_type": ct,
                    "bytes": int(total) if str(total).isdigit() else None}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


class InternetArchive:
    """Internet Archive netlabel releases under CC BY, CC BY-SA or CC0, one track per release.

    The advanced-search API lists items; an item's metadata lists its files. We take the first
    VBR MP3 of at least 90 seconds as the track and the item's page as its landing page. The
    items' own `licenseurl` is the licence; an item without one is skipped. Files redirect to
    numbered archive.org servers, which `catalogue.fetch.ALLOWED_HOSTS` covers by suffix.
    """

    search_url = "https://archive.org/advancedsearch.php"

    def __init__(self, fetch: Fetch | None = None) -> None:
        self.fetch = fetch or http_json

    def search(self, term: str, rows: int = 12, allow_nc: bool = False) -> list[Track]:
        lic = ['licenseurl:"http://creativecommons.org/licenses/by/3.0/"',
               'licenseurl:"http://creativecommons.org/licenses/by/4.0/"',
               'licenseurl:"http://creativecommons.org/licenses/by-sa/3.0/"',
               'licenseurl:"http://creativecommons.org/licenses/by-sa/4.0/"',
               'licenseurl:"http://creativecommons.org/publicdomain/zero/1.0/"']
        q = f'mediatype:audio AND collection:netlabels AND ({" OR ".join(lic)}) AND "{term}"'
        params = urllib.parse.urlencode(
            {"q": q, "fl[]": ["identifier", "title", "creator", "licenseurl", "subject"],
             "sort[]": "downloads desc", "rows": rows, "output": "json"}, doseq=True)
        data = self.fetch(f"{self.search_url}?{params}")
        out = []
        for doc in (data.get("response") or {}).get("docs", []):
            t = self.to_track(doc, allow_nc)
            if t:
                out.append(t)
        return out

    def to_track(self, doc: dict[str, Any], allow_nc: bool = False) -> Track | None:
        lic = parse_url(doc.get("licenseurl"))
        if not accepted(lic, allow_nc):
            return None
        ident = doc["identifier"]
        try:
            meta = self.fetch(f"https://archive.org/metadata/{ident}")
        except Exception:
            return None
        files = [f for f in meta.get("files", []) if f.get("format") in ("VBR MP3", "MP3")]
        files = [f for f in files if _secs(f.get("length")) >= 90.0]
        if not files:
            return None
        f = sorted(files, key=lambda x: x.get("name", ""))[0]
        subj = doc.get("subject") or []
        subj = [subj] if isinstance(subj, str) else subj
        creator = doc.get("creator") or "Unknown artist"
        creator = creator if isinstance(creator, str) else ", ".join(creator)
        title = f.get("title") or doc.get("title") or ident
        return Track(
            id=f"internet_archive:{ident}/{f['name']}", title=str(title).strip(), artist=creator,
            audio_url=f"https://archive.org/download/{ident}/{urllib.parse.quote(f['name'])}",
            landing_url=f"https://archive.org/details/{ident}", licence=lic,
            source="internet_archive", duration_s=round(_secs(f.get("length")), 1),
            artist_url="", album=str(doc.get("title") or ""),
            artwork_url=f"https://archive.org/services/img/{ident}",
            genres=[s.lower() for s in subj][:6], filetype="mp3")


def _secs(v: Any) -> float:
    if v is None:
        return 0.0
    s = str(v)
    if ":" in s:
        parts = [float(p) for p in s.split(":")]
        out = 0.0
        for p in parts:
            out = out * 60 + p
        return out
    try:
        return float(s)
    except ValueError:
        return 0.0
