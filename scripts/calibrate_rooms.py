"""Compare the synthetic studio with the measured SADIE II studio BRIRs, and every space's RT60.

Usage:
    python scripts/calibrate_rooms.py            # downloads the measured files if needed

Prints, per direction, the direct-to-reverberant ratio, early decay time and early interaural
cross-correlation of the measured KU100 BRIRs next to the synthetic studio's, then the target and
the measured (Schroeder T30) reverberation time of every space per octave. Decision 0013 quotes
this output.
"""

from __future__ import annotations

import numpy as np

from stage.spatial.hrtf import download_brirs, download_pack, get_hrtf
from stage.spatial.room import OCTAVES, brir, get_space, spaces
from stage.spatial.roommetrics import band_rt60, brir_metrics

DIRECTIONS = (0.0, 45.0, 90.0, 135.0, 180.0)


def main() -> None:
    download_pack()
    z = np.load(download_brirs(), allow_pickle=False)
    az, el = z["az_deg"].astype(float), z["el_deg"].astype(float)
    ir = z["ir"].astype(float) * float(z["scale"])
    fs = int(z["sample_rate"])
    hs = get_hrtf(fs)
    studio = get_space("studio")
    print(f"HRTF set: {hs.name}; studio reflection level {studio.reflection_level_db} dB")
    print(f"{'az':>5} | {'DRR meas':>8} {'synth':>6} | {'EDT meas':>8} {'synth':>6} | "
          f"{'IACC_E meas':>11} {'synth':>6}")
    for a in DIRECTIONS:
        i = int(np.argmin(np.abs((az - a + 180.0) % 360.0 - 180.0) + np.abs(el)))
        m = brir_metrics(ir[i], fs)
        s = brir_metrics(brir(studio, hs, a, 0.0, studio.speaker_distance_m).total, fs)
        print(f"{a:5.0f} | {m['drr_db']:8.1f} {s['drr_db']:6.1f} | {m['edt_s']:8.3f} "
              f"{s['edt_s']:6.3f} | {m['iacc_early']:11.2f} {s['iacc_early']:6.2f}")
    print()
    print("space          " + " ".join(f"{int(f):>11}" for f in OCTAVES))
    for name, sp in spaces().items():
        meas = band_rt60(brir(sp, hs, 30.0, 0.0, sp.speaker_distance_m).total, fs)
        cells = [f"{t:.2f}/{meas[str(int(f))]:.2f}" for f, t in zip(OCTAVES, sp.rt60_s,
                                                                    strict=True)]
        print(f"{name:14} " + " ".join(f"{c:>11}" for c in cells))
    print("(target/measured RT60 in seconds)")


if __name__ == "__main__":
    main()
