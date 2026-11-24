"""The SoundStage Separator network (PyTorch). Training and ONNX export only; needs torch.

Inputs and outputs are chosen so the whole graph exports to ONNX with plain operators:

    spec  (B, 4, F, T)  real and imaginary parts of the left and right STFT, in that order
    wave  (B, 2, N)     the same excerpt as a waveform, N = (T - 1) * hop
    ->
    mask  (B, S, 4, F, T)  complex masks per stem and channel (re, im for left, then right)
    resid (B, S, 2, N)     waveform-branch correction per stem

A stem is then istft(mask * X) + resid. The STFT itself stays outside the graph (numpy at
inference, `torch_stft` in training), matching `stage.analysis.stft` exactly.

Architecture (decision 0015, docs/research/separation.md):

1. Front end: per-bin features computed from the spectrum inside the graph. Log magnitudes, the
   normalised complex spectra, interaural phase (as cosine and sine, no atan2), level
   difference, time-smoothed inter-channel coherence, the Avendano-Jot panning index, a soft
   harmonic/percussive ratio (time-smoothed against frequency-smoothed magnitude, after
   Fitzgerald 2010, with mean filters instead of medians so the graph stays exportable), and an
   f0 salience map by harmonic summation.
2. Band split: each band's bins and features projected to `dim` (Band-Split RNN).
3. Core: alternating sequence models, a bidirectional LSTM across time within each band and a
   transformer layer across bands within each frame (BS-RNN / BS-RoFormer pattern).
4. Mask heads per band: an MLP to complex masks for every stem and channel.
5. Waveform branch: a three-level 1-D convolutional U-Net with skip connections (Demucs), whose
   output is added in the time domain (Hybrid Demucs).
"""

from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F

from stage.separation.ssep.config import SsepConfig

EPS = 1e-6
N_FEATURES = 13


def sqrt_hann(n_fft: int, device=None, dtype=torch.float32) -> torch.Tensor:
    n = torch.arange(n_fft, device=device, dtype=dtype)
    return torch.sqrt(0.5 - 0.5 * torch.cos(2.0 * math.pi * n / n_fft))


