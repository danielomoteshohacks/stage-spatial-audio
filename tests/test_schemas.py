"""The JSON schemas are part of the contract between subsystems, so they are tested."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


@pytest.mark.parametrize("name", ["plan", "report", "consent"])
def test_schema_is_valid(name):
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name", ["plan", "report", "consent"])
def test_valid_example_passes(name):
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    example = json.loads((SCHEMAS / "examples" / f"{name}.valid.json").read_text())
    Draft202012Validator(schema).validate(example)


@pytest.mark.parametrize("name", ["plan", "report", "consent"])
def test_invalid_example_is_rejected(name):
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    example = json.loads((SCHEMAS / "examples" / f"{name}.invalid.json").read_text())
    errors = list(Draft202012Validator(schema).iter_errors(example))
    assert errors, f"{name}.invalid.json should violate the schema"
