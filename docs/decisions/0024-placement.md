# 0024. Where each part goes: placement principles, from data

- Status: accepted
- Date: 2026-11-24

## Research (read before designing; tags as in the separation record)

What working Atmos mixers say (secondary reports of interviews and guides; the Dolby Atmos Music
delivery playbook and the Sound On Sound "Mixing Atmos" series could be searched but their full
text was not retrieved here, so the near/mid/far point below is **unverified against a Dolby
primary source**):

- Kick, snare, bass and the lead vocal usually stay front and centre; a mixer starts from the
  vocal where it feels immediate and builds the rhythm section around it (Bob Clearmountain,
  AudioTechnology and Music Connection interviews). Giles Martin avoids a hard-centre vocal so it
  sits in a space (Rolling Stone). ESTABLISHED as practice, reported second-hand.
- Drums and most vocals in front; power chords in front on rock songs; acoustic guitars mainly
  at the sides (Clearmountain). Backing vocals top-rear or panned low, strings high (Vintage King
  guide; Darrell Thorp on the Foo Fighters mix, via Avid). ESTABLISHED as practice.
- Beds are static and mapped to speakers; objects are point sources. Dolby's game-music guidance
  puts volumetric material (pads, reverbs, textures) in the bed and uses objects for sources that
  benefit from a point location (lead and melody instruments). Hence v3: every leaf an object,
  and only diffuse content (the returned reverb) treated as a bed. ESTABLISHED.
- Binaural render modes "near, mid, far" (a per-object distance setting of the Dolby binaural
  renderer): guides advise dry lead vocals near or off and backing vocals mid or far, and
  keeping objects at the outer boundary, only moving them inward as an effect. Single secondary
  source, UNVERIFIED. v3 expresses the same idea with distance: lead 1.0 m, backing 1.9 m,
  pads 2.6 m, through level, air absorption and the reflection level (decision 0025).

What the binaural literature says (the reasons for a dry stage with a few reflections):

- Early reflections help externalisation and can reduce front-back confusion with non-individual
  HRTFs, but one reflection does not remove all confusions, and a lateral reflection can help or
  hurt depending on the geometry (Reed and Maher, "Evaluation of the effect of reflections on
  front-back confusion with non-individualised HRTFs", AES). Adding early reflections and
  reverberation to a dummy-head baseline improves externalisation (Rajendran et al., JASA Express
  Letters 145(3), 2019, which also treats elevation with non-individual HRTFs by spectral
  manipulation). ESTABLISHED.
- Head tracking reduces front-back reversals and individual HRTFs add little over non-individual
  ones when it is used; without tracking (v3's case) the cost of non-individual HRTFs is larger
  (reviews cited in arXiv 2606.30114, which also reports 17 percent front-back confusion for a
  KEMAR set against 8 percent for measured individual HRTFs, and near-zero elevation correlation
  for the KEMAR in the median plane). ESTABLISHED, as reported there.
- Elevation and front-back cues sit in the pinna and head spectral cues; Blauert's directional
  bands (1969; Spatial Hearing, 1997) name the bands that favour front, above and behind.
  ESTABLISHED; using them to *boost* is SPECULATIVE and bounded to 2 dB (decision 0025).

## Decision

Placement is data, not code: `configs/placement/roles.json` (every role's mode, azimuth,
elevation, distance, whether it breathes, its events, and the source of its rule in the `why`
field) and a `v3` block in each genre template (stage width, height, rear, return level, motion,
lead distance), scaled by the listener's character. Azimuths are positive to the left.

| Role | Placement | Notes |
|---|---|---|
| Lead vocal | front centre, +7 degrees, 1.0 m | never moves; raised so it leaves the head |
| Kick, snare, bass | front, 0 degrees | never move |
| Hats and cymbals | pair at +/-30, elevation 38 | above and slightly forward |
| Toms | pair at +/-50, elevation 8 | fills sweep across (event `fill`) |
| Backing vocals | pair or side at +/-100, elevation 12 | breathe: wider in choruses |
| Guitars | pair at +/-75 (side: +/-78) | double-tracked left and right parts become wide pairs |
| Keys | pair at +/-38, elevation 6 | front-wide |
| Pads, strings, synths | pair at +/-125 (side: +/-130), elevation 30 | wrap, rear and height; lift on risers |
| FX, throws, ad-libs | rear overhead, 180 degrees, elevation 50, 2.5 m | risers climb, throws fly to the rear |

**Dynamics.** Objects marked `breathes` pull to 60 percent of their azimuth and elevation in
quiet sections and open to the full position in loud ones, by the genre's section openness (the
table already in each template), cross-faded over a bar and scaled by the listener's motion
depth: verses intimate, choruses and drops the full sphere.

**Events** (`stage.scene3.events`) are detected from the leaves and snapped to the beat grid:
risers (an effects envelope rising 6 dB or more over at least a second; the pads lift with it), tom
fills (a sweep from one side to the other, alternating direction), delay throws (an isolated
burst on the effects leaf flies to the rear and back). Every path is eased with smoothstep;
speed is capped at 90 degrees per second and range at 100 degrees for events, 45 degrees per
second for any ambient motion (the v2 cap, from the auditory-vection literature, Valjamae 2009).
The cap reduces *amplitude*, never timing: a move must land on the beat. These thresholds are
SPECULATIVE; they are in `roles.json` so listening tests can change them.

## Genre contrast

Afrobeats, amapiano, hip-hop, R&B, gospel, house, pop, rock, acoustic and classical differ in
stage width (0.8 to 1.2), height (0.5 to 1.2), rear wrap (0.4 to 1.3), returned ambience (0.8 to 1.5)
and motion appetite (0.2 to 1.3); the reason for each is in its template's `v3.why`.

## Limits

The generated ground-truth songs place their leaves by the same published practice, so the
angular-error numbers in decision 0027 measure agreement with *this* convention on synthetic
songs, not with any particular mixer's choices on real songs. Only a listening test can say
whether the placements are liked.
