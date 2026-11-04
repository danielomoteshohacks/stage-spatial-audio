# 0002. Rust real-time core with a Python reference as the oracle

- Status: accepted

## Context
The part that runs on a listener's device must be small, fast and portable.

## Decision
Write the real-time core in Rust (WebAssembly for the browser, native for phones). Keep a NumPy
reference implementation; the Rust core must match its golden files.

## Consequences
One code base across platforms, no garbage collector in the audio path, and an independent check
against mistakes. Cost: a Rust learning curve.

## Alternatives considered
C++ (equally fast, heavier web toolchain, memory-unsafe); Python only (cannot run in real time on a phone).
