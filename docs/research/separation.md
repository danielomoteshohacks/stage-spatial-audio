# Music source separation: what made Demucs and its successors work

Research note for the SoundStage Separator (decision 0015). Written before the code.

## How this note was researched, and what could not be read

This session's network blocks arxiv.org, joss.theoj.org and the publishers' sites. What was read
directly: the Demucs repository README (github.com/facebookresearch/demucs, archived 1 January
2025) and the norbert README (github.com/sigsep/norbert). Paper tables were reached only through
web-search summaries, which quote the papers' tables; those numbers are marked **(secondary)**
below and must be re-checked against the PDFs before they are quoted anywhere else. The
evaluation script (`scripts/eval_separation.py`) measures htdemucs and htdemucs_ft directly on
the MUSDB18-HQ test set on Kaggle, and those measurements, not the quoted ones, are the gate.

## Baselines to beat

| Model | Extra training data | Avg SDR (dB) | Drums | Bass | Other | Vocals | Source |
|---|---|---|---|---|---|---|---|
| HT Demucs (htdemucs) | 800 songs | 9.00 | 10.08 | 10.39 | 6.32 | 9.20 | avg: README (read); per stem: SCNet paper's table (secondary) |
| HT Demucs, per-source fine-tuned + sparse attention | 800 songs | 9.20 | | | | | README intro (read); the released htdemucs_ft has no sparse kernels |
| HT Demucs f.t. (v4) in the README comparison table | 800 songs | 9.0 | | | | | README table (read) |
| Hybrid Demucs (v3) | none | 7.7 | | | | | README table (read) |
| Band-Split RNN | none / 1.7k mixes | 8.2 / 9.0 | | | | | README table (read) |
| BS-RoFormer, L = 9, 82.8 M params | none | 10.02 | 9.66 | 11.58 | 7.80 | 11.02 | Mel-RoFormer paper table (secondary) |
| Mel-Band RoFormer, L = 9, 94.8 M params | none | | 9.34 | | 7.93 | 11.60 | same (secondary) |
| Demucs v2 (waveform) | none | 6.3 | | | | | README table (read) |
| Open-Unmix | none | 5.3 | | | | | README table (read) |

The README describes htdemucs_ft as "separation will take 4 times more time but might be a bit
better", trained on the same data. A secondary comparison puts the fine-tuning gain per stem at
about +0.6 dB bass, +0.3 vocals, 0 drums, -0.1 other.

**Target:** our engine becomes the default only when its average SDR on the MUSDB18-HQ test set,
measured by our script with museval's BSSEval v4 (median over 1 s frames, then median over
tracks, the SiSEC 2018 protocol), is at least that of htdemucs measured the same way.

## The principles behind the results

1. **Two domains at once.** Demucs v2 showed a waveform U-Net can rival spectrogram masking;
   Hybrid Demucs (v3) ran a spectrogram branch and a waveform branch in parallel and summed
   them, each covering the other's weakness (phase and transients in the waveform, harmonic
   resolution in the spectrogram).
2. **U-Net encoder and decoder with skip connections.** Strided convolutions down, transposed
   convolutions up, the encoder's activations added back at each level, so fine detail survives
   the bottleneck.
3. **Long context.** Demucs v2 put a bidirectional LSTM at the bottleneck; HT Demucs replaced it
   with a cross-domain transformer (self-attention within each branch, cross-attention between
   them). The README notes HT models take at most 7.8 s segments.
4. **Band-split frequency modelling.** Band-Split RNN cuts the spectrum into sub-bands that are
   narrow where the ear and the instruments need resolution (low frequencies) and wide at the
   top, projects each band to a shared feature size, then models sequences across time and
   across bands alternately. BS-RoFormer keeps that split and uses transformers with rotary
   position embeddings for both axes; Mel-RoFormer uses overlapping mel-scale bands, which helps
   vocals and hurts bass (the paper reports bass only for its smaller model).
5. **Masks plus a multichannel Wiener filter.** Open-Unmix estimates magnitude masks and refines
   all sources together with a multichannel Wiener filter (norbert: "an iterative procedure
   called Expectation Maximization, where filtering and re-estimation of the parameters are
   iterated"). The Wiener step uses the stereo covariance of each source, so it is also where the
   mix's spatial information enters.
6. **Heavy augmentation.** Remixing stems drawn from different songs (the largest single gain in
   Demucs v2), random gains, channel swap, sign flip, and pitch and tempo changes.
7. **Losses.** Waveform L1 (Demucs), with multi-resolution STFT losses common in later systems,
   so errors are penalised both in time and in several time-frequency trade-offs.
8. **Data.** The strongest results use extra data (800 songs for htdemucs); without it the
   transformer models are data-hungry. We cannot license 800 songs, so we distil from teachers
   on music the owner may use.

## What SoundStage adds, and why

- **Spatial front end.** Per-bin ILD, IPD (as cosine and sine), inter-channel coherence and the
  panning index of Avendano and Jot as input channels. A mix encodes where each instrument sits,
  and our downstream task is spatial, so the separator should see it explicitly rather than
  rediscover it from raw stereo spectra.
- **HPSS cues** (time-smoothed against frequency-smoothed magnitude, after Fitzgerald's median
  filtering, implemented with mean filters so it stays exportable to ONNX) and an **f0 salience**
  map (harmonic summation) for the voice.
- **A compact band-split network** in the BS-RoFormer family with a small waveform U-Net branch,
  targeted under 10 MB of fp16 weights (BS-RoFormer L = 9 is 82.8 M parameters, about 166 MB).
- **A DSP back end:** multichannel Wiener refinement, an exact mixture-consistency projection (the
  stems always sum to the mix, which the spatial renderer relies on), and a bleed-reduction stage,
  with residual SNR and per-stem leakage estimates in run.json.

Each feature must earn its place in an ablation (same training budget with and without it);
until that ablation runs on Kaggle, the features are SPECULATIVE.
