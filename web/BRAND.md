# SoundStage brand (v3)

SoundStage should feel like a record shop you would want to stay in: warm paper in daylight,
charcoal at night, the same objects in both. Light is the default; dark follows the system setting
unless the listener chooses (Credits, Appearance: Light, Dark, System). Every value lives in
`src/styles/tokens.css`; this page says why.

## Colour

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | #faf8f5 | #15161b | Page. Warm white; charcoal, not black, so shadows still read |
| `--surface` | #ffffff | #1f2128 | Cards, sheets |
| `--text` | #1c1a16 | #f3efe8 | Body text |
| `--text-2` | #55504a | #b9b3a8 | Secondary text |
| `--text-3` | #6b655d | #9a948a | Captions and hints, never body copy |
| `--lagoon` | #07756a | #34d6c2 | Primary action, the spatial side, focus |
| `--coral` | #c4432a | #ff8a6d | The original side, warnings |

Lagoon means "spatial", coral means "original"; the A/B pill is where both meet. Contrast, WCAG 2.1
relative luminance, computed from the hex values above:

| Pair | Light | Dark |
|---|---|---|
| text on bg | 16.4 | 15.8 |
| text-2 on bg / surface | 7.5 | 7.7 (surface) |
| text-3 on surface | 5.8 | 5.3 |
| lagoon on bg | 5.3 | 9.9 |
| label on a lagoon button | 5.6 (white) | 9.3 (dark ink) |
| coral on bg | 4.7 | 7.8 |
| label on a coral button | 5.0 (white) | not used |

Text never goes below 4.5:1. The light lagoon is deliberately deep: the first version (#0e9f8e)
measured 4.27:1 and failed Lighthouse's contrast audit.

## Materials

The same three materials in both themes, so switching themes changes colour and not character.

- **Matte**: cards and the page, with a very fine noise grain (`--grain-opacity`, 4.5 percent in
  light, 7 percent in dark) so large flat areas do not band.
- **Glossy**: the play button and the active tab: a top highlight (`--highlight`) over the fill and a
  tinted shadow (`--shadow-play`) under it. It is the only glossy object on any screen, which is
  what makes it the obvious thing to press.
- **Translucent**: the mini player, the tab bar and sheets: `--overlay` with a 22 px backdrop blur
  and a hairline. Where `backdrop-filter` is missing they fall back to `--overlay-strong`, which is
  opaque enough to read on.

Elevation is three layered shadows (`--shadow-1..3`), each a tight contact shadow plus one or two
wide soft ones, never a single blur.

## Type

Instrument Sans for the interface, Instrument Serif for editorial headings (shelf titles, track
title on the now-playing screen). Both are SIL OFL and are in the credits. Sizes are a fixed scale
(`--text-xs` to `--text-hero`); the hero size is `clamp`ed so a 360 px phone never wraps a title.

## Motion

Springs sampled as CSS `linear()` easings: a critically damped one for movement (`--spring`) and a
slightly overshooting one for the play button (`--spring-bounce`). Under
`prefers-reduced-motion` every duration is 0 and the springs are linear, so nothing slides.

## The play button

A 64 px disc, lagoon fill with a top highlight and a coloured shadow, a rounded triangle or pause
bars drawn with rounded joins, a 94 percent press scale that springs back. It is the largest target
on the screen and the only element that casts a coloured shadow. Hit area is at least 44 px
everywhere it appears (mini player 44, now playing 64).

## Navigation

Phone: a bottom tab bar (Home, Browse, Library, Create, Credits) above the safe area, with the mini
player docked on top of it. At 900 px and wider the tab bar becomes a left rail (`--nav-w`) and the
mini player spans the content column. The now-playing screen opens as a sheet from the mini player
and always carries the Original and Spatial pill ("Spatial" is the filled lagoon state).

## Cover art

Remote cover art is loaded lazily, except the first shelf's first thumbnails, which load eagerly so
the largest paint does not wait. Where art cannot be read the tile is a gradient derived from a hash
of the track id (`src/lib/tint.ts`); a saved copy of a track keeps the original's `artId`, so its
cover does not change when it is saved.

## Measured

Lighthouse, mobile profile, median of 3 runs (`npm run lighthouse`, both themes): performance 0.98
(light) and 0.99 (dark), accessibility 1.00, best practices 0.96. Mid-range Android profile (4x CPU,
slow 4G; `node e2e/screens.mjs --profile`): first contentful paint 456 ms, largest contentful paint
732 ms, total blocking time 52 ms, 105 KB transferred, first shelf visible at about 2.0 s.
