# schemas

JSON Schemas (draft 2020-12) for the files that subsystems exchange: the mix **plan**, the
quality **report**, the **consent** record, and the **run** report that
`stage.pipeline.run` writes as `run.json` for every processed track. They are the contract between stages, so they are
validated by tests (`tests/test_schemas.py`). Each schema has one valid and one invalid example in
`examples/`.

Status: active.
