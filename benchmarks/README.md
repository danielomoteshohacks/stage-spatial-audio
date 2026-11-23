# benchmarks

Reproducible performance measurements: seconds of compute per minute of audio per stage, real-time
factor of the renderer, memory, and the size of built artefacts. Results are published with the
machine description.

`pipeline_run.py` times one pipeline run on a generated test track and reports peak memory:

```bash
python benchmarks/pipeline_run.py --seconds 10 --profile max
```

Status: active for the Python pipeline (results in [`docs/log.md`](../docs/log.md)); the Rust and
WebAssembly measurements are planned (slice 4).
