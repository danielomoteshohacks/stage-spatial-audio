# 0006. Lite renderer: sector gains are w (not sqrt(w)), weights use the original angle

- Status: accepted (measured; revisit when the room and distance stages are added)

## Context
The sector weights sum to 1 in power, which suggests an amplitude split of sqrt(w). But the
renderer splits one primary signal into 13 coherent copies that are filtered and summed at each
ear, so they add as amplitudes, not powers. Measured on 200,000 random complex bins (beta 2.0):

| split | per-sector power sum, before filtering | amplitude sum | through head filters, both ears |
|---|---|---|---|
| sqrt(w) | 0.00 dB | +3.89 dB | +6.32 dB |
| w | -2.46 dB | 0.00 dB | +2.59 dB |

A single filter at each bin's exact widened azimuth gives +2.75 dB. w is 0.16 dB from that and
sqrt(w) is 3.57 dB from it (tests/unit/test_renderer_split.py).

## Decision
- Use w as the amplitude gain. The private `_split` flag keeps sqrt(w) available for measurement.
- Compute the weights from the bin's original stereo angle and render each sector at its widened
  centre (`sector_azimuths(beta)`). The weights are Gaussians on the un-widened grid, so weighting
  on a widened angle would pile everything past about 20 degrees onto the edge sector.
- Scale the ear filters by 1/sqrt(2). The head model gives each ear unit gain at low frequencies,
  so a primary that shared its power over two speaker channels arrives with twice the power.
  Measured total power change on 4 s pink noise, before and after: +1.5 to +3.4 dB, then
  -0.9 to +0.4 dB.

## Consequences
Level is roughly conserved overall, but the head model is not flat. Total ear power relative to
the primary at 8 kHz, with the 1/sqrt(2) scaling: -2.4 dB for a centred source, -0.4 dB at 15
degrees, +1.6 dB for a hard-right source (beta 2.0); within 0.1 dB of 0 at 100 Hz. That is a
timbre change for the fidelity guard to bound, not a level error. Interpolating complex filters of
neighbouring sectors whose delays differ can cancel a little at high frequencies; not yet measured.
(Measured in 0009: far-ear notches of 17 to 25 dB halfway between sector centres, at most 2.1 dB
per 1/3 octave with both ears' power summed.)

## Alternatives considered
sqrt(w) with a normalising divisor; blending sector azimuths into one filter per bin (exact, but
13 times the filter design work per bin).
