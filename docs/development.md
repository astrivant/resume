# Development

Use Python 3.13+ and Poetry 2.5.1 in the existing checkout. Dependencies install
from `poetry.lock`; local checks and CI share the settings in `pyproject.toml`.

## Install and verify

```bash
poetry install --with dev
poetry run pre-commit install
poetry run pre-commit run --all-files
poetry run pytest --cov --cov-report=term-missing
poetry build
```

Tests run in parallel with pytest-xdist and combined coverage. Select a worker
count with `poetry run pytest -n 4`, or use `-n 0` for single-process debugging.
Hooks check Ruff, strict mypy, Google-style docstrings, schemas, ShellCheck, and
shfmt. For container-based development, see [local image builds](containers.md#build-locally).

## Package responsibilities

Implementation and tests live in `pkg/resumeme/`; repository tooling lives in
`scripts/`. `linkedin/` owns browser and network acquisition; `compiler/` owns
parsing, typed records, transformation passes, target resources, and compilation.
Runtime options remain in `config.py`. See the [compiler architecture](compiler.md).
See [pipeline and package ownership](README.md#pipeline-and-ownership), the
[profile schema](profile-schema.md), and the [template interface](templates.md).

## Document checks

CI runs [TeXtidote Action](https://github.com/marketplace/actions/textidote-action)
against the root README and generated LaTeX, with English spelling and grammar
checks. Download `textidote-reports` for annotated HTML; the job summary reports
finding counts. Prose findings are advisory; tool failures block publication.
See [document review](README.md#document-review) for the pinned image and review policy.
