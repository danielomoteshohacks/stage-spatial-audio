"""Configuration of the SoundStage Separator, shared by training, export and inference."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

STEMS = ("vocals", "drums", "bass", "other")
#: Hugging Face model repository the Kaggle training run pushes to.
WEIGHTS_REPO = "danieltesh/soundstage-separator"


def band_edges(n_fft: int, sample_rate: int) -> list[tuple[int, int]]:
    """Bin ranges of the band split: narrow where pitch lives, wide at the top.

    The widths follow Band-Split RNN's scheme (Luo and Yu 2022): 100 Hz bands up to 1 kHz,
    250 Hz to 4 kHz, 500 Hz to 8 kHz, 1 kHz to 16 kHz, and the rest in one band. Every bin
    belongs to exactly one band.
    """
    hz_per_bin = sample_rate / n_fft
    n_bins = n_fft // 2 + 1
    edges_hz = []
    f = 0.0
    for top, width in ((1000.0, 100.0), (4000.0, 250.0), (8000.0, 500.0), (16000.0, 1000.0)):
        while f < top - 1e-9:
            edges_hz.append(f)
            f += width
    bins = sorted({int(round(e / hz_per_bin)) for e in edges_hz} | {n_bins})
    bins = [b for b in bins if b <= n_bins]
    return [(a, b) for a, b in zip(bins[:-1], bins[1:], strict=True) if b > a]


@dataclass(frozen=True)
class SsepConfig:
    sample_rate: int = 44100
    n_fft: int = 2048
    hop: int = 512
    dim: int = 96
    layers: int = 4
    heads: int = 4
    stems: tuple[str, ...] = STEMS
    wave_channels: tuple[int, ...] = (24, 48, 96)
    #: Training segment (seconds) and the inference chunk with its crossfade overlap.
    segment_s: float = 6.0
    overlap: float = 0.25
    extra: dict = field(default_factory=dict)

    @property
    def n_bins(self) -> int:
        return self.n_fft // 2 + 1

    @property
    def bands(self) -> list[tuple[int, int]]:
        return band_edges(self.n_fft, self.sample_rate)

    def to_json(self) -> str:
        d = asdict(self)
        d["stems"] = list(self.stems)
        d["wave_channels"] = list(self.wave_channels)
        return json.dumps(d, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> SsepConfig:
        d = json.loads(text)
        d["stems"] = tuple(d["stems"])
        d["wave_channels"] = tuple(d["wave_channels"])
        return cls(**d)
