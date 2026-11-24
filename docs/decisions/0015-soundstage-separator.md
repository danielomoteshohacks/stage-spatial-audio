# 0015. Our own separator: the SoundStage Separator, distilled, gated against htdemucs

- Status: accepted (engine and training code); the trained weights are pending the Kaggle runs
- Date: 2026-11-24

## Context

The owner does not want SoundStage to depend on downloading Demucs or other large separation
models, and asked for our own engine that learns from what Demucs proved and improves on it.

What "our own engine" can honestly mean: a separator's knowledge lives in trained weights, not
in rules that could be copied. So ours is our own architecture, our own DSP front end and back
end, and our own small trained weights. Teacher models are used only as teachers during
training and are never shipped. This session has no GPU, so it writes and tests all the code
and proves the training loop on tiny data; the real training runs on free Kaggle GPUs from a
notebook the owner launches (`training/README.md`).

## Decision

- **Architecture** (`stage.separation.ssep.model`, research in `docs/research/separation.md`):
  a spatial, HPSS and f0 front end computed inside the graph (13 features per bin); a 38-band
  split after Band-Split RNN; 4 blocks of a bidirectional LSTM across time and a transformer
  layer across bands (dim 96); per-band MLP heads giving complex masks per stem and channel; a
  three-level waveform U-Net added in the time domain (Hybrid Demucs). Four stems (vocals,
  drums, bass, other), with the stem list in the configuration so more can be added by training
  a model with more heads. **3.95 M parameters, 8.4 MB as an fp16 ONNX file.** The teacher's
  size is measured by `scripts/eval_separation.py` on Kaggle rather than quoted.
- **DSP back end** (`ssep.dsp`, numpy): multichannel Wiener refinement with full-rank spatial
  covariances (Duong, Vincent and Gribonval 2010, the method norbert implements), a bleed
  reduction exponent of 1.25 on the stems' power shares, and an exact mixture-consistency
  projection (stems sum to the mix to 1e-9). run.json reports the raw residual SNR and a per-stem
  leakage estimate.
- **Inference** (`ssep.infer`): ONNX Runtime on the Space CPU, 6 s chunks with 25 percent
  complementary crossfades, no torch. Measured here: **9.8 s of CPU per 30 s of audio** on the
  4 vCPU build machine. The graph uses only standard operators (LSTM, attention, convolutions,
  pooling, gather), the prerequisite for a WebGPU or WASM build later.
- **Training** (`training/`): MUSDB18-HQ ground truth plus distillation from htdemucs_ft
  pseudo-labels; remix, gain, channel swap, sign flip and speed (pitch and tempo) augmentation;
  waveform L1 plus multi-resolution STFT losses plus the distillation term; mixed precision,
  gradient clipping, checkpoint resume and a time budget for Kaggle's session limits; pushes to
  `danieltesh/soundstage-separator` with a token kept as a Kaggle secret. About 25 GPU hours in
  four runs, inside Kaggle's free weekly allowance.
- **Gate and fallback** (`stage.separation.chain`): ssep runs only when its model card records a
  museval evaluation at least equal to htdemucs; otherwise the teacher (htdemucs, inside
  @spaces.GPU), otherwise Lite. Each attempt and its reason are in run.json.

## Measured in this session (no trained weights yet)

| Check | Result |
|---|---|
| Overfit a 2-example synthetic multitrack, small config, 100 steps | mean SDR above 8 dB (gate); at 200 steps vocals 16.4, drums 2.6, bass 24.7, other 9.3 dB |
| ONNX export vs PyTorch, frames 30 and 90 | max difference under 1e-4 |
| Stems from the ONNX separator sum to the mixture | within 1e-6, including resampling 48 to 44.1 kHz and back |
| Training script: stop, resume, export | resumes at the saved step, writes model.onnx and model.json |

**What went wrong:** with randomly initialised complex masks the toy bass converged to the
inverted solution (correlation -0.98 with its reference, SDR -5.8 dB): magnitude losses cannot
see the sign. The mask heads now start at an equal in-phase split (1/S real, 0 imaginary), after
which the bass reached 25 dB.

## Not done yet, and why

- No trained weights and no MUSDB18-HQ numbers: they need the Kaggle runs. Until stage 4 of the
  notebook has run, the README's separator table holds the published baselines only.
- The feature ablation (each front-end feature on and off) needs the same Kaggle budget again;
  until it runs, every feature is SPECULATIVE.
- A RoFormer teacher: no checkpoint with a confirmed permissive licence was found, so the teacher
  ensemble is htdemucs_ft alone (MIT).

## Licences

MUSDB18-HQ is for research use only: the README and models/MANIFEST.md say so, and weights trained
on it are research weights until the owner decides otherwise. demucs and its pretrained models
are MIT according to the repository README (read). onnxruntime is MIT, onnx Apache-2.0, torch
BSD-3-Clause, museval MIT.

## Patents

None identified for band-split mask estimation, multichannel Wiener filtering or mixture
consistency projection; all are published academic methods with open implementations.
