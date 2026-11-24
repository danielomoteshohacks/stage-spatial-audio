"""Where a render puts its energy, and how much of it is direct sound.

Decision 0022. v2 sounded like "stereo pushed backwards"; these measurements say why, and v3 is
judged by them. Everything here reads a plan and the per-object binaural renders (the stems that
sum to the render), never the audio of the whole mix, so the numbers are about what the renderer
did and not about what the song contains.

Directions follow the SOFA convention of the renderer: azimuth in degrees, positive to the LEFT,
0 in front; elevation positive up.

**Direction-energy map.** Each object is a set of *feeds*: the directions it is rendered from,
with the share of the object's energy each carries. The renderer's own geometry gives the feeds
(`feeds_for_plan`): v2 puts every object at az +/- spread / 2 around its template azimuth and
opens ambient objects into a side, rear and height bed; v3 lists each object's feeds in the plan.
An object's *measured* energy (its stem, above the bass crossover, where the render is binaural)
is shared over its feeds, and split into direct and room parts by the energy of the impulse
response the renderer used for that feed (`direct / (direct + early + late)`). The map is the
direct part, summed per direction.

**Sectors.** Front is |az| <= 30 below the height layer; side 30 < |az| <= 110; rear |az| > 110;
height is elevation >= 25 degrees. Four sectors that partition the sphere of directions used.

**Object spread.** Directions are merged when closer than 20 degrees (greedy, heaviest first);
the count of merged directions that carry at least 5 percent of the direct energy is the number
of independent places the listener hears sound from.

**Direct-to-reverberant ratio per object.** From the object's impulse response in the plan's
space: direct energy over early plus late energy, in dB. `measured_drr_db` also fits the response
from a source and its render (Wiener deconvolution) for renders whose source is at hand.

**IACC.** The maximum of the normalised interaural cross-correlation within +/- 1 ms, 500 Hz to
4 kHz (ISO 3382-1 style).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, sosfiltfilt

FRONT_HALF_WIDTH_DEG = 30.0
SIDE_LIMIT_DEG = 110.0
HEIGHT_EL_DEG = 25.0
MERGE_DEG = 20.0
SPREAD_MIN_SHARE = 0.05
#: A direct sound is followed by early reflections up to here and late reverberation after it.
EARLY_LIMIT_S = 0.080


@dataclass(frozen=True)
class Feed:
    """One direction an object is rendered from, with the share of the object's energy."""

    az: float
    el: float
    weight: float
    direct: float = 1.0  # share of this feed's energy that is direct sound, 0 to 1
    early: float = 0.0  # share that is early reflections (under 80 ms); late is the remainder


@dataclass
class DirectionMap:
    az: NDArray[np.float64]
    el: NDArray[np.float64]
    direct: NDArray[np.float64]  # direct energy per feed (arbitrary unit, sums to the total)
    room: NDArray[np.float64]  # early plus late
    late: NDArray[np.float64]
    objects: list[str] = field(default_factory=list)
    owner: list[str] = field(default_factory=list)  # object name per feed


def angular_distance_deg(az1: float, el1: float, az2: float, el2: float) -> float:
    """Great-circle angle between two directions."""
    a1, e1, a2, e2 = (np.radians(v) for v in (az1, el1, az2, el2))
    c = np.sin(e1) * np.sin(e2) + np.cos(e1) * np.cos(e2) * np.cos(a1 - a2)
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def wrap_deg(a: float | NDArray) -> float | NDArray:
    return (np.asarray(a) + 180.0) % 360.0 - 180.0 if isinstance(a, np.ndarray) else (
        (a + 180.0) % 360.0 - 180.0)


