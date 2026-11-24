# Training the SoundStage Separator on Kaggle

This folder trains our own separator (decision 0015): the code is ours, the weights are ours,
and the large downloads (MUSDB18-HQ, the teacher model) happen on Kaggle's servers. The cloud
session that wrote this code has no GPU; it proved the training loop works on a tiny synthetic
multitrack (`tests/separation/test_ssep_model.py`: overfits to at least 8 dB mean SDR in 100
steps, the ONNX export matches PyTorch within 1e-4, a run resumes from its checkpoint).

## One-time setup (about 10 minutes)

1. **Hugging Face write token.** On huggingface.co: Settings, Access Tokens, New token, type
   "Write". The training run creates and fills the model repository
   `danieltesh/soundstage-separator`.
2. **Kaggle.** kaggle.com, Create, New Notebook. File, Import Notebook, and upload
   `training/kaggle_notebook.ipynb` from this repository.
3. In the notebook's right-hand panel: **Settings**, Accelerator **GPU T4 x2** (or P100), and
   Internet **On** (Kaggle asks for a verified phone number once). **Add-ons, Secrets**: add a
   secret named `HF_TOKEN` with the token from step 1, and tick it for this notebook.
4. Optional: **Add Input**, search for a copy of MUSDB18-HQ on Kaggle and add it. Without one,
   the notebook downloads MUSDB18-HQ from Zenodo (about 30 GB, which Kaggle allows in
   /kaggle/working).

## The four runs

Set `STAGE` in the first code cell, then **Save Version, Save & Run All (Commit)**, so the run
continues with the browser closed and its output (teacher stems, checkpoint) is kept.

| Stage | What it does | GPU time |
|---|---|---|
| 1 | Teacher stems: htdemucs_ft over the 100 training tracks (and any extra music) | about 1.5 h |
| 2 | Training, first session. Attach the stage 1 output first (Add Input, Your Work) | about 10.5 h |
| 3 | Training, second session: resumes from the checkpoint in the model repository | about 10.5 h |
| 4 | Evaluation on the 50 test tracks: ours, htdemucs and htdemucs_ft; writes the result into model.json | about 2 h |

Total about 25 GPU hours, inside Kaggle's free 30 hours a week. A run that stops early is just run
again with the same `STAGE`: teacher stems skip finished tracks and training resumes from
`ckpt.pt` (saved every 2000 steps and at the time limit, and pushed to the model repository).

## What happens after stage 4

The Space downloads `model.onnx` and `model.json` from the model repository at start-up. It uses
our separator **only if** model.json records, from the stage 4 evaluation, an average SDR at
least that of htdemucs. Until then it uses the teacher (htdemucs, downloaded on Hugging Face's
servers) and every run.json says which separator ran and why.

## Data and licences

| Data | Licence | Use here |
|---|---|---|
| MUSDB18-HQ (Rafii, Liutkus, Stoter, Mimilakis and Bittner 2019) | Research use only; the tracks carry their own (mostly non-commercial) licences | Training and the test-set evaluation. Weights trained on it are for research until the owner confirms otherwise. |
| Extra music for pseudo-labels | Only music the owner has the right to use | Optional, through a private Kaggle dataset |
| htdemucs_ft teacher (demucs repository) | MIT | Teacher only, never shipped |

No audio, stems or checkpoints are committed to this repository.