def _layout(n_samples: int, n_fft: int, hop: int) -> tuple[int, int, int]:
    left = n_fft - hop
    total = left + n_samples + (n_fft - hop)
    n_frames = max(1, -(-(total - n_fft) // hop) + 1)
    needed = (n_frames - 1) * hop + n_fft
    return left, needed - left - n_samples, n_frames


def torch_stft(x: torch.Tensor, n_fft: int, hop: int) -> torch.Tensor:
    """(..., n) real -> (..., T, F) complex, identical to stage.analysis.stft.stft."""
    left, right, _ = _layout(x.shape[-1], n_fft, hop)
    pad = F.pad(x, (left, right))
    frames = pad.unfold(-1, n_fft, hop)
    return torch.fft.rfft(frames * sqrt_hann(n_fft, x.device, x.dtype), dim=-1)


def torch_istft(spec: torch.Tensor, n_samples: int, n_fft: int, hop: int) -> torch.Tensor:
    """Inverse of `torch_stft`: (C, T, F) complex -> (C, n), overlap-add over window energy."""
    lead = spec.shape[:-2]
    t = spec.shape[-2]
    win = sqrt_hann(n_fft, spec.device, spec.real.dtype)
    frames = torch.fft.irfft(spec, n=n_fft, dim=-1) * win  # (..., T, n_fft)
    frames = frames.reshape(-1, t, n_fft).transpose(1, 2)  # (C, n_fft, T)
    length = (t - 1) * hop + n_fft
    out = F.fold(frames, output_size=(1, length), kernel_size=(1, n_fft), stride=(1, hop))
    norm = F.fold((win**2).reshape(1, n_fft, 1).expand(1, n_fft, t), output_size=(1, length),
                  kernel_size=(1, n_fft), stride=(1, hop))
    left = n_fft - hop
    out = out[..., 0, left : left + n_samples] / norm[..., 0, left : left + n_samples].clamp_min(
        1e-12)
    return out.reshape(*lead, n_samples)


class Features(nn.Module):
    """Per-bin spatial, harmonic/percussive and pitch features of a stereo spectrum."""

    def __init__(self, n_bins: int, smooth: int = 9, hpss: int = 17, harmonics: int = 5) -> None:
        super().__init__()
        self.smooth = smooth
        self.hpss = hpss
        idx = torch.arange(n_bins)
        gather = torch.stack([(idx * h).clamp(max=n_bins - 1) for h in range(1, harmonics + 1)])
        weight = torch.stack([((idx * h) < n_bins).float() * 0.8 ** (h - 1)
                              for h in range(1, harmonics + 1)])
        self.register_buffer("harm_idx", gather, persistent=False)
        self.register_buffer("harm_w", weight, persistent=False)

    def _time_mean(self, x: torch.Tensor, k: int) -> torch.Tensor:
        # (B, F, T) averaged over k frames; stride 1 with same-length padding.
        return F.avg_pool1d(F.pad(x, (k // 2, k // 2), mode="replicate"), k, stride=1)

    def forward(self, spec: torch.Tensor) -> torch.Tensor:
        lr, li, rr, ri = spec[:, 0], spec[:, 1], spec[:, 2], spec[:, 3]
        pl = lr * lr + li * li
        pr = rr * rr + ri * ri
        ml, mr = torch.sqrt(pl + EPS), torch.sqrt(pr + EPS)
        cre = lr * rr + li * ri
        cim = li * rr - lr * ri
        den = ml * mr
        cos_ipd, sin_ipd = cre / den, cim / den
        ild = torch.tanh(torch.log10((pl + EPS) / (pr + EPS)) / 3.0)
        k = self.smooth
        cre_s, cim_s = self._time_mean(cre, k), self._time_mean(cim, k)
        pl_s, pr_s = self._time_mean(pl, k), self._time_mean(pr, k)
        coherence = torch.sqrt(cre_s * cre_s + cim_s * cim_s + EPS) / torch.sqrt(
            pl_s * pr_s + EPS)
        # Avendano and Jot (2004): similarity psi = 2|LR*| / (|L|^2 + |R|^2), signed by the side.
        psi = 2.0 * torch.sqrt(cre_s * cre_s + cim_s * cim_s + EPS) / (pl_s + pr_s + EPS)
        panning = (1.0 - psi.clamp(0.0, 1.0)) * torch.tanh((pr_s - pl_s) / (pl_s + pr_s + EPS)
                                                            * 10.0)
        mono = ml + mr
        harm = self._time_mean(mono, self.hpss)
        perc = F.avg_pool1d(F.pad(mono.transpose(1, 2), (self.hpss // 2, self.hpss // 2),
                                  mode="replicate"), self.hpss, stride=1).transpose(1, 2)
        harmonic_ratio = harm * harm / (harm * harm + perc * perc + EPS)
        logm = torch.log(mono + EPS)
        # f0 salience: weighted sum of the log magnitude at the first five harmonics of each bin,
        # relative to the frame's maximum.
        gathered = logm[:, self.harm_idx, :]  # (B, H, F, T)
        salience = (gathered * self.harm_w[None, :, :, None]).sum(dim=1)
        salience = salience - salience.amax(dim=1, keepdim=True)
        norm = ml + mr
        feats = [torch.log(ml), torch.log(mr), lr / norm, li / norm, rr / norm, ri / norm,
                 cos_ipd, sin_ipd, ild, coherence.clamp(0.0, 1.0), panning, harmonic_ratio,
                 torch.tanh(salience / 20.0)]
        return torch.stack(feats, dim=1)  # (B, N_FEATURES, F, T)


class RMSNorm(nn.Module):
    def __init__(self, dim: int) -> None:
        super().__init__()
        self.scale = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + 1e-6) * self.scale


class BandSplit(nn.Module):
    def __init__(self, bands: list[tuple[int, int]], channels: int, dim: int) -> None:
        super().__init__()
        self.bands = bands
        self.proj = nn.ModuleList(
            nn.Sequential(RMSNorm(channels * (e - s)), nn.Linear(channels * (e - s), dim))
            for s, e in bands)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, c, _, t = x.shape
        out = []
        for (s, e), proj in zip(self.bands, self.proj, strict=True):
            band = x[:, :, s:e, :].permute(0, 3, 1, 2).reshape(b, t, c * (e - s))
            out.append(proj(band))
        return torch.stack(out, dim=1)  # (B, nb, T, D)


class CoreBlock(nn.Module):
    def __init__(self, dim: int, heads: int, n_bands: int) -> None:
        super().__init__()
        self.time_norm = RMSNorm(dim)
        self.time = nn.LSTM(dim, dim // 2, batch_first=True, bidirectional=True)
        self.band = nn.TransformerEncoderLayer(dim, heads, dim_feedforward=2 * dim, dropout=0.0,
                                               batch_first=True, norm_first=True,
                                               activation="gelu")
        self.band_pos = nn.Parameter(torch.zeros(1, n_bands, dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, nb, t, d = x.shape
        y = self.time_norm(x).reshape(b * nb, t, d)
        y, _ = self.time(y)
        x = x + y.reshape(b, nb, t, d)
        y = x.permute(0, 2, 1, 3).reshape(b * t, nb, d) + self.band_pos
        y = self.band(y)
        return y.reshape(b, t, nb, d).permute(0, 2, 1, 3)


class MaskHead(nn.Module):
    def __init__(self, bands: list[tuple[int, int]], dim: int, n_stems: int) -> None:
        super().__init__()
        self.bands = bands
        self.n_stems = n_stems
        self.heads = nn.ModuleList(
            # The output layer is the largest part of the network (bins x stems x 4 per band), so
            # the hidden width stays at `dim`; twice that would cost 1.6 M parameters for no
            # measured gain yet, and push the weights past the 10 MB fp16 budget.
            nn.Sequential(RMSNorm(dim), nn.Linear(dim, dim), nn.GELU(),
                          nn.Linear(dim, (e - s) * n_stems * 4)) for s, e in bands)
        # Start from an equal, in-phase split of the mixture (real part 1/S, imaginary 0).
        # From random complex masks a stem can settle on the inverted solution (mask near -1):
        # magnitude losses cannot see the sign, and on the toy multitrack the bass did exactly
        # that (correlation -0.98 with its reference) until this initialisation.
        for (s, e), head in zip(bands, self.heads, strict=True):
            last = head[-1]
            nn.init.normal_(last.weight, std=1e-3)
            bias = torch.zeros(e - s, n_stems, 4)
            bias[:, :, 0::2] = 1.0 / n_stems
            with torch.no_grad():
                last.bias.copy_(bias.reshape(-1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, _, t, _ = x.shape
        out = []
        for i, ((s, e), head) in enumerate(zip(self.bands, self.heads, strict=True)):
            m = head(x[:, i]).reshape(b, t, e - s, self.n_stems, 4)
            out.append(m)
        m = torch.cat(out, dim=2)  # (B, T, F, S, 4)
        return m.permute(0, 3, 4, 2, 1)  # (B, S, 4, F, T)


class WaveBranch(nn.Module):
    """Three-level 1-D U-Net with skips; its output starts at zero so training begins from masks."""

    def __init__(self, channels: tuple[int, ...], n_stems: int) -> None:
        super().__init__()
        self.n_stems = n_stems
        self.down = nn.ModuleList()
        self.up = nn.ModuleList()
        c_in = 2
        for c in channels:
            self.down.append(nn.Sequential(nn.Conv1d(c_in, c, 8, stride=4, padding=2), nn.GELU(),
                                           nn.Conv1d(c, c, 3, padding=1), nn.GELU()))
            c_in = c
        for c_out, c in zip((*reversed(channels[:-1]), channels[0]), reversed(channels),
                            strict=True):
            self.up.append(nn.Sequential(nn.Conv1d(c, c, 3, padding=1), nn.GELU(),
                                         nn.ConvTranspose1d(c, c_out, 8, stride=4, padding=2),
                                         nn.GELU()))
        self.out = nn.Conv1d(channels[0], n_stems * 2, 1)
        nn.init.zeros_(self.out.weight)
        nn.init.zeros_(self.out.bias)
        self.multiple = 4 ** len(channels)

    def forward(self, wave: torch.Tensor) -> torch.Tensor:
        n = wave.shape[-1]
        pad = (-n) % self.multiple
        x = F.pad(wave, (0, pad))
        skips = []
        for layer in self.down:
            x = layer(x)
            skips.append(x)
        for layer, skip in zip(self.up, reversed(skips), strict=True):
            x = layer(x + skip)
        y = self.out(x)[..., :n]
        return y.reshape(wave.shape[0], self.n_stems, 2, n)


class SsepNet(nn.Module):
    def __init__(self, cfg: SsepConfig | None = None) -> None:
        super().__init__()
        self.cfg = cfg or SsepConfig()
        c = self.cfg
        bands = c.bands
        self.features = Features(c.n_bins)
        self.split = BandSplit(bands, N_FEATURES, c.dim)
        self.core = nn.ModuleList(CoreBlock(c.dim, c.heads, len(bands)) for _ in range(c.layers))
        self.masks = MaskHead(bands, c.dim, len(c.stems))
        self.wave = WaveBranch(c.wave_channels, len(c.stems))

    def forward(self, spec: torch.Tensor, wave: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x = self.split(self.features(spec))
        for block in self.core:
            x = block(x)
        return self.masks(x), self.wave(wave)


def apply_masks(mask: torch.Tensor, spec: torch.Tensor) -> torch.Tensor:
    """Complex masks (B, S, 4, F, T) times the mixture (B, 4, F, T) -> stems (B, S, 2, T, F)."""
    xr = spec[:, None, 0::2]  # (B, 1, 2, F, T) real parts of left, right
    xi = spec[:, None, 1::2]
    mr, mi = mask[:, :, 0::2], mask[:, :, 1::2]
    yr = mr * xr - mi * xi
    yi = mr * xi + mi * xr
    return torch.complex(yr, yi).transpose(-1, -2)


def separate_tensor(net: SsepNet, wave: torch.Tensor) -> torch.Tensor:
    """Waveform (B, 2, n) -> stems (B, S, 2, n), differentiable (the training forward)."""
    c = net.cfg
    n = wave.shape[-1]
    spec_c = torch_stft(wave, c.n_fft, c.hop)  # (B, 2, T, F)
    spec = torch.stack([spec_c[:, 0].real, spec_c[:, 0].imag, spec_c[:, 1].real,
                        spec_c[:, 1].imag], dim=1).transpose(-1, -2)  # (B, 4, F, T)
    mask, resid = net(spec, wave)
    stems = apply_masks(mask, spec)  # (B, S, 2, T, F)
    b, s = stems.shape[:2]
    y = torch_istft(stems.reshape(b * s * 2, *stems.shape[-2:]), n, c.n_fft, c.hop)
    return y.reshape(b, s, 2, n) + resid


def count_parameters(net: nn.Module) -> int:
    return sum(p.numel() for p in net.parameters())
