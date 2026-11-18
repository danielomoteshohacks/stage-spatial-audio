# stage-core

The real-time core in Rust, compiled to WebAssembly for the browser and to native libraries for
Android and iOS. It must match the Python reference's golden files.

Status: planned (slice 4). Targets: WebAssembly at most 300 KB compressed; Lite CPU load at most
5 percent of one mid-range phone core. See `docs/specs/` and `docs/decisions/0002`.
