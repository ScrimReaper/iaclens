# Contributing to infra-graph

Thank you for your interest in contributing.

## Before you start

- Check [open issues](https://github.com/parabvedang007/infra-graph/issues) to avoid duplicate work.
- For significant changes, open an issue first to discuss the approach.

## Development setup

```bash
git clone https://github.com/parabvedang007/infra-graph
cd infra-graph
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Running tests

```bash
pytest              # all tests
pytest tests/test_tf_parser.py -v   # one file
```

All tests must pass before a PR is merged. New features must include tests.

## Submitting a PR

1. Fork the repo and create a branch from `main`.
2. Write or update tests for your change.
3. Run `pytest` — all 65+ tests must pass.
4. Run `ruff check .` — no lint errors.
5. Open a PR with a clear description of what and why.

## Adding a new parser

1. Create `infra_graph/parsers/yourformat_schema.py` implementing the `SchemaParser` protocol:
   - `can_parse(path: Path) -> bool` — detect if the file is this format
   - `parse(path: Path) -> tuple[list[Node], list[Edge]]` — extract nodes and edges
2. Register it in `infra_graph/parsers/yaml_parser.py` (or `graph/builder.py` for non-YAML formats).
3. Add fixtures to `tests/fixtures/` and write tests asserting specific nodes and edges are extracted.
4. Add a row to the **Supported File Types** table in `README.md`.

## Worked examples

The most useful contribution is a worked example: run `infra-graph build` on a real IaC repo (anonymized if needed), save the output to `worked/{slug}/`, write an honest `review.md` covering what the graph got right and wrong, and open a PR.

## Code style

- Python 3.10+, type hints on all public functions.
- `ruff` for linting and import sorting.
- No external dependencies beyond what's in `pyproject.toml` without discussion.

## License

By contributing, you agree that your contributions are licensed under the MIT License.
