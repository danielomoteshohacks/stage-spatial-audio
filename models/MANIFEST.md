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

Attribution for SADIE II, as required by its licence: Armstrong, C., Thresh, L., Murphy, D. and
Kearney, G. (2018). "A Perceptual Evaluation of Individual and Non-Individual HRTFs: A Case Study
of the SADIE II Database." Applied Sciences 8(11), 2029. Copyright 2018, University of York,
licensed under the Apache License, Version 2.0.

A pretrained model counts as research-only until its licence is confirmed in writing.
