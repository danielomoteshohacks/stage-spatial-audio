# SoundStage brand

SoundStage should look like something a person made with care, for listening at night on a
phone: quiet, deep, a little warm. Every value below lives in `src/styles/tokens.css`.

## Colour

| Token | Value | Use | Contrast on ink |
|---|---|---|---|
| `--ink` | #08090D | The background: night | |
| `--ink-2`, `--ink-3` | #0E1016, #151821 | Solid surfaces where glass would be busy | |
| `--glass` | rgba(22, 25, 34, 0.62) with a 22 px backdrop blur | Sheets, cards, the mini player | |
| `--ivory` | #F4F1EA | Text | 17.6:1 |
| `--ivory-2` | 72 percent ivory | Secondary text | 9.2:1 |
| `--ivory-3` | 56 percent ivory | Hints, captions (never body copy) | 5.8:1 (5.7 on glass) |
| `--lagoon` | #1FC8B4 | Primary actions, the spatial side, focus | 9.5:1; ink on lagoon 9.5:1 |
| `--coral` | #FF7A5C | The original side, warnings, warmth | 7.8:1 |

The two signature colours come from a Lagos lagoon at sunset: the water's luminous teal and the
coral of the last light. Lagoon means "spatial", coral means "original"; the A/B switch is the
one place both meet. Contrast ratios are WCAG 2.1 relative-luminance ratios against #08090D,
computed from the hex values; text never goes below 4.5:1.

On the now-playing screen the accent tokens (`--accent`, `--accent-2`) take colours from the
track's own cover art (`src/lib/palette.ts`), lifted in lightness until they keep the same
contrast floor; without artwork they stay lagoon and coral.

## Surfaces

Frosted glass: translucent fill, backdrop blur, a 1 px light hairline on the top edge only (light
falls from above), and the layered shadow `--shadow-2`. Radii are 10, 16 and 24 px; pills are
fully round.

## Type

Instrument Sans (interface) and Instrument Serif (editorial headings), both SIL Open Font
Licence 1.1, self-hosted from `@fontsource`, Latin subset only, `font-display: swap`. Display
text is never Inter or a system font. Headings in the serif, sentence case; numbers in the sans
with tabular figures.

## Mark and icons

The logo (`src/components/Logo.svelte`) is a stage arc made of concentric sound fronts: three
arcs opening upward around a point, the listener, with the innermost arc in lagoon. Icons
(`src/components/Icon.svelte`) are drawn on one 24 px grid with a 1.75 px round-capped stroke and
no fills, except the play and pause glyphs, which are solid for legibility at small sizes.

## Never

Purple-blue gradients, sparkle icons, generic blobs, emoji, stock phrases ("unlock", "elevate",
"seamless", "revolutionise", "AI-powered") and placeholder copy. Copy is short, specific and in a
person's voice.
