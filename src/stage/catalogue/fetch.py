"""Fetch a catalogue track's audio on the server, for playback proxying and for rendering."""

from __future__ import annotations

import urllib.request
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

from stage.catalogue.model import Track
from stage.catalogue.sources import UA

MAX_BYTES = 80 * 1024 * 1024
#: Hosts the catalogue's sources serve audio from. A track's URL is only fetched when it came
#: from a source this process queried, and its host must also be one of these (or a subdomain of
#: archive.org, whose files redirect to numbered servers).
ALLOWED_HOSTS = ("jamendo.com", "wikimedia.org", "freesound.org", "archive.org", "ccmixter.org",
                 "freemusicarchive.org")


class FetchRefused(ValueError):
    pass


def host_allowed(url: str) -> bool:
    u = urlparse(url)
    h = (u.hostname or "").lower()
    return u.scheme == "https" and any(h == d or h.endswith("." + d) for d in ALLOWED_HOSTS)


def open_stream(track: Track, range_header: str | None = None, timeout: float = 30.0):
    if not host_allowed(track.audio_url):
        raise FetchRefused(f"the host of {track.audio_url!r} is not an approved audio source")
    headers = {"User-Agent": UA}
    if range_header:
        headers["Range"] = range_header
    return urllib.request.urlopen(urllib.request.Request(track.audio_url, headers=headers),
                                  timeout=timeout)


def iter_stream(resp, chunk: int = 1 << 16) -> Iterator[bytes]:
    try:
        while data := resp.read(chunk):
            yield data
    finally:
        resp.close()


def download(track: Track, dest: Path, max_bytes: int = MAX_BYTES) -> Path:
    """Download the whole track to `dest` (suffix taken from the URL or the file type)."""
    resp = open_stream(track)
    total = 0
    with open(dest, "wb") as fh:
        for part in iter_stream(resp):
            total += len(part)
            if total > max_bytes:
                dest.unlink(missing_ok=True)
                raise FetchRefused(f"the track is larger than {max_bytes // 2**20} MB")
            fh.write(part)
    return dest


def suffix_for(track: Track) -> str:
    ft = (track.filetype or "").lower()
    if ft.startswith("mp3") or ft.startswith("mp32") or "jamendo" in track.audio_url:
        return ".mp3"
    for ext in (".ogg", ".flac", ".wav", ".mp3", ".m4a", ".opus"):
        if track.audio_url.lower().split("?")[0].endswith(ext):
            return ext
    return ".mp3"
