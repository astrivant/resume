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
Hooks check Ruff, strict mypy, Google-style docstrings, schemas, ShellCheck, and
shfmt. For container-based development, see [local image builds](containers.md#build-locally).

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
Runtime options remain in `config.py`. See the [compiler architecture](compiler.md).
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
