"""Show what the stereo analysis finds in a real audio clip.

Usage:
    python scripts/analyze_clip.py path/to/clip.wav [--start 30] [--seconds 15] [--plot out.png]

Prints the share of the signal that the model explains as an amplitude-panned primary sound,
and where that primary energy sits across thirteen 5-degree sectors of the stereo image
(the sectors the renderer will use later). Use only audio you own or may use.
"""

from __future__ import annotations

import argparse

import numpy as np

from stage.analysis import analyse_stereo, stft
from stage.io import read_audio, to_stereo

N_FFT = 2048
HOP = 1024
SECTOR_CENTRES = np.arange(-6, 7) * 5.0  # -30 ... +30 degrees


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("path")
    parser.add_argument("--start", type=float, default=0.0, help="start time in seconds")
    parser.add_argument("--seconds", type=float, default=15.0, help="length to analyse")
    parser.add_argument("--plot", help="optional PNG output (needs matplotlib)")
    args = parser.parse_args()

    audio, sample_rate = read_audio(args.path, start_s=args.start, duration_s=args.seconds)
    audio = to_stereo(audio)
    spec = stft(audio, n_fft=N_FFT, hop=HOP)
    res = analyse_stereo(spec[0], spec[1], hop=HOP, sample_rate=sample_rate)

    power_primary = np.sum(np.abs(res.primary) ** 2, axis=0)
    power_ambient = np.sum(np.abs(res.ambient) ** 2, axis=0)
    total = power_primary.sum() + power_ambient.sum()
    if total == 0:
        raise SystemExit("The clip is silent.")

    print(f"clip: {audio.shape[1] / sample_rate:.1f} s at {sample_rate} Hz")
    print(f"primary energy:  {100 * power_primary.sum() / total:5.1f} %")
    print(f"ambient energy:  {100 * power_ambient.sum() / total:5.1f} %")
    print(f"mean in-phase coherence (energy weighted): "
          f"{np.average(res.inphase_coherence, weights=power_primary + power_ambient):.2f}")

    edges = np.append(SECTOR_CENTRES - 2.5, SECTOR_CENTRES[-1] + 2.5)
    hist, _ = np.histogram(res.angle_deg, bins=edges, weights=power_primary)
    hist = hist / hist.sum() if hist.sum() > 0 else hist
    print("\nprimary energy by stereo angle (left to right):")
    for centre, share in zip(SECTOR_CENTRES, hist, strict=True):
        bar = "#" * int(round(share * 60))
        print(f"{centre:+5.0f} deg  {100 * share:5.1f} %  {bar}")

    if args.plot:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            msg = "Plotting needs matplotlib: python -m pip install matplotlib"
            raise SystemExit(msg) from None
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.bar(SECTOR_CENTRES, 100 * hist, width=4.2)
        ax.set_xlabel("stereo angle (degrees, negative is left)")
        ax.set_ylabel("share of primary energy (%)")
        fig.tight_layout()
        fig.savefig(args.plot, dpi=150)
        print(f"\nsaved {args.plot}")


if __name__ == "__main__":
    main()
