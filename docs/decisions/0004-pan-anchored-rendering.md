# 0004. Pan-anchored rendering instead of template placement

- Status: accepted (subject to experiments H1, H3 and H5)

## Context
Template positions invent a stereo image. Research on stereo upmixing and headphone rendering
supports building on the image that already exists.

## Decision
Estimate each sound's position from the stereo image, preserve its order, widen it with a
monotone warp, set distance per role and treat ambience separately.

## Consequences
Faithful to the record and usable without any neural network. Weaker on time-panned and
spaced-microphone recordings (handled by a coherence gate) and on mono recordings.

## Alternatives considered
Template placement; a neural network that outputs the binaural mix directly.
