"""Which licences let a track into the catalogue.

Spatialising a recording is an adaptation: the render is a derivative work. So a track is listed
only when its licence allows adaptation, and never when it carries a NoDerivatives term (CC BY-ND,
CC BY-NC-ND). The default policy also leaves out NonCommercial licences, so the catalogue stays
usable by anyone running this project, not only by a non-commercial demo; `allow_nc=True` admits
BY-NC and BY-NC-SA (the demo's own use is non-commercial) and the credits then say so.

What each accepted licence asks of the render (shown on the track and in the dataset record):

* CC0 and Public Domain Mark: nothing; credit is given anyway.
* CC BY: credit the creator, link the licence, say it was changed.
* CC BY-SA: as BY, and the render is shared under the same licence (BY-SA).
* CC BY-NC, CC BY-NC-SA (only with `allow_nc`): as above, and not for commercial use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ACCEPT = {"cc0", "pdm", "by", "by-sa"}
ACCEPT_NC = {"by-nc", "by-nc-sa"}
LABELS = {"cc0": "CC0 1.0", "pdm": "Public Domain Mark 1.0", "by": "CC BY",
          "by-sa": "CC BY-SA", "by-nc": "CC BY-NC", "by-nc-sa": "CC BY-NC-SA"}


@dataclass(frozen=True)
class Licence:
    code: str  # by, by-sa, by-nc, by-nc-sa, by-nd, by-nc-nd, cc0, pdm, or "unknown"
    version: str = ""

    @property
    def url(self) -> str:
        if self.code == "cc0":
            return "https://creativecommons.org/publicdomain/zero/1.0/"
        if self.code == "pdm":
            return "https://creativecommons.org/publicdomain/mark/1.0/"
        if self.code == "unknown":
            return ""
        return f"https://creativecommons.org/licenses/{self.code}/{self.version or '4.0'}/"

    @property
    def label(self) -> str:
        base = LABELS.get(self.code, self.code.upper())
        return f"{base} {self.version}".strip() if self.code not in ("cc0", "pdm") else base

    @property
    def share_alike(self) -> bool:
        return self.code.endswith("-sa")

    def allows_adaptation(self) -> bool:
        return "nd" not in self.code.split("-") and self.code != "unknown"

    def as_dict(self) -> dict:
        return {"code": self.code, "version": self.version, "label": self.label, "url": self.url,
                "share_alike": self.share_alike}


def parse_url(url: str | None) -> Licence:
    """A Creative Commons licence from its URL (Jamendo's `license_ccurl`, a record's link)."""
    if not url:
        return Licence("unknown")
    m = re.search(r"creativecommons\.org/licenses/([a-z\-]+)/([0-9.]+)", url)
    if m:
        return Licence(m.group(1), m.group(2))
    if "publicdomain/zero" in url:
        return Licence("cc0", "1.0")
    if "publicdomain/mark" in url:
        return Licence("pdm", "1.0")
    return Licence("unknown")


def from_openverse(code: str | None, version: str | None) -> Licence:
    code = (code or "").lower()
    if code in ("cc0", "pdm"):
        return Licence(code, version or "1.0")
    return Licence(code or "unknown", version or "") if code else Licence("unknown")


def accepted(lic: Licence, allow_nc: bool = False) -> bool:
    if not lic.allows_adaptation():
        return False
    return lic.code in ACCEPT or (allow_nc and lic.code in ACCEPT_NC)


def attribution(title: str, artist: str, lic: Licence, source_url: str,
                changed: bool = True) -> str:
    """The credit line the licences ask for (title, creator, source, licence, and a change note)."""
    line = f"\"{title}\" by {artist}"
    if source_url:
        line += f" ({source_url})"
    if lic.code in ("cc0", "pdm"):
        line += f", {lic.label}"
    else:
        line += f", licensed under {lic.label} ({lic.url})"
    if changed:
        line += ". Spatialised by SoundStage: the audio was processed into an object-based "
        line += "binaural mix"
        line += ", shared under the same licence." if lic.share_alike else "."
    return line