def sector_shares(dmap: DirectionMap) -> dict[str, float]:
    """Share of the direct energy in each sector, and the azimuth-only front measure."""
    total = float(dmap.direct.sum())
    if total <= 0.0:
        return {k: 0.0 for k in ("front", "side", "rear", "height", "outside_front_az",
                                 "mean_elevation_deg")}
    az = np.abs(wrap_deg(dmap.az))
    height = dmap.el >= HEIGHT_EL_DEG
    front = (az <= FRONT_HALF_WIDTH_DEG) & ~height
    side = (az > FRONT_HALF_WIDTH_DEG) & (az <= SIDE_LIMIT_DEG) & ~height
    rear = (az > SIDE_LIMIT_DEG) & ~height
    d = dmap.direct
    return {
        "front": float(d[front].sum() / total),
        "side": float(d[side].sum() / total),
        "rear": float(d[rear].sum() / total),
        "height": float(d[height].sum() / total),
        # The brief's "outside the front +/-30 degrees": azimuth only, so a front height object
        # is not counted as moved around the listener.
        "outside_front_az": float(d[az > FRONT_HALF_WIDTH_DEG].sum() / total),
        "mean_elevation_deg": float((d * dmap.el).sum() / total),
    }


def object_spread(dmap: DirectionMap, merge_deg: float = MERGE_DEG,
                  min_share: float = SPREAD_MIN_SHARE) -> int:
    """How many independent directions carry at least `min_share` of the direct energy."""
    total = float(dmap.direct.sum())
    if total <= 0.0:
        return 0
    order = np.argsort(-dmap.direct)
    centres: list[list[float]] = []  # az, el, energy
    for i in order:
        if dmap.direct[i] <= 0.0:
            continue
        for c in centres:
            if angular_distance_deg(c[0], c[1], float(dmap.az[i]), float(dmap.el[i])) < merge_deg:
                c[2] += float(dmap.direct[i])
                break
        else:
            centres.append([float(dmap.az[i]), float(dmap.el[i]), float(dmap.direct[i])])
    return int(sum(1 for c in centres if c[2] / total >= min_share))


def stem_energy(y: NDArray, sample_rate: int, above_hz: float) -> float:
    """Energy of a (2, n) stem above `above_hz` (below it the render is the untouched original)."""
    sos = butter(2, above_hz, btype="highpass", fs=sample_rate, output="sos")
    from scipy.signal import sosfilt

    return float(np.sum(sosfilt(sos, y, axis=-1) ** 2))


def direction_map(plan: dict[str, Any], objects: dict[str, NDArray], sample_rate: int,
                  feeds_fn: Callable[[dict[str, Any], dict[str, Any]], list[Feed]] | None = None,
                  above_hz: float | None = None) -> DirectionMap:
    """The direct and room energy per direction, from the plan and the per-object renders."""
    fn = feeds_fn or feeds_for_object
    above = float(above_hz if above_hz is not None else plan.get("crossover_hz", 120.0))
    az: list[float] = []
    el: list[float] = []
    direct: list[float] = []
    room: list[float] = []
    late: list[float] = []
    owner: list[str] = []
    names: list[str] = []
    by_name = {o["name"]: o for o in plan["stems"]}
    for name, y in objects.items():
        if name not in by_name:
            continue  # "low_end" and other non-object stems
        e = stem_energy(np.asarray(y, dtype=np.float64), sample_rate, above)
        if e <= 0.0:
            continue
        names.append(name)
        for f in fn(by_name[name], plan):
            az.append(f.az)
            el.append(f.el)
            direct.append(e * f.weight * f.direct)
            room.append(e * f.weight * (1.0 - f.direct))
            late.append(e * f.weight * max(1.0 - f.direct - f.early, 0.0))
            owner.append(name)
    return DirectionMap(az=np.array(az), el=np.array(el), direct=np.array(direct),
                        room=np.array(room), late=np.array(late), objects=names, owner=owner)


# --- Feeds of the v2 renderer and of the v3 plan -------------------------------------------------


