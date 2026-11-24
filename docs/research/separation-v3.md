# Separation for v3: what wins, and why the cascade is shaped as it is

Status of every claim is tagged **ESTABLISHED** (read in the primary source) or **SPECULATIVE**
(our own reasoning or a measurement on generated songs only). Read 2026-11-24.

## What the leaderboards and challenges say

- **BS-RoFormer** (Lu, Wang, Kong and Hung, ICASSP 2024, arXiv 2309.02612): band-split module,
  hierarchical Transformers over time and over bands, rotary position embeddings. Ranked first
  in the music-demixing track of the Sound Demixing Challenge 2023. **ESTABLISHED.**
- **Mel-Band RoFormer** (Wang, Lu and Won, arXiv 2310.01809): the same with overlapping mel-scale
  bands; reported better than BS-RoFormer on vocals, drums and bass on MUSDB18-HQ. **ESTABLISHED.**
- **SDX'23** (arXiv 2308.06979): the winning systems and the "robust" training task (label noise
  and bleeding in the training data). The best system improved SDR by over 1.6 dB over the 2021
  winner on the same set. **ESTABLISHED.**
- **MVSep benchmarks and ensembles** (Solovyev, Stempkovskiy and Habruseva, arXiv 2305.07489):
  an ensemble of models chosen *per stem*, with weights chosen on a validation set, beat every
  single model; the open code is ZFTurbo's Music-Source-Separation-Training (MIT).
  The MVSep Multisong leaderboard at the time of reading: the top single model is a BS-RoFormer
  build (about 14.6 dB vocals SDR), the top ensembles are BS-RoFormer, Mel-Band RoFormer and SCNet
  XL (MVSep's newest vocal ensemble lists 11.93 dB vocals and 18.23 dB instrumental on its
  Multisong set, a different and harder set from the figures above; sets are not comparable).
  Mel-Band and BS variants and their ensembles hold the top positions. **ESTABLISHED** (read from
  the leaderboard and algorithms pages; they change).
- **SDR is a weak proxy for what a listener hears.** It weights low frequencies heavily and does
  not track perceived separation; MVSep publishes *bleedless* (penalises content in the estimate
  that is not in the reference) and *fullness* (penalises content missing from the estimate)
  next to it, both on mel spectrograms in dB (arXiv 2510.25745 describes them; the open
  implementation is `bleed_full` in ZFTurbo's `utils/metrics.py`, MIT). We implement them from
  that definition (`stage.metrics.separation.bleed_full`) and check them against a line-by-line
  reimplementation of the original to 1e-7. **ESTABLISHED.**
- **Music Source Restoration challenge 2025** (task: arXiv 2505.21827; winner: SJTU X-LANCE,
  arXiv 2602.09042). The winning system is a **sequential cascade of BS-RoFormers, each with one
  job**: denoise, then a frozen pretrained 6-stem separator (bass, drums, other, vocals, guitars,
  piano), then models fine-tuned from the 6-stem model's Transformer weights that split drums
  and "other" into finer categories, and **dereverberation applied only to the vocals**, bypassed
  when its output is more than 10 dB quieter than its input, because reverberation on
  instruments is part of the intended timbre and the model otherwise removes backing vocals.
  It ranked first on every objective (MMSNR 4.46 against 2.34 for second) and subjective measure.
  Authors' own conclusion: the challenge still measures separation more than restoration.
  **ESTABLISHED.**

What this says for SoundStage: (1) a cascade of specialised models beats one four-stem model;
(2) ensembles are weighted per band or per stem on a validation set; (3) dereverberation is a
vocal tool with a guard, not something to run on every stem; (4) SDR alone is not enough.

## The models, their licences and the numbers their authors give

Full table with sizes and SHA-256 in `models/MANIFEST.md` and `configs/cascade/models.json`.
SDRs are those the source gives, on the set it names, and are not comparable across sets.

| Level | Model | Licence at the source | Number from the source |
|---|---|---|---|
| 1 | Kim Mel-Band RoFormer (`KimberleyJSN/melbandroformer`) | MIT (card tag) | vocals SDR 10.98, Multisong (ZFTurbo table) |
| 1 | anvuew BS-RoFormer (`anvuew/BS-RoFormer`) | GPL-3.0 (card) | 12.55 on the author's set (file name) |
| 2 | anvuew karaoke BS-RoFormer | GPL-3.0 (card) | none stated |
| 3 | BS-RoFormer SW, 6 stems (re-upload `enerjazzer/BS-ROFO-SW-Fixed`) | **none stated** (card says `unknown`) | none found |
| 3 | htdemucs 6 stems (fallback) | MIT (repository) | bass 11.22, drums 10.22, vocals 8.05, Multisong |
| 4 | jarredou DrumSep MDX23C, 5 stems | CC BY-NC-SA 4.0 per Intel's conversion; the release page states none | kick 16.66, snare 11.53, toms 12.33, hi-hat 4.04, cymbals 6.36 (DrumSep test) |
| 5 | anvuew dereverb Mel-Band RoFormer | GPL-3.0 (card) | 19.17 on the author's set (file name) |

**Findings that change the plan the brief assumed.**

1. *BS-RoFormer SW is not CC BY-NC-SA as suspected; it has no stated licence at all.* The
   original author's repository is gone; every copy found says `license: unknown` (third-party
   conversions tag it MIT without citing an upstream statement). It is recorded as
   `unverified` and **off by default**: the cascade's level 3 uses htdemucs 6-stem (MIT) until
   the owner decides. The 2025 challenge winner built on it, which shows how good it is and not
   that it may be redistributed.
