# 0003. Apache-2.0 licence for the code

- Status: accepted

## Context
The project should be easy for anyone, including companies, to evaluate and try.

## Decision
License the code under Apache-2.0. Model weights and datasets keep their own licences, recorded in
`models/MANIFEST.md` and `data/manifest.example.csv`.

## Consequences
Permissive reuse and an explicit patent grant. A licence does not stop others from using the ideas;
publication gives a dated record of authorship. Contributions to GPL projects (for example
Pedalboard) are made under their licence.

## Alternatives considered
GPL-3.0 (strong copyleft, discourages company evaluation); all rights reserved (hard to evaluate).
