# 0013. Binaural rooms: image sources, a multiband FDN, and the measured studio as reference

- Status: accepted
- Date: 2026-11-24

## Context

v1 sounded dry: its room was off by default (decision 0007 dropped the late field after its
timbre gate failed) and its reflections went through the toy head. Envelopment needs
reflections from around the listener, and a late field with the right decay and the right
coherence between the ears.

## Decision

`stage.spatial.room` builds a binaural room impulse response per source:

- **Image sources** of a shoebox (Allen and Berkley 1979) up to order 2 or 3. Each image has its
  own direction through the measured head, its distance delay, 1/r spreading, per-octave wall
  absorption, and air absorption along its extra path from the ISO 9613-1:1993 equations
  (20 C, 50 % RH: 4.7 dB/km at 1 kHz, 105 dB/km at 8 kHz, matching the standard's table).
  Wall absorption is derived from the preset's target RT60 with Eyring's formula, so the early
  and late parts describe the same room.
- **Late field** from the existing Hadamard FDN, run once per octave with that octave's T60 and
  joined by complementary raised-cosine band weights. Its leading silence (the shortest delay
  line, 23 ms) is cut so the decay has no gap. The two outputs are power-balanced per 1/3 octave
  and mixed to the **diffuse-field interaural coherence of the KU100, measured from the pack**
  (Menzer and Faller 2009 mixing), not the free-field sin(kd)/kd.
- **Level** of the reverberant part from Sabine's critical distance, DRR = (r_c / r)^2, times a
  per-space `reflection_level_db`.
- **Spaces** (`configs/spaces/spaces.json`): studio, living room, car, club, concert hall,
  cinema, each with dimensions, listener position, absorption bias, target RT60 per octave and
  the reasoning. Generic names only.

## Calibration against the measured SADIE II BRIRs

SADIE II ships 50 BRIRs of the KU100 in the York studio (0.3 s each). They are published as
`sadie2-d1-brir48k.npz`; `scripts/calibrate_rooms.py` compares them. The measured room is much
drier than diffuse-field theory predicts for its decay (treated rooms are not diffuse), so the
studio preset takes the measured RT60 per octave and a reflected level of -12.7 dB, fitted to the
frontal DRR. Then, without further fitting:

| Azimuth | DRR measured / synthetic (dB) | EDT measured / synthetic (s) | IACC_E measured / synthetic |
|---|---|---|---|
| 0 | 11.5 / 11.4 | 0.009 / 0.003 | 0.75 / 0.83 |
| 45 | 10.7 / 11.5 | 0.006 / 0.006 | 0.46 / 0.45 |
| 90 | 12.3 / 11.5 | 0.006 / 0.003 | 0.39 / 0.28 |
| 135 | 9.9 / 11.4 | 0.008 / 0.008 | 0.51 / 0.46 |
| 180 | 6.5 / 11.0 | 0.088 / 0.003 | 0.80 / 0.88 |

DRR is within 1 dB except behind the head (4.5 dB too dry: the measured room has a strong rear
reflection the shoebox model does not); IACC within 0.12; EDT is direct-dominated in both except
at 180 degrees. Only one measured room exists, so the other five spaces are validated by their
RT60 alone.

## Measured RT60 (Schroeder T30, target / measured, seconds)

| Space | 125 | 250 | 500 | 1k | 2k | 4k | 8k |
|---|---|---|---|---|---|---|---|
| studio | 0.21/0.26 | 0.22/0.21 | 0.15/0.19 | 0.12/0.12 | 0.10/0.10 | 0.09/0.10 | 0.09/0.09 |
| living room | 0.65/0.66 | 0.58/0.61 | 0.50/0.49 | 0.45/0.45 | 0.42/0.42 | 0.38/0.38 | 0.32/0.32 |
| car | 0.12/0.15 | 0.10/0.10 | 0.08/0.10 | 0.07/0.07 | 0.07/0.07 | 0.06/0.06 | 0.05/0.05 |
| club | 1.30/1.31 | 1.10/1.08 | 0.95/0.96 | 0.90/0.90 | 0.85/0.84 | 0.75/0.74 | 0.60/0.62 |
| concert hall | 2.40/2.40 | 2.20/2.21 | 2.00/2.01 | 1.95/1.94 | 1.80/1.78 | 1.50/1.51 | 1.10/1.15 |
| cinema | 0.85/0.91 | 0.75/0.77 | 0.65/0.65 | 0.60/0.59 | 0.58/0.57 | 0.55/0.53 | 0.48/0.48 |

`tests/unit/test_room.py` requires 15 percent plus 30 ms, except where the octave's bandwidth
times RT60 is below 16 (Jacobsen 1987), where an octave filter cannot resolve the decay and the
value is only an upper bound (car and studio at 125 Hz).

## What went wrong and was fixed

- The FDN's first output comes after its 23 ms shortest line; in a 0.1 s room that gap flattened
  the decay curve (studio 4 kHz read 0.15 s against 0.09). The leading silence is now cut.
- The two FDN outputs had up to 3 dB power difference per band, so the coherence mix gave 0.59
  where the KU100 has 0.35 at 350 Hz. A smooth per-band power balance fixed it (test within 0.1).
- Frequency-domain shaping of the very short car response wrapped round (car 1 kHz read 1.4 s);
  shaping now runs on a zero-padded response.
- In the car the right virtual loudspeaker sat 15 cm from the door; its reflection combed the
  treble. The listener now sits on the centre line. The car still reads 5.8 dB at 8 kHz on the
  test signal (guard: review).

## Sources

ESTABLISHED: Allen and Berkley 1979; ISO 9613-1:1993 equations (implemented from the standard's
formulae and checked against its 1 kHz and 8 kHz table values); Eyring 1930; Sabine's critical
distance; ISO 3382-1:2009 for T30, EDT and IACC; ITU-R BS.1116-3 for control rooms. Jot and
Chaigne 1991 and Menzer and Faller 2009 as already cited in decision 0007. The SADIE II BRIRs were
measured here. SPECULATIVE: the RT60 targets of the living room, club and cinema are typical
values from the literature cited in the presets, not measurements of particular rooms.

## Patents

None identified for image sources, FDNs with per-band absorption, or coherence mixing of two
uncorrelated reverberators.
