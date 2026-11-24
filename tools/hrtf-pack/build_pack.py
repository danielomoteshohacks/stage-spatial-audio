"""Build the SoundStage HRTF pack from the SADIE II database (University of York).

Run on a machine with internet access (the GitHub Actions workflow hrtf-pack.yml does this):

    python tools/hrtf-pack/build_pack.py --out dist/hrtf

It downloads subject D1 (the Neumann KU100 dummy head) of SADIE II from its Zenodo record,
refuses to continue unless the record's licence is Apache-2.0, reads the 48 kHz HRIR SOFA file
with h5py, converts every direction into a log magnitude per ear plus an ITD
(stage.spatial.hrtfpack), and writes:

    sadie2-d1-ku100.npz     the pack (float16 magnitudes, about 3 to 5 MB)
    manifest.json           source URL, file names, checksums, licence and attribution
    brir_reference.json     DRR, EDT, IACC and RT60 of any D1 BRIRs in the download (if present)

Every file found in the archive is listed in the manifest, so what was used is on record.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from stage.spatial.hrtfpack import process_hrirs, write_pack  # noqa: E402
from stage.spatial.roommetrics import brir_metrics  # noqa: E402

#: SADIE II Database on Zenodo (Armstrong, Thresh, Murphy and Kearney, University of York).
ZENODO_RECORD = "12092466"
ATTRIBUTION = (
    "SADIE II Database, The Audio Lab, University of York. C. Armstrong, L. Thresh, D. Murphy "
    "and G. Kearney, \"A Perceptual Evaluation of Individual and Non-Individual HRTFs: A Case "
    "Study of the SADIE II Database\", Applied Sciences 8(11), 2029, 2018. Licensed under the "
    "Apache License 2.0."
)
PACK_NAME = "sadie2-d1-ku100.npz"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "soundstage-hrtf-pack/1"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read()


def zenodo_record(record: str) -> dict:
    return json.loads(fetch(f"https://zenodo.org/api/records/{record}"))


def record_licence(rec: dict) -> str:
    lic = rec.get("metadata", {}).get("license") or rec.get("metadata", {}).get("rights") or {}
    if isinstance(lic, list):
        lic = lic[0] if lic else {}
    return str(lic.get("id", lic) if isinstance(lic, dict) else lic).lower()


def pick_d1_archive(files: list[dict]) -> dict:
    """The subject D1 file of the record, or the whole-database archive if D1 is not separate."""
    names = [f["key"] for f in files]
    d1 = [f for f in files if fnmatch.fnmatch(f["key"].lower(), "*d1*")]
    if d1:
        return max(d1, key=lambda f: f.get("size", 0))
    zips = [f for f in files if f["key"].lower().endswith(".zip")]
    if not zips:
        raise SystemExit(f"no D1 file or zip archive in the record; files: {names}")
    return max(zips, key=lambda f: f.get("size", 0))


def open_archive(blob: bytes) -> dict[str, bytes]:
    """Every file in a zip (nested zips are opened too), by path."""
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            data = zf.read(name)
            if name.lower().endswith(".zip"):
                for inner, idata in open_archive(data).items():
                    out[f"{name}/{inner}"] = idata
            else:
                out[name] = data
    return out


def read_sofa(blob: bytes) -> dict:
    """The variables SoundStage needs from a SOFA (netCDF-4 / HDF5) file, via h5py."""
    import h5py

    with h5py.File(io.BytesIO(blob), "r") as f:
        ir = np.asarray(f["Data.IR"], dtype=np.float64)
        fs = float(np.asarray(f["Data.SamplingRate"]).ravel()[0])
        pos = np.asarray(f["SourcePosition"], dtype=np.float64)
        ptype = f["SourcePosition"].attrs.get("Type", b"spherical")
        ptype = ptype.decode() if isinstance(ptype, bytes) else str(ptype)
        attrs = {k: (v.decode(errors="replace") if isinstance(v, bytes) else str(v))
                 for k, v in f.attrs.items()}
    if ptype.lower().startswith("cart"):
        x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
        az = np.degrees(np.arctan2(y, x))
        el = np.degrees(np.arctan2(z, np.hypot(x, y)))
    else:
        az, el = pos[:, 0], pos[:, 1]
    return {"ir": ir, "fs": fs, "az": np.mod(az + 180.0, 360.0) - 180.0, "el": el,
            "attrs": attrs}


def choose_hrir(names: list[str]) -> str:
    """The 48 kHz free-field HRIR SOFA of D1 (not a BRIR, not a headphone response)."""
    sofas = [n for n in names if n.lower().endswith(".sofa")]
    hrir = [n for n in sofas if "brir" not in n.lower() and "hptf" not in n.lower()
            and "hpcf" not in n.lower()]
    for pattern in ("*48k*fir*", "*48k*", "*44k*", "*"):
        hits = sorted(n for n in hrir if fnmatch.fnmatch(Path(n).name.lower(), pattern))
        if hits:
            # Prefer the longest filter of that rate: most of the measured response is kept.
            return max(hits, key=lambda n: ("256" in n, "512" in n, len(n)))
    raise SystemExit(f"no HRIR SOFA among {sofas}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="dist/hrtf")
    ap.add_argument("--record", default=ZENODO_RECORD)
    ap.add_argument("--sofa", help="use a local SOFA file instead of downloading")
    ap.add_argument("--cache", help="folder to keep the downloaded archive in between runs")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"attribution": ATTRIBUTION, "licence": "Apache-2.0"}

    if args.sofa:
        blob = Path(args.sofa).read_bytes()
        files = {Path(args.sofa).name: blob}
        manifest["source"] = {"local_file": Path(args.sofa).name}
    else:
        rec = zenodo_record(args.record)
        licence = record_licence(rec)
        print(f"record {args.record}: {rec.get('metadata', {}).get('title')} "
              f"version {rec.get('metadata', {}).get('version')} licence {licence}")
        if "apache" not in licence:
            raise SystemExit(f"licence is {licence!r}, not Apache-2.0: stopping")
        listing = rec.get("files", [])
        print("record files:", [(f["key"], f.get("size")) for f in listing])
        chosen = pick_d1_archive(listing)
        url = chosen["links"].get("self") or chosen["links"].get("download")
        cached = Path(args.cache) / chosen["key"] if args.cache else None
        if cached is not None and cached.is_file():
            print(f"using the cached {cached}")
            blob = cached.read_bytes()
        else:
            print(f"downloading {chosen['key']} ({chosen.get('size', 0) / 2**20:.0f} MB) "
                  f"from {url}")
            blob = fetch(url)
        md5 = hashlib.md5(blob).hexdigest()
        if chosen.get("checksum", "").startswith("md5:") and chosen["checksum"][4:] != md5:
            raise SystemExit("downloaded file does not match the record's md5")
        if cached is not None and not cached.is_file():
            cached.write_bytes(blob)
        files = open_archive(blob) if chosen["key"].lower().endswith(".zip") else {
            chosen["key"]: blob}
        manifest["source"] = {
            "zenodo_record": args.record, "doi": rec.get("doi"),
            "title": rec.get("metadata", {}).get("title"),
            "version": rec.get("metadata", {}).get("version"),
            "licence_id": licence, "file": chosen["key"], "url": url, "md5": md5,
        }
        files = {k: v for k, v in files.items()
                 if "d1" in k.lower() or chosen["key"].lower().find("d1") >= 0}

    names = sorted(files)
    manifest["archive_files"] = names
    notice = [n for n in names if Path(n).name.lower() in ("license", "license.txt", "notice",
                                                            "notice.txt", "readme.txt")]
    manifest["notice_text"] = {n: files[n].decode(errors="replace")[:20000] for n in notice}

    hrir_name = choose_hrir(names)
    sofa = read_sofa(files[hrir_name])
    print(f"HRIR {hrir_name}: {sofa['ir'].shape} at {sofa['fs']:.0f} Hz")
    ir = sofa["ir"]
    if ir.ndim == 4:  # (M, R, E, N): take the first emitter
        ir = ir[:, :, 0, :]
    pack = process_hrirs(ir, sofa["fs"], sofa["az"], sofa["el"], meta={
        "dataset": "SADIE II", "subject": "D1 (Neumann KU100)", "sofa_file": hrir_name,
        "sofa_attributes": {k: sofa["attrs"][k] for k in sorted(sofa["attrs"])
                            if k in ("Title", "License", "Organization", "AuthorContact",
                                     "DatabaseName", "ListenerShortName", "SOFAConventions",
                                     "DataType", "Comment", "History")},
        "attribution": ATTRIBUTION,
    })
    digest = write_pack(pack, out / PACK_NAME)
    manifest["pack"] = {"file": PACK_NAME, "sha256": digest,
                        "bytes": (out / PACK_NAME).stat().st_size,
                        "directions": pack.n_directions, "bins": int(pack.freqs_hz.size),
                        "sample_rate": sofa["fs"], "sofa_file": hrir_name}
    print(f"pack {PACK_NAME}: {manifest['pack']['bytes'] / 2**20:.2f} MB, sha256 {digest}")

    brirs = [n for n in names if n.lower().endswith(".sofa") and "brir" in n.lower()]
    reference = []
    for name in brirs:
        b = read_sofa(files[name])
        bir = b["ir"][:, :, 0, :] if b["ir"].ndim == 4 else b["ir"]
        front = int(np.argmin(np.abs(b["az"]) + np.abs(b["el"])))
        for idx in sorted({front, int(np.argmin(np.abs(b["az"] - 30) + np.abs(b["el"])))}):
            m = brir_metrics(bir[idx], b["fs"])
            m.update(file=name, az_deg=float(b["az"][idx]), el_deg=float(b["el"][idx]))
            reference.append(m)
    (out / "brir_reference.json").write_text(json.dumps(
        {"brir_files": brirs, "measurements": reference, "attribution": ATTRIBUTION}, indent=2))
    manifest["brir_files"] = brirs
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: v for k, v in manifest.items() if k != "notice_text"}, indent=2))


if __name__ == "__main__":
    main()
