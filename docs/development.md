# Development

Use Python 3.13+ and Poetry 2.5.1 in the existing checkout. Dependencies install
from `poetry.lock`; local checks and CI share the settings in `pyproject.toml`.
Dependency constraints allow patch releases within the tested major/minor lines.
Use `poetry update` to refresh the lockfile; major/minor upgrades require updating
those constraints and rerunning the checks below. CI installs the committed lockfile.

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
The [test suite layout](../pkg/resumeme/tests/README.md) maps subsystem folders to
targeted pytest commands.
Hooks check Ruff, strict mypy, Google-style docstrings, schemas, ShellCheck, and
shfmt. For container-based development, see [local image builds](containers.md#build-locally).

## Repository layout

The root keeps the README, license, published PDF, active `resumeme.config.yaml`,
and files used by native packaging, Git, Docker, version managers, and pre-commit.
Supporting files live beside their owning subsystem:

| Location | Contents |
| --- | --- |
| [`.config/`](../.config/) | Homebrew dependencies, ESLint configuration, and the copyable reference résumé config |
| [`.github/`](../.github/) | Actions, repository settings, and GitHub's security and contribution guides |
| [`docs/`](./) | Usage and development documentation, including the generated fork example |
| [`output/release/`](../output/release/) | Complete signed PDF bundle: PDF, signatures, public key, fingerprint, checksums, and provenance |
| [`pkg/resumeme/tests/`](../pkg/resumeme/tests/) | Tests and the sharding plugin loaded explicitly through `pyproject.toml` before pytest parses arguments |

Copy `.config/resumeme.config.ref.yaml` to the root as `resumeme.config.yaml`
before using it; output paths remain relative to the active configuration.
Homebrew uses `--file .config/Brewfile`. Pre-commit and the workspace editor
select `.config/eslint.config.mjs` explicitly, with file patterns relative to the
repository root. The published pre-commit hook manifest remains at its required
root path, `.pre-commit-hooks.yaml`.

### Python packages

Modules with a shared responsibility live in a subpackage rather than repeating
a filename prefix. Imports name the implementing module; package initializers
stay small. `resumeme.config` exposes the configuration models and loading API.

| Package under `pkg/resumeme/` | Responsibility |
| --- | --- |
| `config/` | Typed models and validated configuration loading |
| `linkedin/browser/` | Browser lifecycle, authentication, and JavaScript resource loading |
| `linkedin/capture/` | Profile traversal, shard plans, aggregation, timings, and scheduling feedback |
| `linkedin/resume/` | PDF publication, saved-resume management, uploads, and recruiter sharing |
| `linkedin/approval/` | Sign-in approval audit context |
| `linkedin/session/` | Encrypted browser session archives |
| `compiler/asts/skills/` | Skill parsing and generated proposal models |
| `compiler/passes/projects/` | Project consolidation, description separation, and tile layout |
| `github/companies/` | Employer-specific PDF artifact transfer |

Tests keep their standard `test_*.py` filenames within the existing subsystem
directories. Standalone JavaScript resources remain in `linkedin/scripts/`.

### CI scripts

[`scripts/ci/`](../scripts/ci/) groups entry points by responsibility. Run them
from the repository root; config and artifact paths are relative to that working
directory. Workflows and composite actions call these scripts directly.

| Directory | Responsibility |
| --- | --- |
| [`pipeline/`](../scripts/ci/pipeline/) | Select the source commit and profile-refresh mode |
| [`checks/`](../scripts/ci/checks/) | Run lint/tests, generate coverage badges, and redact/report Trivy findings |
| [`linkedin/`](../scripts/ci/linkedin/) | Manage encrypted sessions, capture timing feedback and profile artifacts, and publication opt-ins |
| [`codex/`](../scripts/ci/codex/) | Prepare summary/skill inputs and validate generated response artifacts |
| [`resume/`](../scripts/ci/resume/) | Render, compile, stage, and restore PDFs; prepare TeXtidote inputs |
| [`publication/`](../scripts/ci/publication/) | Commit accepted artifacts to main and update README previews and branding |
| [`pages/`](../scripts/ci/pages/) | Resolve settings, deploy the accepted commit with OIDC, and verify the live PDF hash |
| [`containers/`](../scripts/ci/containers/) | Check the built image and push its registry tags |

Release signing and distribution remain in [`scripts/release/`](../scripts/release/).
Shared environment setup and retries live in [`scripts/tooling/`](../scripts/tooling/);
local validation hooks live in [`scripts/validation/`](../scripts/validation/).

## Local commits and CI-owned files

[`.gitattributes`](../.gitattributes) marks published PDFs, captured profile/media,
the `output/release/` signing bundle, and generated presentation assets with `ci-generated`.
This metadata lets compatible local Git shortcuts exclude CI-owned output from
routine source commits. Native Git commands and CI publication are unaffected.
Keep these attributes aligned with configured output paths. The authored README
remains source because its generated branding shares the file with maintained docs.

Stage source paths explicitly for routine changes. Preserve local generated
previews before pulling CI's published versions. For intentional manual
publication, review and stage the complete PDF/signature bundle together.
Intentional edits to the same generated paths can still conflict.

## CI environment caches

The shared [project setup action](../.github/actions/setup-project/action.yml)
restores installed environments before doing installation work:

| Cache | Contents | Reuse boundary |
| --- | --- | --- |
| `resumeme-poetry-v1-*` | Dedicated Poetry runtime under `$RUNNER_TEMP/resumeme-poetry` | Pinned Poetry version, Python runtime/ABI, OS release, architecture, absolute paths, and setup implementation |
| `resumeme-project-v1-*` | `.venv` with locked dependencies, saved before installing resumeme | Same compatibility inputs plus `poetry.lock`, `pyproject.toml`, project setup implementation, and `main` versus `main,dev` |

Exact hits skip package downloads and dependency installation. Every project
setup still runs `poetry check --lock`, then installs only the current checkout
with `poetry install --only-root`. That local operation refreshes the editable
package, entry points, and metadata without fetching dependencies. Profile data,
PDFs, and application source are not restored from these caches. The PyPI job
uses the same Poetry cache without installing application dependencies.

On misses, Poetry synchronizes the selected groups from the committed lockfile
without resolving newer versions. Each environment is saved immediately after
successful setup, before tests or credential-bearing operations. There is no
cache warmup dependency between otherwise independent jobs. Concurrent cold jobs
can install simultaneously; subsequent jobs and runs reuse the completed cache.
Installed environments have no partial-key fallback because incompatible paths,
interpreters, or dependency selections can produce invalid executables.

GitHub scopes caches by branch/tag and permits default-branch fallback. Pull
request caches do not populate `main`; sibling tags cannot restore one another's
caches. Eviction, quota, and runner/path changes can still cause cold installs.
Caching is an optimization, not a prerequisite for a successful build. See
[GitHub's cache scope and retention rules](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching).
Delete the relevant cache or bump its `v1` namespace in
[`cache-keys.py`](../scripts/tooling/cache-keys.py) to force replacement.

Only the two environment directories are archived. Their packages are not
encrypted by resumeme; never put credentials or browser state inside them.
Docker layers and the six-hour Trivy database cache remain separate, as does the
[encrypted LinkedIn session cache](linkedin-session-cache.md). See
[dependency cache data handling](data-handling.md#dependency-environment-caches).

## Pinned toolchain and CI dependencies

Python application and development packages are specified in
[`pyproject.toml`](../pyproject.toml) and resolved by
[`poetry.lock`](../poetry.lock). The following external tools, images, and GitHub
Actions are pinned separately. The listed files are the source of truth; update
this inventory in the same change whenever one of those pins changes.

### Toolchain and images

| Component | Pin | Source |
| --- | --- | --- |
| Local and Actions Python | `3.13.12` | [`.python-version`](../.python-version), [`.tool-versions`](../.tool-versions), and `actions/setup-python` below |
| ESLint and math-check Node.js | `26.10.0` | [`.tool-versions`](../.tool-versions), the pre-commit `node` language version, and the CI checks job |
| Production image Python | `python:3.14.7-slim-bookworm`, digest `sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56` | [`Dockerfile`](../Dockerfile) |
| Poetry | `2.5.1` | [`.tool-versions`](../.tool-versions) is read by [shared CI setup](../.github/actions/setup-poetry/action.yml); [`Dockerfile`](../Dockerfile) pins the container installation separately |
| Poetry build backend | `poetry-core==2.5.0` | [`pyproject.toml`](../pyproject.toml) build-system requirements |
| Cosign CLI | `3.1.3` | [`.tool-versions`](../.tool-versions) and the release workflow inputs below |
| TeX Live image | `drpsychick/texlive-pdflatex`, digest `sha256:55b4bef7344394c0aafcd69b1796280f64b871ee2d2f2c3115e8f93ec9fea6ea` | [`Dockerfile`](../Dockerfile) and [`toolchain.json`](../pkg/resumeme/compiler/backends/latex/resources/toolchain.json) |
| Trivy scanner | `aquasec/trivy:0.75.0` | [`stage-security.yml`](../.github/workflows/stage-security.yml); version tag, not an immutable digest |
| TeXtidote image | `gokhlayeh/textidote`, digest `sha256:f0fe1a468f9818e2a91f7c660f25f7a17ba7ff1cd39e7daee32bdee7533f1441` | [`stage-readme.yml`](../.github/workflows/stage-readme.yml) and [`stage-documents.yml`](../.github/workflows/stage-documents.yml) |
| Tini | Debian package `0.19.0-1+b3` | [`Dockerfile`](../Dockerfile) |
| ESLint | `10.10.0` | [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) selects [`.config/eslint.config.mjs`](../.config/eslint.config.mjs) to lint standalone Selenium JavaScript resources |
| Markdown math parsers | KaTeX `0.19.0`, remark-math `6.0.0`, remark-parse `11.0.0`, unified `11.0.5` | [`package.json`](../scripts/validation/math/package.json) and its adjacent `package-lock.json`; development checks only |

The math-check package overrides transitive KaTeX versions with its direct
`katex` pin (`"katex": "$katex"`). `micromark-extension-math` currently requests
the vulnerable `0.16` line; the override removes that nested copy and addresses
[CVE-2026-103923](https://github.com/KaTeX/KaTeX/security/advisories/GHSA-238p-pmpm-9mq7).
Retain the override until upstream accepts a patched version, and rerun the math
checks when changing it. Trivy continues to scan the complete committed lockfile.

JavaScript executed in LinkedIn's browser is kept under
[`pkg/resumeme/linkedin/scripts/`](../pkg/resumeme/linkedin/scripts/) and linted
separately with ESLint. The Python package loads these files as resources at
runtime, and the wheel includes them. The pre-commit hook runs locally and in CI.

### GitHub Actions

Every external `uses:` reference below is pinned to the full commit SHA shown in
the workflow. The adjacent version comment is for readability; the SHA is the
actual reference. Repeated references use the same pin.

| Action | Version comment | Commit SHA |
| --- | --- | --- |
| `actions/cache/restore`, `actions/cache/save` | `v6.1.0` | `55cc8345863c7cc4c66a329aec7e433d2d1c52a9` |
| `actions/checkout` | `v7.0.1` | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/configure-pages` | `v6.0.0` | `45bfe0192ca1faeb007ade9deae92b16b8254a0d` |
| `actions/download-artifact` | `v8.0.2` | `9000827ccba6bdab643e8b6fd33ac0654aef8333` |
| `actions/setup-python` | `v7.0.0` | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| `actions/setup-node` | `v7.1.0` | `949feb2413d6458794dcd2491c4babbbce0c15c1` |
| `actions/upload-artifact` | `v7.0.2` | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| `actions/upload-pages-artifact` | `v5.0.0` | `fc324d3547104276b827a68afc52ff2a11cc49c9` |
| `docker/build-push-action` | `v7.4.0` | `c3c9e263c25d99ce0380d002d59b67737d91b0dc` |
| `docker/login-action` | `v4.6.0` | `dbcb813823bdd20940b903addbd779551569679f` |
| `docker/metadata-action` | `v6.2.0` | `dc802804100637a589fabce1cb79ff13a1411302` |
| `docker/setup-buildx-action` | `v4.4.1` | `f87e5991a6d7451dcb8d9637bfbc97413f497069` |
| `openai/codex-action` | `v1` | `bdf19a4a223ec2549a3e2274a0cf61556bc07675` |
| `ossf/scorecard-action` | `v2.4.4` | `2d1146689b8cda280b9bc96326124645441f03bc` |
| `peaceiris/actions-gh-pages` | `v4.0.0` | `4f9cc6602d3f66b9c108549d475ec49e8ef4d45e` |
| `sigstore/cosign-installer` | `v4.1.2` | `6f9f17788090df1f26f669e9d70d6ae9567deba6` |

The workflow requests the GitHub-hosted `ubuntu-24.04` runner image. GitHub
updates the contents behind that label, so it is not an immutable image pin.
Likewise, Homebrew formulas in [`Brewfile`](../.config/Brewfile) are package selections,
not version locks; Debian's `firefox-esr` and development `git` packages are
installed from the current apt index. These platform-managed tools can change
without a source edit. The Tini apt package is version-constrained as listed above.

When changing an action or tool, update its workflow or image reference first,
then update this inventory and run the relevant local checks. Keep action SHAs,
image digests, and `poetry.lock` updates in reviewed changes; do not resolve new
Python versions during ordinary CI runs.

CI uses three test partitions with four pytest-xdist workers per runner. The
standard public `ubuntu-24.04` runner has
[four CPUs](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories);
private repositories receive two CPUs with that label. Lint, types, and schema
checks run once alongside the test matrix. Cases are sorted by pytest node ID
and assigned round-robin, including individual parameter combinations, so every
case runs in exactly one partition. No partition options means the entire suite.
Reproduce a CI partition locally with:

```bash
poetry run pytest --shard-count 3 --shard-index 1 -n 4
```

Indices are one-based. `bash scripts/ci/checks/test.sh` still runs both pre-commit and
the complete suite; use `checks` or `tests` as its first argument to run only
that portion. Additional arguments in `tests` or `all` mode go to pytest.

## Browser end-to-end parity

The browser end-to-end stage launches real headless Firefox and Chrome sessions
against the same local LinkedIn-shaped fixture. It checks expanded profile text,
links, images, sections, skills, and profile-schema round trips, then requires the
normalized JSON payloads to match exactly. Both runs use one runner, and the job
summary records capture durations and recommends the faster browser as the default.
The fixture keeps LinkedIn credentials, MFA, and external network access out of CI.
This stage runs on pull requests and runs again on pushes to `main`; its result is
part of `CI verification`.

The regular test suite excludes these browser tests. Run one locally with the
matching browser installed:

```bash
RESUMEME_E2E_BROWSER=firefox poetry run pytest pkg/resumeme/tests/linkedin/test_browser_e2e.py -m browser_e2e -n 0
RESUMEME_E2E_BROWSER=chrome poetry run pytest pkg/resumeme/tests/linkedin/test_browser_e2e.py -m browser_e2e -n 0
```

The README coverage badge uses the combined `python-coverage` XML artifact from
CI. Each partition uploads distinct raw coverage as `python-coverage-1`, `-2`,
or `-3`, including on failure. The aggregation job merges all three after every
partition succeeds; failed tests cannot publish a partial coverage badge.
Successful default-branch pushes publish `badges/coverage.svg` on `gh-pages`
in a separate job; unchanged percentages produce no commit. The badge links to
the CI runs and becomes available after its first successful publication. Its
raw GitHub URL works independently of the resume's Pages site. No additional
secret or coverage service is required. Forks retaining the project README can
replace `astrivant/resumeme` in the badge's image and destination URLs.

## Configuration lint hook

[`.pre-commit-hooks.yaml`](../.pre-commit-hooks.yaml) exports
`resumeme-config-validator`, which runs `resumeme config lint` on changed
`resumeme.config*.yaml` or `.yml` files. It validates configuration without
captured LinkedIn data or a PDF build. See the [CLI reference](CLI.md#resumeme-config-lint)
for direct use with arbitrary filenames.

This checkout uses a `repo: local` entry in
[`.pre-commit-config.yaml`](../.pre-commit-config.yaml), so validation always runs
the latest checkout's code with the existing Poetry environment. Check both
maintained configurations explicitly with:

```bash
poetry run pre-commit run resumeme-config-validator --files resumeme.config.yaml .config/resumeme.config.ref.yaml
```

Other repositories can install the published hook with Python 3.13 available:

```yaml
repos:
  - repo: https://github.com/astrivant/resumeme
    rev: <tag-or-commit-containing-the-hook>
    hooks:
      - id: resumeme-config-validator
```

Replace the revision placeholder with a tag or commit containing the hook; after
release, `pre-commit autoupdate` selects the latest tagged version. Override
`files` on the hook entry to select other config filenames. Pre-commit passes
every matching filename to the validator, and any invalid file fails the hook.

## Repository settings and reviews

[`.github/settings.yml`](../.github/settings.yml) is applied by the
[Settings app](https://github.com/repository-settings/app) after it reaches the
default branch. The app must be installed with repository administration access;
editing the file locally does not change GitHub's live protection.

`main` requires one approving review, approval of the latest push by someone other
than its pusher, dismissal of stale approvals, resolved review conversations, and
the `CI verification` check on an up-to-date branch. Squash and rebase merges keep
history linear; merge commits, force pushes, and branch deletion are disabled.
Administrators retain bypass. There is no code-owner review requirement because
this repository has no `CODEOWNERS` file.

Direct PDF publication to protected `main` requires **`RESUME_PUBLISH_TOKEN`**:
a dedicated token limited to this repository with contents write permission,
owned by an administrator or another actor allowed to bypass both required
reviews and checks. Ordinary `GITHUB_TOKEN` write permission does not grant that
bypass. Set the secret before applying branch protection; it reaches only the
main-branch publication job, after verification. Forks without branch protection
can omit it and retain `GITHUB_TOKEN` publication.

```bash
gh secret set RESUME_PUBLISH_TOKEN --repo OWNER/REPO
```

In `astrivant/resumeme`, the organization secret `BENCHMARK_PUBLISH_TOKEN` supplies
the publication credential when `RESUME_PUBLISH_TOKEN` is absent. Its owner must
have bypass permission and its repository scope must include `astrivant/resumeme`.
This fallback is restricted to the upstream repository; forks use the dedicated
secret described above. Both credentials reach only the verified publication job.

If publication reports `GH006`, check the job's `RESUMEME_PUBLISH_USES_TOKEN`
value. `false` means neither publication secret was supplied, so checkout used
`GITHUB_TOKEN`. `true` means a token was supplied; verify its owner and repository
scope. The parent commit's successful CI check does not apply to the new generated
commit. After changing the workflow, push it and start a new run; rerunning an
older run uses its original workflow and secret mapping.

Publication-token commits include a `Resumeme-Publication: true` trailer. Their
pushes run normal CI and Scorecard; only repeated PDF publication is skipped.
The originating run deploys Pages using the accepted commit. Monthly and manual
refreshes can still publish new PDFs; tagging a generated commit still captures
LinkedIn and creates a release. Publication never forces a push or relaxes branch
protection.

## OpenSSF Scorecard

The README's [Scorecard badge](https://scorecard.dev/viewer/?uri=github.com/astrivant/resumeme)
links to the latest published assessment. `scorecard.yml` runs on pushes to `main`
and weekly, using the upstream action with `publish_results: true` and GitHub OIDC.
No additional secret is required. The badge becomes available after the first
successful publication. Forks skip analysis because the
[upstream action](https://github.com/ossf/scorecard-action#installation) does not support them.
This workflow runs independently of PDF builds and releases.

## Package responsibilities

Implementation and tests live in `pkg/resumeme/`; repository tooling lives in
`scripts/`. `linkedin/` owns browser and network acquisition; `compiler/` owns
parsing, typed records, transformation passes, target resources, and compilation.
Runtime options live in `config/models.py`, with loading and validation in
`config/loading.py`. See the [compiler architecture](compiler.md).
See [pipeline and package ownership](README.md#pipeline-and-ownership), the
[profile schema](profile-schema.md), and the [template interface](templates.md).

## Exceptions

Define package exceptions under `pkg/resumeme/exceptions/` and import them from
`resumeme.exceptions`. `ResumemeError` is the shared base; domain classes identify
configuration, profile, summary, media, contribution, rendering, compilation,
publication, signing, and browser failures. They retain their previous built-in
or Selenium bases so existing catch clauses and retry policies continue to work.
Preserve exception chaining when translating a dependency failure. Untranslated
dependency exceptions keep their original types.

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

CI derives the package version from the tag and updates `project.version` in each
disposable build checkout. For example, `v0.1.0` produces version `0.1.0`, and
`v0.2.0rc1` produces `0.2.0rc1`. The wheel, source archive, and package installed in
the container use the same version. No version edit or metadata commit is required;
the source commit and dependency lockfile remain unchanged.

```bash
# For the initial 0.1.0 release, commit the reviewed release changes first.
poetry check --lock
git tag v0.1.0
git push origin v0.1.0
```

For later releases, commit the reviewed changes and push a new version tag.
Tags use `vMAJOR.MINOR.PATCH`, optionally followed by Python prerelease (`a1`,
`b1`, `rc1`), postrelease (`.post1`), or development (`.dev1`) suffixes.
Non-version tags, ordinary pushes, manual runs, and pull requests do not upload
to PyPI. Branch and personal resume tags retain the committed package version.
Missing credentials, invalid version tags, or missing distributions fail publication.
Transient upload failures use exponential
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

Pre-commit's `document-math` hook checks Markdown equations with
[KaTeX strict parsing](https://katex.org/docs/options) after remark identifies
math nodes. Prefer GitHub `math` fences for derivations; inline `$...$` and
display `$$` blocks are also checked. It rejects malformed TeX, unsupported
commands, and unclosed display/fenced blocks, with file/line diagnostics.
Ordinary code blocks and inline code remain examples, not math input.

The same hook runs the [capture scheduling](capture-scheduling.md) worked examples
as Python doctests, including exact fractional variance calculations and actual
PID updates. Syntax validity is not a proof of a mathematical claim. Keep the
definitions, derivations, worked examples, and relevant property tests aligned.
Leave a blank line before closing a `pycon` fence so doctest does not treat that
fence as expected output.

Run `poetry run pre-commit run document-math --all-files` locally. Node 22 or newer
is required; local/CI tooling pins Node `26.10.0`. The wrapper installs from the
npm lockfile with lifecycle scripts disabled, only when the manifests or Node
runtime change. CI caches npm downloads and runs the hook in the existing checks
job. No new workflow or production dependency is introduced.

Use keyboard punctuation in prose, comments, CLI messages, and templates: `-`,
straight quotes, `...`, and `->`. Accented words and names are welcome. Express
Unicode parser delimiters and test cases with code-point escapes or HTML entities;
keep captured profile data lossless. Rendering normalizes editorial punctuation
without removing accents or meaningful symbols such as list bullets.

CI runs [TeXtidote Action](https://github.com/marketplace/actions/textidote-action)
against the root README and generated LaTeX, with English spelling and grammar
checks. README review starts with source checks; generated LaTeX review waits for
its profile and summaries. Download `textidote-readme-report` and
`textidote-reports` for annotated HTML; each job summary reports
finding counts. Prose findings are advisory; tool failures block publication.
See [document review](README.md#document-review) for the pinned image and review policy.
