# resume

Create an illustrated PDF résumé from your expanded LinkedIn profile. Capture your
profile locally in Firefox, keep a portable snapshot, and let GitHub Actions render
and commit `resume.pdf` on `main`.

## Contents

- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Development](#development)

## Quick start

Requires Python 3.13+, Poetry 2.1.3, Firefox, and Docker for PDF compilation.

```bash
poetry install --only main
poetry run resume --help
```

Set `linkedin.username` in `resume.reference.yaml`, then capture your own profile:

```bash
poetry run resume capture
poetry run resume build
```

Sign in directly in the Firefox window opened by the capture command. Review
`data/profile.json`, `data/assets/`, and `resume.pdf` before committing your snapshot.
Forks retain the same defaults; changing the username is the only required config
edit, but each owner must capture their profile once. GitHub Actions cannot perform
an interactive LinkedIn login from a username.

Enable Actions in your fork and allow Actions to write repository contents. Push
the snapshot to `main`; the pipeline validates, builds, and commits `resume.pdf`.
Branch rules must permit that bot commit. Pull requests build review artifacts
without writing to the branch. See [configuration and operation](docs/README.md).

## How it works

`pkg/resume/` owns collection, validated profile data, media downloads, rendering,
and the command line. A local Firefox session expands profile sections and follows
their detail pages. `requests` downloads linked images and project previews into
`data/assets/`. Passwords and session cookies are never serialized.

A Jinja template translates the snapshot and configuration into `tex/resume.tex`.
The pinned `drpsychick/texlive-pdflatex` image compiles that source into `resume.pdf`.
CI builds from committed inputs without contacting LinkedIn. The layout uses
LinkedIn's blue accents, pale background, white cards, profile photo, and logos,
with full text flowing across pages. It is a print adaptation, not a pixel-identical
copy of the responsive website.

## Development

```bash
poetry install --with dev
poetry run pre-commit install
poetry run pre-commit run --all-files
poetry run pytest --cov --cov-report=term-missing
poetry build
```

The project follows Polyad's package layout, typed Python conventions, and
source/test/build/verification/deploy pipeline stages. See [architecture and
capture limits](docs/README.md) for ownership and failure behavior.
