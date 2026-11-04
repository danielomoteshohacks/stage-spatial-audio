# 0001. Three complete tiers: Lite, Standard, Studio

- Status: accepted

## Context
The project is large. Cutting features until a weak minimal version remains would lose the ambition.

## Decision
Build the same product three times, from lightest to richest. Every tier uses the same plan file,
guard and interface. Lite needs no neural network and runs in real time on the device.

## Consequences
Graceful degradation, a portable baseline, and a clean ladder of comparisons: each tier must beat
the previous one in blind tests to earn its cost.

## Alternatives considered
A single full pipeline (fragile, heavy); a cut-down minimal version (loses the ambition).
