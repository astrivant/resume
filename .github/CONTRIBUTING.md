# Contributing

Thanks for contributing to resumeme. Start with the [README](../README.md) for the
project overview, then use the [development guide](../docs/development.md) for the
supported Python environment, CI behavior, and detailed checks.

## Local checks

Install the locked development dependencies and hooks, then run the same checks
used before merging:

```bash
poetry install --with dev
poetry run pre-commit install
poetry run pre-commit run --all-files
poetry run pytest --cov --cov-report=term-missing
```

The [test layout](../pkg/resumeme/tests/README.md) documents focused commands and
the browser end-to-end suite. The [CLI reference](../docs/CLI.md) covers config
validation and local capture or build commands.

## Pull requests and security scans

Pull requests must pass the required `CI verification` check. Its test stage runs
Trivy for dependency vulnerabilities and secret patterns. Findings or scanner and
report errors fail the check. A follow-up workflow posts a concise comment with
finding counts and links to the sanitized report and run logs. See the
[security policy](SECURITY.md#automated-source-scanning) and
[pipeline documentation](../docs/automation.md#trivy-security-scan) for scan scope,
report handling, and limitations.

Report security vulnerabilities through the private process in
[SECURITY.md](SECURITY.md), not a public issue. Do not include real LinkedIn
credentials, session data, signing keys, or another person's profile data in
issues, pull requests, or test fixtures.

## Dependency and tool updates

Python dependencies belong in `pyproject.toml` and `poetry.lock`. Update the
external action, image, and tool pins at their source, then update the
[development inventory](../docs/development.md#pinned-toolchain-and-ci-dependencies)
in the same change. GitHub Actions should remain pinned to full commit SHAs, and
base images should use immutable digests where supported. Explain any pin that
remains tag-based in the inventory.

Keep user-facing behavior and operations documentation aligned with changes.
The [documentation index](../docs/README.md) links to configuration, capture,
rendering, publication, and security references.
