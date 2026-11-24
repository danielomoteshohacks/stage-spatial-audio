"""The HRTF pack: minimum phase, ITD by onset, quadrature weights, the builder on a SOFA file."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from stage.spatial.hrtfpack import (
    area_weights,
    minimum_phase_from_logmag,
    onset_s,
    process_hrirs,
    read_pack,
    unit_vectors,
    write_pack,
)
from stage.spatial.roommetrics import brir_metrics, rt60

ROOT = Path(__file__).resolve().parents[2]
FS = 48000


def _grid(step=15):
    az, el = [], []
    for e in range(-60, 91, step):
        n = max(1, int(round(360 / step * np.cos(np.radians(e)))))
        for a in np.linspace(-180, 180, n, endpoint=False):
            az.append(a)
            el.append(e)
    return np.array(az, float), np.array(el, float)


def _toy_hrirs(az, el, n=256):
    """Delayed band-limited impulses with a level difference: a known ITD for every direction."""
    ir = np.zeros((az.size, 2, n))
    lat = np.sin(np.radians(az)) * np.cos(np.radians(el))  # +1 hard left (SOFA azimuth)
    itd = 0.0875 / 343.0 * (lat + np.arcsin(lat))
    k = np.arange(n)
    for i in range(az.size):
        tl = 20 + max(0.0, -itd[i]) * FS
        tr = 20 + max(0.0, itd[i]) * FS
        ir[i, 0] = (1 + 0.5 * lat[i]) * np.sinc(k - tl) * np.hanning(n)
        ir[i, 1] = (1 - 0.5 * lat[i]) * np.sinc(k - tr) * np.hanning(n)
    return ir, itd


def test_minimum_phase_keeps_the_magnitude_and_is_causal_and_front_loaded():
    rng = np.random.default_rng(0)
    h = rng.standard_normal(128) * np.exp(-np.arange(128) / 20)
    mag = 20 * np.log10(np.abs(np.fft.rfft(h, 1024)))
    m = minimum_phase_from_logmag(mag, 1024)
    assert np.allclose(20 * np.log10(np.abs(np.fft.rfft(m))), mag, atol=1e-6)
    # Minimum phase has the fastest energy build-up of all filters with that magnitude.
    assert np.all(np.cumsum(m**2)[:128] >= np.cumsum(np.pad(h, (0, 896)) ** 2)[:128] - 1e-4)


def test_onset_itd_recovers_the_true_delay_within_20_microseconds():
    az, el = _grid()
    ir, itd = _toy_hrirs(az, el)
    onsets = onset_s(ir, FS)
    est = onsets[:, 1] - onsets[:, 0]
    assert np.max(np.abs(est - itd)) < 20e-6


def test_area_weights_sum_to_one_and_favour_sparse_regions():
    az, el = _grid()
    w = area_weights(az, el)
    assert w.sum() == pytest.approx(1.0)
    # A weighted mean of the unit vectors of a closed grid is near the origin, the plain mean
    # is pulled toward the denser hemisphere.
    v = unit_vectors(az, el)
    assert np.linalg.norm((w[:, None] * v).sum(0)) < np.linalg.norm(v.mean(0))


def test_pack_round_trip_and_size(tmp_path):
    az, el = _grid()
    ir, itd = _toy_hrirs(az, el)
    pack = process_hrirs(ir, FS, az, el, meta={"dataset": "toy"})
    digest = write_pack(pack, tmp_path / "p.npz")
    back = read_pack(tmp_path / "p.npz")
    assert len(digest) == 64 and back.meta["dataset"] == "toy"
    assert np.allclose(back.logmag_db, pack.logmag_db, atol=0.05)  # float16 resolution
    assert np.allclose(back.itd_s, pack.itd_s, atol=1e-7)
    assert back.df_coherence.shape == back.freqs_hz.shape
    # Coherence of a head: high at low frequencies, falling with frequency.
    assert back.df_coherence[1] > 0.8 and back.df_coherence[1] > back.df_coherence[20]


def test_builder_reads_a_sofa_file(tmp_path):
    h5py = pytest.importorskip("h5py")
    az, el = _grid()
    ir, _ = _toy_hrirs(az, el)
    sofa = tmp_path / "D1_48K_24bit_256tap_FIR_SOFA.sofa"
    with h5py.File(sofa, "w") as f:
        f.attrs["SOFAConventions"] = b"SimpleFreeFieldHRIR"
        f["Data.IR"] = ir
        f["Data.SamplingRate"] = np.array([FS])
        d = f.create_dataset("SourcePosition", data=np.stack([az % 360, el, np.ones_like(az)], 1))
        d.attrs["Type"] = b"spherical"
    out = tmp_path / "out"
    subprocess.run([sys.executable, str(ROOT / "tools" / "hrtf-pack" / "build_pack.py"),
                    "--sofa", str(sofa), "--out", str(out)], check=True, capture_output=True)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["licence"] == "Apache-2.0" and "University of York" in manifest["attribution"]
    pack = read_pack(out / manifest["pack"]["file"])
    assert pack.n_directions == az.size
    assert pack.az_deg.min() >= -180 and pack.az_deg.max() < 180


def test_builder_picks_the_48k_hrir_not_a_brir():
    spec = importlib.util.spec_from_file_location("build_pack",
                                                  ROOT / "tools" / "hrtf-pack" / "build_pack.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    names = ["D1/D1_BRIR_SOFA/D1_48K_BRIR.sofa",
             "D1/D1_HRIR_SOFA/D1_44K_16bit_256tap_FIR_SOFA.sofa",
             "D1/D1_HRIR_SOFA/D1_48K_24bit_256tap_FIR_SOFA.sofa", "D1/D1_HRIR_SOFA/D1_96K.sofa"]
    assert mod.choose_hrir(names).endswith("D1_48K_24bit_256tap_FIR_SOFA.sofa")


def test_room_metrics_of_an_exponential_decay():
    rng = np.random.default_rng(1)
    t = np.arange(int(1.5 * FS)) / FS
    decay = np.exp(-6.91 * t / 0.8)  # 60 dB in 0.8 s
    ir = np.stack([rng.standard_normal(t.size), rng.standard_normal(t.size)]) * decay
    ir[:, 0] = 30.0  # a strong direct sound
    assert rt60(ir[0], FS) == pytest.approx(0.8, rel=0.05)
    m = brir_metrics(ir, FS)
    assert m["iacc_late"] < 0.2  # independent noise in the two ears
    assert m["rt60_s"]["1000"] == pytest.approx(0.8, rel=0.1)
