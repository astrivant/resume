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

## Publish to PyPI

The package is named [`resumeme`](https://pypi.org/project/resumeme/). Pushing a
version tag runs the shared test/build gate, then `stage-pypi.yml` publishes the
verified wheel and source archive using Poetry 2.5.1. Publishing downloads the
`resumeme-python-distributions` artifact from the same run; it does not rebuild or
resolve application dependencies. The container remains a separate tag stage.

Grant this repository access to the organization secret **`PYPI_API_TOKEN`**.
A repository secret or a secret in the **`pypi`** GitHub environment also works.
The publish step maps it to Poetry's **`POETRY_PYPI_TOKEN_PYPI`** environment
variable. The token must authorize uploads to `resumeme`; the first upload needs
a token permitted to create the project. Resume-only forks do not need this token.
Environment protection rules apply before the publishing job starts.

Set and commit the version before tagging. Tags must exactly match the committed
`project.version` prefixed with `v`; for example, version `0.1.0` uses `v0.1.0`, and
`0.2.0rc1` uses `v0.2.0rc1`.

```bash
# For the initial 0.1.0 release, commit the reviewed release changes first.
poetry check --lock
git tag v0.1.0
git push origin v0.1.0
```

For later releases, run `poetry version <version>`, commit the metadata, and push
the corresponding tag. Non-version tags, ordinary pushes, manual runs, and pull
requests do not upload to PyPI. Missing credentials, mismatched versions, or
missing distributions fail publication. Transient upload failures use exponential
backoff; reruns skip files PyPI already accepted. Changed package contents require
a new version.

After the first successful publication, users can install the CLI with Python
3.13+ and verify it:

```bash
pipx install resumeme
resumeme --help
```

Firefox and the PDF toolchain are still required for capture and compilation; see
the [runtime prerequisites](README.md#install).

## Document checks

Use keyboard punctuation in prose, comments, CLI messages, and templates: `-`,
straight quotes, `...`, and `->`. Accented words and names are welcome. Express
Unicode parser delimiters and test cases with code-point escapes or HTML entities;
keep captured profile data lossless. Rendering normalizes editorial punctuation
without removing accents or meaningful symbols such as list bullets.

CI runs [TeXtidote Action](https://github.com/marketplace/actions/textidote-action)
against the root README and generated LaTeX, with English spelling and grammar
checks. Download `textidote-reports` for annotated HTML; the job summary reports
finding counts. Prose findings are advisory; tool failures block publication.
See [document review](README.md#document-review) for the pinned image and review policy.
