"""The cascade's data: models, presets and the licence policy (configs/cascade/models.json)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stage.config import load_json

#: What each licence class permits in this repository's deployments.
#: open: any use. copyleft: GPL-3.0 weights, fetched at run time on the Space and never
#: redistributed here. nc: non-commercial, allowed for this research demo only, credited.
#: unverified: no licence stated at the source, so off unless the owner enables it.
ALLOWED_DEFAULT = ("open", "copyleft", "nc")


@dataclass(frozen=True)
class ModelSpec:
    id: str
    level: int
    role: str
    family: str
    source: str
    file: str
    size_bytes: int | None
    sha256: str | None
    licence: str
    licence_class: str
    sdr: dict[str, Any]
    stems: tuple[str, ...]
    config: str | None = None
    notes: str = ""


def load() -> dict[str, Any]:
    return load_json("cascade/models.json")


def models() -> dict[str, ModelSpec]:
    out = {}
    for mid, m in load()["models"].items():
        out[mid] = ModelSpec(
            id=mid, level=int(m["level"]), role=m["role"], family=m["family"], source=m["source"],
            file=m["file"], size_bytes=m.get("size_bytes"), sha256=m.get("sha256"),
            licence=m["licence"], licence_class=m["licence_class"], sdr=dict(m.get("sdr", {})),
            stems=tuple(m["stems"]), config=m.get("config"), notes=m.get("notes", ""))
    return out


def preset(name: str) -> dict[str, Any]:
    p = load()["presets"]
    if name not in p:
        raise ValueError(f"unknown preset {name!r}; known: {sorted(p)}")
    return p[name]


def usable(spec: ModelSpec, allowed: tuple[str, ...] = ALLOWED_DEFAULT) -> tuple[bool, str]:
    """(allowed, reason) under a licence policy. The reason is what run.json records."""
    if spec.licence_class in allowed:
        return True, f"{spec.licence} ({spec.licence_class})"
    return False, (f"{spec.id}: licence class {spec.licence_class!r} is not enabled "
                   f"({spec.licence}); enable it only after reading the source")
