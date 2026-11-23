---
title: SoundStage
colorFrom: gray
colorTo: green
sdk: gradio
sdk_version: 6.32.0
python_version: "3.10"
app_file: app.py
pinned: false
license: apache-2.0
short_description: Backend of the SoundStage listening bench
---

# SoundStage backend

The processing API behind the SoundStage listening bench (`web/`). It takes one track, renders an
excerpt with the SoundStage spatializer (optionally after Demucs stem separation), and returns
the original excerpt, the spatial render, the spatial stems and a run report. Tracks are
processed and then deleted after 30 minutes; nothing is stored permanently. Use audio you own or
may use.

The same `app.py` runs on a laptop and on a Hugging Face ZeroGPU Space.

## API

One endpoint, `/process`. It streams one update per pipeline stage, then returns the files.

| Input | Type | Notes |
|---|---|---|
| `audio_file` | file | wav, flac, mp3, ogg or m4a; at most 12 minutes |
| `mode` | `"lite"` or `"stems"` | stems separates first, and falls back to lite (recorded) if it cannot |
| `profile` | string | any name in `stage.render.profiles.PROFILES` (`V0` to `V5`, `V4b`, `V5b`, `max`) |
| `beta` | number | width, 1.0 to 2.4 |
| `start` | number or null | null means 30 s in, moved earlier for a short track |
| `seconds` | number or null | null means 30 s; at most 120 s |

Outputs, in order: progress (JSON with `stages`, `done`, `error`, and on the last update `run`,
`notes` and `expires_in_s`), `original.flac`, `spatial.flac`, the four spatial stems (stems mode
only) and `run.json`. All audio is 24-bit FLAC.

From Python:

```python
from gradio_client import Client, handle_file

client = Client("http://127.0.0.1:7860/")  # or "<user>/<space>"
job = client.submit(handle_file("track.flac"), "lite", "max", 2.0, None, None,
                    api_name="/process")
for update in job:
    print([s["status"] for s in update[0]["stages"]])
progress, original, spatial, stems, run_json = job.result()
```

## Run it on a laptop

From the repository root:

```bash
python -m pip install -e ".[backend]"            # Lite only
python -m pip install -e ".[backend,separation]" # with Demucs stems (downloads torch)
python space/app.py                              # http://127.0.0.1:7860
```

To reach it from a phone on the same Wi-Fi, start it with `GRADIO_SERVER_NAME=0.0.0.0` and use
the laptop's local IP address (for example `http://192.168.1.20:7860`) as the backend URL.

## GPU use on ZeroGPU

Only the separation call is decorated with `@spaces.GPU(duration=60)`. ZeroGPU charges each
visitor's daily quota (a few GPU minutes on a free account) for the duration requested, so the
rendering, which is CPU work, never holds the GPU. When `spaces` is not installed (a laptop), the
same function runs directly on CUDA if available, otherwise on the CPU.

This GPU path has not been run on a real ZeroGPU Space yet; see `docs/log.md`.

## Deploying from GitHub (one-time setup)

`.github/workflows/deploy-space.yml` runs on every push to `main`. It assembles this folder plus
`src/stage` into one bundle (`space/bundle.sh`) and uploads it to the Space. It skips, with a
message in the job log, until both of these exist:

1. Create the Space on Hugging Face: New Space, SDK **Gradio**, hardware **ZeroGPU** (check
   Hugging Face's current terms for which plans can host ZeroGPU Spaces).
2. Create a Hugging Face access token with **write** access to that Space
   (Settings, Access Tokens).
3. In the GitHub repository, Settings, Secrets and variables, Actions:
   - add the **secret** `HF_TOKEN` with the token;
   - add the **variable** `HF_SPACE` with the Space id, for example `your-name/soundstage`.
4. Push to `main` (or re-run the workflow). The Space rebuilds from the uploaded bundle.

To try the bundle locally before deploying:

```bash
./space/bundle.sh /tmp/soundstage-space
cd /tmp/soundstage-space && python app.py
```
