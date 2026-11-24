"""Training losses: waveform L1, multi-resolution STFT, and distillation toward the teacher.

* Waveform L1 is Demucs' loss: it keeps phase and transients honest.
* Multi-resolution STFT (spectral convergence plus log-magnitude L1 at 512, 1024 and 2048 points,
  Yamamoto et al. 2020, "Parallel WaveGAN", ICASSP) penalises errors in several time-frequency
  trade-offs, where a single resolution would let either pre-echo or smeared harmonics through.
* Distillation is the same two terms against the teacher's stems, weighted by `distill`: on
  MUSDB18-HQ the ground truth leads and the teacher adds its knowledge; on extra music only the
  teacher's stems exist.
"""

from __future__ import annotations

import torch

RESOLUTIONS = ((512, 128), (1024, 256), (2048, 512))


def _mag(x: torch.Tensor, n_fft: int, hop: int) -> torch.Tensor:
    win = torch.hann_window(n_fft, device=x.device, dtype=x.dtype)
    spec = torch.stft(x.reshape(-1, x.shape[-1]), n_fft, hop, window=win, return_complex=True)
    return spec.abs().clamp_min(1e-7)


def multires_stft(est: torch.Tensor, ref: torch.Tensor) -> torch.Tensor:
    loss = est.new_zeros(())
    for n_fft, hop in RESOLUTIONS:
        e, r = _mag(est, n_fft, hop), _mag(ref, n_fft, hop)
        sc = torch.linalg.norm(r - e) / torch.linalg.norm(r).clamp_min(1e-7)
        loss = loss + sc + torch.mean(torch.abs(torch.log(e) - torch.log(r)))
    return loss / len(RESOLUTIONS)


def separation_loss(est: torch.Tensor, ref: torch.Tensor | None, teacher: torch.Tensor | None,
                    distill: float = 0.5, stft_weight: float = 1.0) -> torch.Tensor:
    """est, ref, teacher: (B, S, 2, n). Either reference may be missing, not both."""
    if ref is None and teacher is None:
        raise ValueError("need ground truth, teacher stems, or both")
    loss = est.new_zeros(())
    if ref is not None:
        loss = loss + torch.mean(torch.abs(est - ref)) + stft_weight * multires_stft(est, ref)
    if teacher is not None:
        w = distill if ref is not None else 1.0
        loss = loss + w * (torch.mean(torch.abs(est - teacher))
                           + stft_weight * multires_stft(est, teacher))
    return loss


def sdr_db(est: torch.Tensor, ref: torch.Tensor) -> torch.Tensor:
    """Signal-to-distortion ratio per stem, 10 log10(|s|^2 / |s - s_hat|^2), averaged over a batch.

    The "new SDR" of the music demixing challenges (no projection, no time windows); museval's
    BSSEval v4 numbers come from scripts/eval_separation.py.
    """
    num = ref.pow(2).sum(dim=(-1, -2))
    den = (ref - est).pow(2).sum(dim=(-1, -2)).clamp_min(1e-10)
    return (10.0 * torch.log10(num.clamp_min(1e-10) / den)).mean(dim=0)
