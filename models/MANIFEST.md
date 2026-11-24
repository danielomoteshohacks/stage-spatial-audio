# Model and data-asset manifest

Every pretrained model or measured dataset SoundStage uses, with where it comes from, its
licence as checked, and what it is used for. Large files are never committed: they are built
or downloaded on GitHub Actions runners or on the Hugging Face Space and verified by checksum.

| Name | Source | Version | Checksum (SHA-256) | Licence (checked where) | Used for | Commercial use |
|---|---|---|---|---|---|---|
| SADIE II, subject D1 (Neumann KU100) HRIRs, resampled pack `sadie2-d1-ku100.npz` | The Audio Lab, University of York; Zenodo 10.5281/zenodo.12092466, file `D1.zip` (md5 468f0fce29c2f5880627c571b73e64c3), built by `tools/hrtf-pack` into release `hrtf-pack-v1` | SADIE II 2-2 | f99b77ff092e44c3d043060630abb68563e4696ca40b4d3a3c447cca5b084c74 | Apache-2.0 (Zenodo record metadata; `License` attribute of the SOFA file) | Default head-related filters (decision 0012) | Yes, under Apache-2.0 with attribution |
| SADIE II, subject D1 studio BRIRs, `sadie2-d1-brir48k.npz` | Same archive, `D1/D1_BRIR_SOFA/D1_48K_24bit_0.3s_FIR_SOFA.sofa` | SADIE II 2-2 | 7142adb4956c85bbec415c204f04b16ca2ebea88e6cf87f46338d5f798b0ab27 | Apache-2.0 (as above) | Calibration reference of the room model (decision 0013); not used in renders | Yes, with attribution |
| htdemucs (Demucs v4) | Meta AI Research, `demucs` package, downloaded on the Space | 4.x | fetched by `demucs.pretrained` | MIT (demucs repository README, read; no separate weights licence is stated) | Teacher fallback for stems mode on the Space (decisions 0009, 0015) | Yes, as far as the repository states |
| htdemucs_ft (Demucs v4, fine-tuned) | Same package, downloaded on Kaggle | 4.x | fetched by `demucs.pretrained` | MIT (as above) | Teacher for distillation only, never shipped (0015) | Yes, as far as the repository states |
| SoundStage Separator (ssep) | Ours: `training/` on Kaggle, pushed to the Hugging Face model repository `danieltesh/soundstage-separator` | not trained yet | recorded in model.json when published | Code Apache-2.0; weights trained on MUSDB18-HQ, so research use only until the owner decides | Default separator once its evaluation reaches htdemucs (0015) | No (MUSDB18-HQ is research-only) |

| Kim Mel-Band RoFormer (vocals) | Hugging Face `KimberleyJSN/melbandroformer`, file `MelBandRoformer.ckpt` (913,106,900 bytes) | as of 2026-11 | 87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e | MIT (model card tag) | Cascade level 1, vocals vs instrumental (decision 0023); vocals SDR 10.98 on MVSep Multisong (ZFTurbo table) | Yes |
| anvuew BS-RoFormer (vocals) | Hugging Face `anvuew/BS-RoFormer`, `bs_roformer_ft1_anvuew_sdr_12.55.ckpt` (204,493,312 bytes) | as of 2026-11 | 60347271e8493fdff28ef558c3b2297afb869a1f4462594ed548038264bec395 | GPL-3.0 (model card header) | Cascade level 1 ensemble member, `best` preset only; run at run time, never redistributed | Copyleft: GPL-3.0 terms |
| anvuew karaoke BS-RoFormer | Hugging Face `anvuew/karaoke_bs_roformer`, `karaoke_bs_roformer_anvuew.ckpt` (204,486,925 bytes); training data by becruily | as of 2026-11 | 206d04757cb5f75ca3b55f8a0a48f5c26aa2351d4ff3c7adbfc9affa30ea3ae4 | GPL-3.0 (model card header) | Cascade level 2, lead vs backing vocals | Copyleft: GPL-3.0 terms |
| BS-RoFormer SW (6 stems: bass, drums, other, vocals, guitar, piano) | Hugging Face `enerjazzer/BS-ROFO-SW-Fixed`, `BS-Rofo-SW-Fixed.ckpt` (699,412,152 bytes), a re-upload of jarredou's BS-ROFO-SW whose own repository was removed | as of 2026-11 | 24e7d35ee9c64415673d3fd33e06a67cac2c103c5df6267ba1576459c775916e | **Not stated** (card: `license: unknown`; MIT tags on third-party conversions cite no upstream statement) | Cascade level 3, **disabled by default** (class `unverified`); the 2025 MSR challenge winner built on it (arXiv 2602.09042) | Unknown: no |
| htdemucs, 6-stem variant | `demucs` package (Meta AI Research), downloaded on the Space | 4.x | fetched by `demucs.pretrained` | MIT (repository README; no separate weights licence stated) | Cascade level 3 default, and the CPU path | Yes, as far as the repository states |
| DrumSep MDX23C, 5 stems (kick, snare, toms, hi-hat, cymbals) by jarredou | GitHub release `jarredou/models` tag `DrumSep`, `drumsep_5stems_mdx23c_jarredou.ckpt`; the release page could not be read in this session | v0.1 | recorded on first download | CC BY-NC-SA 4.0 per Intel's OpenVINO conversion of this checkpoint (`Intel/drumsep_mdx23c_jarredou_openvino`); the original release states none | Cascade level 4; non-commercial research demo with attribution only | No |
| anvuew dereverb Mel-Band RoFormer | Hugging Face `anvuew/dereverb_mel_band_roformer`, `dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt` (913,107,578 bytes) | as of 2026-11 | 9262877b87e9ebb0fb808a456b0a411fa677f5df31c8383c1254af531c078970 | GPL-3.0 (model card header) | Cascade level 5, lead vocal only, behind the 10 dB guard | Copyleft: GPL-3.0 terms |
| Music-Source-Separation-Training (inference and model code) | github.com/ZFTurbo/Music-Source-Separation-Training, cloned at a pinned commit on the Space | pin recorded at deploy | n/a (code) | MIT (LICENSE file, read) | Model classes that match the published checkpoints' parameter names (`stage.separation.cascade.runner.build_model`) | Yes |
| `BS-RoFormer` Python package (lucidrains) | PyPI `BS-RoFormer` | 1.x | n/a (code) | MIT | Fallback model classes when the repository above is not on the path; used by the loader test | Yes |

Cascade attributions for the credits screen: Kim (KimberleyJSN) Mel-Band RoFormer vocals;
anvuew (BS-RoFormer vocals, karaoke, dereverb) with training data by becruily; jarredou and
aufr33 (DrumSep); ZFTurbo (Music-Source-Separation-Training, MVSep benchmarks); Meta AI Research
(Demucs); Lu, Wang, Kong and Hung (BS-RoFormer); Wang, Lu and Won (Mel-Band RoFormer).

Attribution for SADIE II, as required by its licence: Armstrong, C., Thresh, L., Murphy, D. and
Kearney, G. (2018). "A Perceptual Evaluation of Individual and Non-Individual HRTFs: A Case Study
of the SADIE II Database." Applied Sciences 8(11), 2029. Copyright 2018, University of York,
licensed under the Apache License, Version 2.0.

A pretrained model counts as research-only until its licence is confirmed in writing.