2. *The dereverb model is for vocals and says so.* Its author's card says it was trained on dry
   mono single voices, pulls stereo and layered vocals towards mono, and removes non-centre
   harmonies. So Level 5 for lead vocals uses it, behind the 10 dB guard; every other stem
   (backing vocals, guitar, piano, other) uses the model-free late-reverberation subtractor
   (`dereverb_dsp`, Lebart, Boucher and Denbigh 2001), also guarded. No published model for
   dereverberating guitars or pianos was found.
3. *GPL-3.0 weights.* Used at run time on the Space, never redistributed by this repository,
   and credited. Whether a GPL licence on weights binds output audio is not settled; the
   renders are not claimed under any terms beyond the original songs'.
4. *Drum separation is non-commercial.* Allowed here (research demo, attribution, noted in the
   in-app credits); a commercial product would need a replacement.

## Level 6, azimuth discrimination (ADRess)

Barry, Lawlor and Coyle, DAFx-04 (2004): a source with gains (g_L, g_R) is cancelled in
|L - g R| at g = g_L/g_R, so the null's position in an "azimuth plane" gives the pan of the
dominant source in each tile and its depth the confidence. **ESTABLISHED** (read from abstracts
and the paper's description; the PDFs' hosts were blocked in this session, so the 2004 paper's
parameter values and the 2005 AES paper on reconstruction were *not* read, and the following are
our own choices): the null found in closed form instead of on 100 discrete gains; Gaussian soft
masks instead of a hard azimuth window; the mask applied to the original complex stereo
spectrum, so every output is a stereo stem with its own phase and level difference, and the
outputs sum to the input. On a generated pair of double-tracked guitars panned left and right
(plain SDR, the soft split): 5.5 and 5.3 dB, against 21.9 dB for an oracle ratio mask on the
same spectrogram. ADRess assumes one dominant source per tile (W-disjoint orthogonality,
Rickard and Yilmaz 2004): two guitars playing the same chord share bins, and no pan rule can
separate those; the Wiener step recovers 0.5 dB, the rest needs a model. **SPECULATIVE** as a
quality claim for real recordings.

## Our post-processing layer: what it does and what it does not

Measured on generated songs (`stage.groundtruth`, 14 s from 26 s in, plain SDR, mean over the
14 leaves active in that window), with "leaky" four-stem input (each true stem plus 25 percent of
the other three, the kind of error a four-stem separator makes) fed to the model-free levels:

| Step | Mean SDR (dB) | Verdict |
|---|---|---|
| No post-processing | -2.18 | |
| Multichannel Wiener (2 iterations, spectral density held fixed) | **+0.45** | keep: +2.6 dB |
| Mixture-consistency projection alone | -0.77 | keep: it makes the sum exact, +1.4 dB |
| Wiener, targeted musical-noise repair, then consistency | -0.08 (2.1 dB better than none) | keep, repair fires only above 25 flickering tiles per thousand |
| Cross-stem coherence bleed suppression | -1.48 | **off by default**: helps bass, hurts hi-hat and lead |
| Transient restoration (envelope limiter around onsets) | no change in attack time | **off by default**: a leaf cannot exceed its own mix, so the limiter never acts |

With *perfect* (oracle) stems the layer makes things worse (kick 19.4 to 9.1 dB, bass 233 to
9.6 dB): it exists for estimates that do not add up to the mix, and the cascade applies it only
to neural or leaky outputs. Wiener's first version, which re-estimated the spectral density
too, drifted leaves towards neighbours that share their pan (bass SDR 9.4 dB with the density
held fixed, as norbert does). The musical-noise detector is calibrated in
`tests/unit/test_cascade_dsp_levels.py`: reference leaf 5 flickering tiles per thousand, soft
azimuth masks 6, a hard pan mask 11, a random mask 150 to 180; a detector on the leaf signal
alone does not work, because resynthesis smooths isolated specks across neighbouring tiles.
These numbers are on synthetic songs. They show the layer's direction, not its size on real
recordings; MUSDB18-HQ is run by `scripts/eval_separation.py` where the data is.

## Speed and quota

- Every level is cached by content hash (`stage.separation.cascade.tree.Cache`), so changing the
  scene, the HRTF or the placement never re-separates.
- ZeroGPU: the figures found disagree (a forum reply says 5 GPU-minutes a day for a free
  account, another 3.5; PRO about 25, with later posts citing 40; no official figure for
  anonymous visitors was found; the Hub docs give PRO as 7 or 8 times the free quota; the quota
  resets 24 hours after first use). **No GPU was available in this session, so GPU seconds
  per minute of audio are not measured**; `scripts/measure_cascade.py` measures them with
  CUDA-synchronised timers on the Space, and the table in the README is filled from that run.
  The budget to design against is the smallest credible figure, 3.5 GPU-minutes a day: a
  3.5-minute song must cost under about 17 GPU-seconds per audio minute for all neural levels
  together. The `fast` preset (one vocal model, one 6-stem model; dereverberation and the kit by
  DSP) exists to fit that; `best` is for pre-rendered catalogue tracks and owners with quota.
- The CPU path (`cpu` preset) needs no weights beyond the four-stem fallback chain.

## Not done, and why

- No neural level was run here: no GPU, and the weight hosts for the published checkpoints are
  not on this session's network allow-list. The loader is tested on a tiny randomly initialised
  network saved and loaded through the same code path
  (`tests/unit/test_cascade_neural.py`); the first run with published weights happens on the
  Space and its result goes in the log.
- Band weights for the level-1 ensemble are not fitted (they need a validation set of real
  songs and the models); `scripts/fit_ensemble.py` is the planned tool, until then equal weights,
  stated in run.json.
- The six-stem fine-tuned splitters of the SJTU system (synths, percussion, orchestral) are open
  at github.com/ModistAndrew/xlance-msr; their licence was not checked and they are not used.