def _shares(plan: dict[str, Any], az: float, el: float, dist: float, send: float
            ) -> tuple[float, float]:
    """(direct, early) shares of direct + early + late in the plan's space at that position,
    from the same impulse response the renderer convolves with."""
    from stage.scene.render import HOME_LISTENING_M, _brir
    from stage.spatial.room import get_space

    sr = int(plan.get("analysis_sample_rate", 48000))
    space = plan.get("space", "studio")
    room_scale = get_space(space).speaker_distance_m / HOME_LISTENING_M
    b = _brir(space, sr, round(az, 1), round(el, 1), round(dist * room_scale, 2), round(send, 3))
    e_d = float(np.sum(b.direct**2))
    e_e = float(np.sum(b.early**2))
    tot = max(e_d + e_e + float(np.sum(b.late**2)), 1e-30)
    return e_d / tot, e_e / tot


def drr_db_for(plan: dict[str, Any], obj: dict[str, Any]) -> float:
    """Direct-to-reverberant ratio (dB) of an object at its template position."""
    from stage.scene.render import HOME_LISTENING_M, _brir
    from stage.spatial.room import get_space

    sr = int(plan.get("analysis_sample_rate", 48000))
    space = plan.get("space", "studio")
    room_scale = get_space(space).speaker_distance_m / HOME_LISTENING_M
    b = _brir(space, sr, round(float(obj["az"]), 1), round(float(obj["el"]), 1),
              round(float(obj["dist"]) * room_scale, 2), round(float(obj.get("room_send", 0.5)), 3))
    e_d = float(np.sum(b.direct**2))
    e_r = float(np.sum(b.early**2) + np.sum(b.late**2))
    return float(10.0 * np.log10(max(e_d, 1e-30) / max(e_r, 1e-30)))


def _mean_openness(plan: dict[str, Any]) -> float:
    secs = plan.get("sections") or []
    if not secs:
        return 0.5
    dur = sum(max(s["end_s"] - s["start_s"], 0.0) for s in secs) or 1.0
    return float(sum(s["openness"] * (s["end_s"] - s["start_s"]) for s in secs) / dur)


def _mean_wide_weight(plan: dict[str, Any]) -> float:
    """Time-averaged energy weight of the wide setting (sin^2 of the renderer's cross-fade)."""
    secs = plan.get("sections") or []
    if not secs:
        return 0.0
    dur = sum(max(s["end_s"] - s["start_s"], 0.0) for s in secs) or 1.0
    acc = 0.0
    for s in secs:
        w = float(np.clip((s["openness"] - 0.3) / 0.6, 0.0, 1.0))
        acc += np.sin(w * np.pi / 2.0) ** 2 * (s["end_s"] - s["start_s"])
    return float(acc / dur)


def _motion_azimuths(motion: dict[str, Any] | None) -> list[tuple[float, float]]:
    """(offset in degrees, weight) samples of a motion path over one period."""
    if not motion:
        return [(0.0, 1.0)]
    phases = np.arange(16) / 16.0
    if motion["path"] == "orbit":
        offs = 360.0 * phases
    else:
        offs = 0.5 * motion["depth"] * np.sin(2.0 * np.pi * phases)
    return [(float(o), 1.0 / len(offs)) for o in offs]


BED_FRONT_SHARE_V2 = 0.4
_BED_FEEDS_V2 = (("side", 90.0, 0.0), ("rear", 135.0, 0.0), ("height", 45.0, 45.0),
                 ("height", 135.0, 45.0))


