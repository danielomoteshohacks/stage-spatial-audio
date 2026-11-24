# web

SoundStage in the browser: drop a song, watch it being built, then listen to the original and the
spatial render in perfect sync, move the parts around you, and keep renders on your phone.
Svelte 5, Vite and TypeScript, mobile first (designed at 412 CSS px, a Galaxy S21 FE). The brand is
documented in [`BRAND.md`](BRAND.md); the product decisions in
[decision 0020](../docs/decisions/0020-product.md).

## What it does

- Home: drop zone, quick (no separation) option, the space, and renders kept on this device
  (IndexedDB) so replaying one never downloads anything.
- Now Playing: cover art read from the file's own tags with colours taken from it, the
  Original/Spatial switch (sample-locked, 30 ms cross-fade), waveform with seek and loop,
  Space, Character, Motion and Genre applied through `/rerender` (no upload), solo and mute
  per part, the fidelity guard's verdict, downloads.
- The stage view (loaded on demand): every part around your head, moving with the music;
  drag one, raise it, re-render.
- Feel: vibration on the kick (Android); Media Session controls; installable (PWA); keyboard:
  Space, S, arrows, [ and ], L.
- Blind test (loaded on demand): A/B/C in random order, loudness-matched, CSV export.

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
npm run size    # fails if the first load (fonts included) is over 250 KB gzipped
npm run lighthouse  # mobile Lighthouse; fails under 0.9 for performance or accessibility
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
