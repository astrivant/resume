# Test suite layout

The suite is grouped by the subsystem a maintainer is changing. Pytest still discovers every group from the configured test root.

| Directory | Coverage |
| --- | --- |
| `compiler/` | Profile transformations, section layout, links, themes, and LaTeX/PDF output |
| `configuration/` | Config and profile schemas, CLI validation, and the config pre-commit hook |
| `delivery/` | GitHub releases, PyPI publication, README output, and Pages deployment |
| `linkedin/` | Browser capture, login, session reuse, profile refresh, and account updates |
| `operations/` | Runtime errors, telemetry, and test sharding |

Run one area with `poetry run pytest pkg/resumeme/tests/<directory>`. For example:

```bash
poetry run pytest pkg/resumeme/tests/compiler -n 4
poetry run pytest pkg/resumeme/tests/linkedin -n 4
```

Target an individual module by passing its path, such as
`poetry run pytest pkg/resumeme/tests/compiler/test_pipeline.py`.

Browser end-to-end coverage remains opt-in and uses local deterministic fixtures:

```bash
RESUMEME_E2E_BROWSER=firefox poetry run pytest pkg/resumeme/tests/linkedin/test_browser_e2e.py -m browser_e2e -n 0
RESUMEME_E2E_BROWSER=chrome poetry run pytest pkg/resumeme/tests/linkedin/test_browser_e2e.py -m browser_e2e -n 0
```