def v2_feeds(obj: dict[str, Any], plan: dict[str, Any]) -> list[Feed]:
    """The directions the v2 scene renderer (stage.scene.render) feeds an object from."""
    send = float(obj.get("room_send", 0.5))
    dist = float(obj["dist"])
    part = str(obj.get("source", "mix.direct")).split(".")[-1]
    blend = float(obj.get("orig_blend", 0.0))
    feeds: list[Feed] = []
    openness = _mean_openness(plan)
    bed_cfg = plan.get("bed", {})
    if part == "ambient" and float(obj.get("spread", 0.0)) == 0.0:
        gains = {"side": bed_cfg.get("ambience", 1.0) * (0.6 + 0.8 * openness),
                 "rear": bed_cfg.get("ambience", 1.0) * (0.5 + 0.9 * openness),
                 "height": bed_cfg.get("heights", 0.5) * (0.3 + 1.2 * openness)}
        raw = [(BED_FRONT_SHARE_V2 / 2.0, 30.0, 0.0), (BED_FRONT_SHARE_V2 / 2.0, -30.0, 0.0)]
        rest = (1.0 - BED_FRONT_SHARE_V2) / 4.0 / 2.0
        for sign in (1.0, -1.0):
            for layer, a, e in _BED_FEEDS_V2:
                raw.append((rest * gains[layer] ** 2, sign * a, e))
        total = sum(r[0] for r in raw)
        for w, a, e in raw:
            feeds.append(Feed(a, e, w / total, *_shares(plan, a, e, dist, send)))
    else:
        spread = float(obj.get("spread", 0.0))
        settings = [(spread, float(obj["el"]), 1.0)]
        if obj.get("wide"):
            ww = _mean_wide_weight(plan)
            settings = [(spread, float(obj["el"]), 1.0 - ww),
                        (float(obj["wide"]["spread"]), float(obj["wide"]["el"]), ww)]
        for sp, e, w in settings:
            offsets = [0.0] if sp <= 0.0 else [sp / 2.0, -sp / 2.0]
            for off in offsets:
                for m_off, m_w in _motion_azimuths(obj.get("motion")):
                    a = float(wrap_deg(float(obj["az"]) + off + m_off))
                    feeds.append(Feed(a, e, w * m_w / len(offsets),
                                      *_shares(plan, a, e, dist, send)))
    if blend > 0.0:
        # The original's own stereo, unprocessed: headphone left and right, all direct.
        keep = 1.0 - blend
        feeds = [Feed(f.az, f.el, f.weight * keep, f.direct, f.early) for f in feeds]
        feeds += [Feed(30.0, 0.0, blend / 2.0, 1.0), Feed(-30.0, 0.0, blend / 2.0, 1.0)]
    return feeds


def v3_feeds(obj: dict[str, Any], plan: dict[str, Any]) -> list[Feed]:
    """v3 plans list each object's feeds; the room part comes from the plan's `drr_db`."""
    out = []
    for f in obj["feeds"]:
        out.append(Feed(float(f["az"]), float(f["el"]), float(f["weight"]),
                        float(f.get("direct", 1.0)), float(f.get("early", 0.0))))
    return out


def feeds_for_object(obj: dict[str, Any], plan: dict[str, Any]) -> list[Feed]:
    if int(plan.get("version", 2)) >= 3 and "feeds" in obj:
        return v3_feeds(obj, plan)
    return v2_feeds(obj, plan)


feeds_for_plan = feeds_for_object


# --- Measurements on the audio ------------------------------------------------------------------


