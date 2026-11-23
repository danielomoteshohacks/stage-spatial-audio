# web

The SoundStage listening bench: drop a track, hear the original and the spatial render in perfect
sync, and tune the spatializer and separator by ear. Svelte 5, Vite and TypeScript, mobile first.

It talks to the Python backend in [`../space/`](../space/) (a laptop or a Hugging Face Space).
Nothing is processed in the browser yet; the Rust/WebAssembly real-time path is slice 4.

## What it does

- Drop zone and file picker (wav, flac, mp3, ogg, m4a), with an excerpt picker (start and length).
- Mode (Lite or Stems), character (the render profile, in plain words), and width (beta), with an
  Advanced drawer that shows the technical names. The profile list is read from the backend.
- Live stage-by-stage progress streamed from the backend's `/process` endpoint.
- A sample-locked A/B player: the original, the spatial render and the spatial stems are decoded
  into AudioBuffers and started at the same AudioContext time; the Original/Spatial switch moves
  two gains with a 30 ms crossfade, so it never restarts. Space switches, K plays or pauses.
- A waveform with a seekable playhead and a drag-to-loop region, plus `[` and `]` for loop points.
- Stems mode: solo and mute per spatial stem, mixed live, and "Use full spatial render".
- A run report: stage timings, the Lite fallback note when separation could not run, residual SNR,
  levels and the profile used.
- A backend setting saved in this browser, and a specific fix when the backend cannot be reached.

## Develop

```bash
cd web
npm ci
npm run dev            # http://localhost:5173, backend default http://127.0.0.1:7860
```

Start the backend in another terminal from the repository root: `python space/app.py`.

To test on a phone on the same Wi-Fi, serve both on the network and open the page over http:

```bash
GRADIO_SERVER_NAME=0.0.0.0 python space/app.py   # terminal 1, repository root
npm run dev -- --host                            # terminal 2, in web/
```

Open the "Network" address Vite prints on the phone, and set the backend (top right) to
`http://<laptop IP>:7860`. An https page (such as the deployed site) cannot call an http backend
on your network; with the deployed site, use the Space as the backend.

## Checks

```bash
npm run check   # svelte-check and TypeScript, warnings fail
npm run lint    # ESLint
npm test        # unit tests (Vitest) for the API client, player maths, labels and settings
npm run build   # production build into dist/
npm run size    # fails if the first load is over 500 KB gzipped
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `VITE_BACKEND_URL` | `http://127.0.0.1:7860` | Backend used until the visitor saves another one |

Copy `.env.example` to `.env.local` to change it locally.

## Deploy on Cloudflare Pages

Create a Pages project connected to this repository with:

| Setting | Value |
|---|---|
| Root directory | `web` |
| Build command | `npm run build` |
| Build output directory | `dist` |
| Environment variable | `VITE_BACKEND_URL` = your Space, for example `https://<user>-<space>.hf.space` |
| Node version | 20 or later (set `NODE_VERSION` = `22` if the default is older) |

`public/_headers` gives the hashed assets a long cache life and keeps `index.html` fresh.
