# 0028. The streaming catalogue: only music that may be adapted, verified, with its credit

- Status: accepted
- Date: 2026-11-25

## Decision

**What is offered.** Only music under a licence that permits adaptation, because spatialising a
song is an adaptation: CC BY, CC BY-SA, CC0 and the Public Domain Mark. Every NoDerivatives licence
(CC BY-ND, CC BY-NC-ND) is excluded; NonCommercial ones (BY-NC, BY-NC-SA) are excluded by default
so the catalogue is usable by anyone running the project and not only by a non-commercial demo
(`allow_nc` turns them on, and the credits then say so). The licence is checked twice: by the
source's filter (Openverse `license_type=commercial,modification`) and again by
`stage.catalogue.licences.accepted`, because a filter is not a guarantee. A track that needs
share-alike carries that in its attribution line, and so does its pre-rendered copy.

**Where it comes from** (`stage.catalogue.sources`):

- **Openverse** (no key at low rates; the headers say 20 requests a minute and 200 a day for
  anonymous callers, which the client respects). It searches Jamendo's catalogue, with genre tags
  and cover art. `wikimedia_audio`, `freesound` and `ccmixter` returned nothing usable for music
  under the licence filter in the runs made here (or a server error), so they are not relied on.
- **Jamendo API v3**, free for non-commercial use with a `client_id`: read from the environment
  variable `JAMENDO_CLIENT_ID` on the Space, never committed, never sent to the browser. A track
  whose `audiodownload_allowed` is false is skipped, and the licence comes from `license_ccurl`.
  How to get a client id: register an application at developer.jamendo.com and copy its client
  id into the Space's secrets. Without it the catalogue runs on Openverse alone.
- **Internet Archive** netlabel releases (CC BY, BY-SA, CC0) have an adapter and tests, but the
  audio hosts (numbered archive.org servers) could not be reached from the build environment, so
  no track from it could be verified and none is in the committed seed.
- The Free Music Archive's API terms could not be read from the build environment; it is not
  called. Wikimedia Commons music is reached through Openverse.

**Shelves** (`configs/catalogue/shelves.json`): Afrobeats and Afro-fusion, Amapiano, hip-hop,
R&B and soul, gospel, house and electronic, lo-fi, cinematic, acoustic, classical, and Made for
spatial. A track is placed on a shelf by its own genre tags and never by a search hit alone (the
first harvest put "Classic Rock CDs In A Giant Bonfire" on the classical shelf and a darkwave
track called "Gospel of Wealth" on the gospel shelf); each shelf also lists tags that keep a track
off it. At most two tracks per artist per shelf. Search, genre pages (with more of the genre from
the sources) and artist pages are routes of the backend (`/catalog/...`).

**The committed seed** (`configs/catalogue/seed.json`, built 2026-11-25): 115 tracks, 33 CC BY and
68 CC BY-SA 3.0 and the rest CC BY 2.0 or CC BY-SA 2.0 and 2.5, all from Jamendo through Openverse,
every one with its creator, album, artwork link, landing page, licence, attribution line and a
check that its audio URL answered with audio. The catalogue refreshes itself in the background on
the Space; the seed is what it serves until that finishes and when a source is down. "Made for
spatial" is, for now, chosen from genre tags that favour wide, layered arrangements (ambient,
cinematic, orchestral, electronic, world): it will be replaced by the pre-render analysis (stereo
width and the number of separable parts) once those runs exist.

**Playing and rendering.** The backend proxies the original audio (`/audio/{id}`, Range
supported, only for tracks it listed itself, only from approved hosts) so the browser can decode
it for the sample-locked Original / Spatial switch without CORS limits. A track not yet rendered
is rendered on demand by `POST /v3/jobs/from-catalog` (or the Gradio event `v3_catalog`, which
is what the Space uses so ZeroGPU quota is charged to the listener): the server downloads it, the
listener uploads nothing.

**Pre-rendered catalogue.** `scripts/render_catalogue.py` renders the first five tracks of each
shelf and writes, per track, the Opus segments, plan, report and a manifest carrying the licence
and attribution, then uploads them to the dataset `danieltesh/soundstage-catalogue`. The `catalogue`
workflow runs it weekly on GitHub's CPU runners in four parts with the `cpu` preset, and by hand
for any preset. Curated tracks then play with no GPU: the backend reads the dataset's `index.json`.
**This is built and tested but has not run**: it needs the owner's Hugging Face write token as the
repository secret `HF_TOKEN`; until then the dataset does not exist and every track renders on
demand. The first render used by the web app will not say "pre-rendered" until it does.

**Legal page** (`/catalog/legal` and the app's Credits screen): what is streamed, from where, under
which licences and what each asks of the render; that only openly licensed music is offered; that
a track can be reported and is removed.

## Limits

- 115 tracks from one source: the breadth is Jamendo's, and Jamendo's independent artists are not
  a mainstream catalogue. Afrobeats and amapiano in particular are thin (many "amapiano" results
  are deep house; the shelf is honest about it in its genre tags, not its title).
- Openverse has no popularity signal, so "best" is: tagged for the shelf, has artwork, found by
  more of the shelf's terms, within 90 to 480 s, one of at most two by an artist. It is not a
  listener-rated ranking; Jamendo's own popularity ordering is used when the client id is set.
- The licence on the source's page is what governs; the seed is a snapshot, and the credits link
  to each track's page.