def _band(x: NDArray, sr: int, lo: float, hi: float) -> NDArray:
    return sosfiltfilt(butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos"), x, axis=-1)


def iacc(y: NDArray, sr: int) -> float:
    b = _band(np.asarray(y, dtype=np.float64), sr, 500.0, 4000.0)
    n = b.shape[1]
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    xc = np.fft.irfft(np.fft.rfft(b[0], nfft) * np.conj(np.fft.rfft(b[1], nfft)), nfft)
    lag = int(round(0.001 * sr))
    window = np.concatenate([xc[: lag + 1], xc[-lag:]])
    return float(np.max(np.abs(window)) / np.sqrt(np.sum(b[0] ** 2) * np.sum(b[1] ** 2)))


def fit_response(source: NDArray, render: NDArray, n_taps: int) -> NDArray[np.float64]:
    """Least-squares impulse response (2, n_taps) from a mono source to a stereo render, by
    regularised deconvolution in the frequency domain. Lags below zero are discarded."""
    n = source.size
    nfft = 1 << int(np.ceil(np.log2(n + n_taps)))
    s = np.fft.rfft(source, nfft)
    reg = 1e-6 * float(np.max(np.abs(s) ** 2))
    out = np.zeros((2, n_taps))
    for ear in range(2):
        r = np.fft.rfft(render[ear], nfft)
        h = np.fft.irfft(r * np.conj(s) / (np.abs(s) ** 2 + reg), nfft)
        out[ear] = h[:n_taps]
    return out


def measured_drr_db(source: NDArray, render: NDArray, sample_rate: int,
                    direct_window_ms: float = 3.0) -> dict[str, float]:
    """Direct-to-reverberant ratio and the late-energy share, fitted from a source and its render.

    The direct part is the response within `direct_window_ms` of its strongest peak; early is the
    rest up to 80 ms after the peak; late is everything beyond.
    """
    n_taps = int(0.8 * sample_rate)
    h = fit_response(np.asarray(source, dtype=np.float64), np.asarray(render, dtype=np.float64),
                     n_taps)
    p = (h**2).sum(axis=0)
    peak = int(np.argmax(p))
    w = int(direct_window_ms * 1e-3 * sample_rate)
    d = float(p[max(0, peak - w) : peak + w].sum())
    early_end = peak + int(EARLY_LIMIT_S * sample_rate)
    early = float(p[peak + w : early_end].sum())
    late = float(p[early_end:].sum())
    tot = max(d + early + late, 1e-30)
    return {"drr_db": float(10 * np.log10(max(d, 1e-30) / max(early + late, 1e-30))),
            "late_share": late / tot, "direct_share": d / tot}


def diagnose(plan: dict[str, Any], objects: dict[str, NDArray], render: NDArray | None,
             sample_rate: int, sources: dict[str, NDArray] | None = None) -> dict[str, Any]:
    """Everything the brief asks for, as one JSON-ready dict."""
    dmap = direction_map(plan, objects, sample_rate)
    shares = sector_shares(dmap)
    by_name = {o["name"]: o for o in plan["stems"]}
    per_object: dict[str, dict[str, float]] = {}
    tot_obj = 0.0
    late_energy = 0.0
    room_energy = 0.0
    for name in dmap.objects:
        obj = by_name[name]
        idx = [i for i, o in enumerate(dmap.owner) if o == name]
        d = float(dmap.direct[idx].sum())
        r = float(dmap.room[idx].sum())
        tot_obj += d + r
        row = {"energy_share_direct": 0.0, "drr_db": float(10 * np.log10(max(d, 1e-30)
                                                                          / max(r, 1e-30)))}
        if int(plan.get("version", 2)) < 3:
            row["drr_template_db"] = drr_db_for(plan, obj)
        per_object[name] = row
        room_energy += r
        late_energy += float(dmap.late[idx].sum())
        if sources and name in sources:
            row.update({f"fit_{k}": v for k, v in measured_drr_db(
                np.asarray(sources[name]).mean(axis=0), objects[name], sample_rate).items()})
    for name, row in per_object.items():
        idx = [i for i, o in enumerate(dmap.owner) if o == name]
        row["energy_share_direct"] = float(dmap.direct[idx].sum() / max(dmap.direct.sum(), 1e-30))
    out: dict[str, Any] = {
        "engine": plan.get("engine", "unknown"),
        "space": plan.get("space"),
        "sectors": {k: round(v, 4) for k, v in shares.items()},
        "object_spread": object_spread(dmap),
        "direct_energy_share": round(float(dmap.direct.sum() / max(tot_obj, 1e-30)), 4),
        "room_energy_share": round(float(room_energy / max(tot_obj, 1e-30)), 4),
        "late_energy_share": round(float(late_energy / max(tot_obj, 1e-30)), 4),
        "per_object": {k: {a: round(b, 4) for a, b in v.items()} for k, v in per_object.items()},
        "drr_db_median": round(float(np.median([v["drr_db"] for v in per_object.values()]))
                               if per_object else 0.0, 2),
        "map": {"az": [round(float(a), 1) for a in dmap.az],
                "el": [round(float(e), 1) for e in dmap.el],
                "direct": [float(d) for d in dmap.direct], "object": dmap.owner},
    }
    if render is not None:
        out["iacc"] = round(iacc(render, sample_rate), 3)
    return out
