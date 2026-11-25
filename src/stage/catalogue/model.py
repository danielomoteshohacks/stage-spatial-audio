"""A catalogue track: what the browser shows and the renderer needs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from stage.catalogue.licences import Licence, attribution


@dataclass
class Track:
    id: str  # "<source>:<identifier>", stable across runs
    title: str
    artist: str
    audio_url: str
    landing_url: str
    licence: Licence
    source: str  # jamendo, wikimedia_audio, freesound, internet_archive, ...
    duration_s: float = 0.0
    artist_url: str = ""
    album: str = ""
    artwork_url: str = ""
    genres: list[str] = field(default_factory=list)
    filetype: str = ""
    shelves: list[str] = field(default_factory=list)
    checked: dict[str, Any] = field(default_factory=dict)  # result of the audio URL check

    @property
    def attribution(self) -> str:
        return attribution(self.title, self.artist, self.licence, self.landing_url)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["licence"] = self.licence.as_dict()
        d["attribution"] = self.attribution
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Track:
        lic = d["licence"]
        return Track(
            id=d["id"], title=d["title"], artist=d["artist"], audio_url=d["audio_url"],
            landing_url=d["landing_url"], licence=Licence(lic["code"], lic.get("version", "")),
            source=d["source"], duration_s=float(d.get("duration_s", 0.0)),
            artist_url=d.get("artist_url", ""), album=d.get("album", ""),
            artwork_url=d.get("artwork_url", ""), genres=list(d.get("genres", [])),
            filetype=d.get("filetype", ""), shelves=list(d.get("shelves", [])),
            checked=dict(d.get("checked", {})))
