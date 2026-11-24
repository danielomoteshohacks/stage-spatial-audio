"""Four-stem separation with Demucs (htdemucs by default), written against the demucs 4 Python API.

torch and demucs are imported inside `separate`, so the rest of SoundStage (Lite rendering, the
service, the tests) installs and runs without them. Install them with the `separation` extra.

The helpers below the entry point are plain numpy so the length and residual bookkeeping is
tested without the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

#: The stems every separator in SoundStage returns, in this order.
STEM_NAMES = ("vocals", "drums", "bass", "other")


class SeparationUnavailable(RuntimeError):
    """Raised when the separation dependencies (torch, demucs) or the model cannot be loaded."""


@dataclass
class Separation:
    """Stems at the input's sample rate and exact length; each is (2, n) float64."""

    stems: dict[str, NDArray[np.float64]]
    sample_rate: int
    residual_snr_db: float
    model: str = "unknown"
    device: str = "cpu"
    notes: list[str] = field(default_factory=list)
    #: The fallback chain's attempts (stage.separation.chain), and engine-specific measurements
    #: such as the separator's per-stem leakage estimates.
    chain: list[dict] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def fit_length(x: NDArray[np.float64], n: int) -> NDArray[np.float64]:
    """Trim or zero-pad the last axis to exactly `n` samples.

    Resampling to the model rate and back can be off by a few samples; the pipeline promises
    outputs of exactly the input's length, so the difference is removed here.
    """
    if x.shape[-1] >= n:
        return x[..., :n]
    pad = [(0, 0)] * (x.ndim - 1) + [(0, n - x.shape[-1])]
    return np.pad(x, pad)


def residual_snr_db(mix: NDArray[np.float64], stems: dict[str, NDArray[np.float64]]) -> float:
    """Input energy over the energy of (input - sum of stems), in dB.

    High means the stems add back up to the mix, so a spatial render of the stems can stay true
    to the record. A perfect split gives +inf.
    """
    total = np.sum(list(stems.values()), axis=0)
    signal = float(np.sum(np.square(mix)))
    residual = float(np.sum(np.square(mix - total)))
    if residual == 0.0:
        return float("inf")
    if signal == 0.0:
        return float("-inf")
    return 10.0 * float(np.log10(signal / residual))


def pick_device(device: str, cuda_available: bool) -> str:
    """Resolve "auto" to "cuda" when a GPU is visible, otherwise "cpu"."""
    if device == "auto":
        return "cuda" if cuda_available else "cpu"
    if device not in ("cpu", "cuda") and not device.startswith("cuda:"):
        raise ValueError(f"device must be 'auto', 'cpu' or 'cuda[:n]', got {device!r}")
    return device


def check_input(audio: NDArray[np.float64]) -> NDArray[np.float64]:
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 2 or audio.shape[0] != 2:
        raise ValueError(f"expected stereo audio of shape (2, samples), got {audio.shape}")
    if audio.shape[1] == 0:
        raise ValueError("cannot separate empty audio")
    return audio


def separate(
    audio: NDArray[np.float64],
    sample_rate: int,
    model: str = "htdemucs",
    device: str = "auto",
) -> Separation:
    """Split stereo audio (2, n) into vocals, drums, bass and other with a pretrained Demucs model.

    Raises SeparationUnavailable if torch or demucs is not installed, or the model cannot be
    loaded (for example, no network to fetch the weights on first use).
    """
    audio = check_input(audio)
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.audio import convert_audio
        from demucs.pretrained import get_model
    except ImportError as exc:
        raise SeparationUnavailable(
            "Stem separation needs torch and demucs, which are not installed. "
            'Install them with: python -m pip install -e ".[separation]"'
        ) from exc

    try:
        net = get_model(model)
    except Exception as exc:  # demucs raises its own ModelLoadingError, and network errors
        raise SeparationUnavailable(f"could not load Demucs model {model!r}: {exc}") from exc
    net.eval()
    dev = pick_device(device, torch.cuda.is_available())
    n = audio.shape[1]

    wav = torch.from_numpy(audio.astype(np.float32))
    wav = convert_audio(wav, sample_rate, net.samplerate, net.audio_channels)
    # The normalisation used by the demucs command line: the models were trained on
    # standardised mixtures, and the stems are scaled back afterwards.
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std()
    scale = std if float(std) > 0 else torch.tensor(1.0)
    with torch.no_grad():
        out = apply_model(
            net, ((wav - mean) / scale)[None], device=dev, shifts=1, split=True, overlap=0.25,
            progress=False,
        )[0]
    out = out * scale + mean

    stems: dict[str, NDArray[np.float64]] = {}
    for i, name in enumerate(net.sources):
        back = convert_audio(out[i].cpu(), net.samplerate, sample_rate, 2)
        stems[name] = fit_length(back.numpy().astype(np.float64), n)
    missing = [s for s in STEM_NAMES if s not in stems]
    if missing:
        raise SeparationUnavailable(f"model {model!r} has no {', '.join(missing)} stem")
    extra = sorted(set(stems) - set(STEM_NAMES))
    # Six-source models (htdemucs_6s) add guitar and piano; folding them into "other" keeps the
    # four stems summing to the mix, which the fidelity of the stems render depends on.
    for name in extra:
        stems["other"] = stems["other"] + stems.pop(name)
    notes = [f"folded {', '.join(extra)} into other"] if extra else []
    stems = {name: stems[name] for name in STEM_NAMES}
    return Separation(
        stems=stems, sample_rate=int(sample_rate), residual_snr_db=residual_snr_db(audio, stems),
        model=model, device=dev, notes=notes,
    )
