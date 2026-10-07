# Container usage and publication

The runtime image packages the `resumeme` CLI, its locked production dependencies,
Firefox ESR, and the TeX toolchain from the same pinned `drpsychick/texlive-pdflatex`
image used by host builds. It installs the built Python wheel and runs as UID/GID
`10001:10001` by default. Profile snapshots, assets, browser sessions, signing keys,
and generated PDFs are supplied at runtime and are excluded from the image.

The image includes [Tini](https://github.com/krallin/tini) as PID 1 to reap orphaned
processes and forward shutdown signals to the CLI's process group. The default
entrypoint is `/usr/bin/tini -g -- resumeme`; `docker run --init` is unnecessary.

## Contents

- [Run the image](#run-the-image)
- [Capture with Firefox](#capture-with-firefox)
- [Build locally](#build-locally)
- [Publish on a tag](#publish-on-a-tag)

## Run the image

After the first tag has been published, run this from a checkout containing your
configuration, `data/profile.json`, and captured assets:

```bash
docker run --rm --platform linux/amd64 --network=none \
    --user "$(id -u):$(id -g)" \
    --mount "type=bind,source=$PWD,target=/workspace" \
    ghcr.io/OWNER/resumeme:v0.1.0 build
```

Replace `OWNER/resumeme` with your lowercase owner/repository and `v0.1.0` with your
published tag. The command writes `resume.pdf`, generated TeX, and build logs back
to the checkout. Using your UID/GID keeps generated files owned by you on Linux.
The working directory is `/workspace`; the usual `resumeme.config.yaml` default
and all relative path rules apply. For another configuration, pass
`--config your-config.yaml build` after the image name.

Use `validate`, `render`, or `--help` in place of `build` for other operations.
The container sets `RESUMEME_TEX_BACKEND=local` so both pdfLaTeX passes run inside
the container. Shell escape stays disabled. The build command above disables
networking as well. No nested Docker daemon or host Docker socket is required.

Only `linux/amd64` is published because the pinned TeX image contains x86-64
binaries. Docker Desktop can emulate it on Apple Silicon. The production image
contains neither Poetry nor development dependencies.

## Capture with Firefox

On macOS and Windows, use the documented local `poetry run resumeme capture` flow,
then run the container against the resulting snapshot. The published image can
also run visible Firefox when connected to a Linux graphical display. For a local
X11 session with a readable Xauthority cookie file:

```bash
docker run --rm -it --platform linux/amd64 --shm-size=1g \
    --user "$(id -u):$(id -g)" --hostname "$(hostname)" \
    --env DISPLAY --env XAUTHORITY=/tmp/xauthority \
    --mount type=bind,source=/tmp/.X11-unix,target=/tmp/.X11-unix,readonly \
    --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/tmp/xauthority,readonly" \
    --mount "type=bind,source=$PWD,target=/workspace" \
    ghcr.io/OWNER/resumeme:v0.1.0 capture
```

Capture needs networking for LinkedIn, Selenium Manager's first driver download,
and media retrieval. Sign in in the displayed Firefox window. Its session stays
in the checkout's ignored `.cache/firefox/` directory and survives container
removal. Login has no deadline. Hosted CI builds saved inputs; it does not start
an interactive LinkedIn capture.

## Build locally

```bash
docker build --platform linux/amd64 --target production --tag resumeme:local .
bash scripts/ci/check-container.sh resumeme:local
```

The smoke check runs without networking or a writable container filesystem. It
checks the installed CLI and compiles a synthetic profile containing a skill
cloud and emoji, using a temporary mounted directory. It also checks that the
production image defaults to a non-root user and omits development commands.

The same Dockerfile has a `development` target with Poetry, development
dependencies, source, tests, and repository scripts:

```bash
docker build --platform linux/amd64 --target development --tag resumeme:dev .
docker run --rm --platform linux/amd64 --entrypoint /usr/bin/tini resumeme:dev -g -- python -m pytest
```

Dependencies install from `poetry.lock` without resolving new versions. The base
Python and TeX images are pinned by digest. Keep the TeX digest in `Dockerfile`
and `pkg/resumeme/compiler/backends/latex/resources/toolchain.json` aligned; schema checks enforce this
shared toolchain contract. Dependabot tracks Docker and Actions updates.

## Publish on a tag

Push a tag pointing at the commit you want to distribute:

```bash
git tag v0.1.0
git push origin v0.1.0
```

All pushed tags trigger the existing pipeline. Ordinary branches and pull requests
also build and smoke-test the container. Publication happens only for tag pushes,
after both the test and build stages succeed:

1. The entry workflow resolves one immutable source commit.
2. The build stage installs the wheel in the production image, smoke-tests it,
   and uploads the tested image archive for tag runs.
3. The verification gate checks all required stage results.
4. The container publication stage loads that archive, checks its source revision,
   and pushes it to GHCR with exponential retries. It does not rebuild the image.
5. After both aliases are uploaded, the stage creates or updates the Git tag's
   GitHub release notes with the exact image paths and copyable `docker pull`
   commands, including `--platform linux/amd64`.

The image name is `ghcr.io/<lowercase-owner>/<lowercase-repository>`. Docker's
[metadata action](https://github.com/docker/metadata-action#typeref) derives the
tag from the Git tag, replacing characters unsupported by container tags, and
also adds `sha-<full-commit-sha>`. No moving `latest` tag is published. OCI labels
record the source repository and commit. Publication references appear in the
workflow summary and tag release notes. Reruns replace only the generated container
section, preserving other notes, assets, and an existing release's draft status.
New container releases use [`gh release create --latest=false`](https://cli.github.com/manual/gh_release_create)
to keep signed PDF releases as the latest release. Signed PDF publication continues
on `main` independently.

The publication job uses the automatic `GITHUB_TOKEN` with `packages: write` for
GHCR and `contents: write` for release notes; no PAT or extra repository secret is
required. GHCR initially creates packages as private. Set the package visibility
to public to allow anonymous pulls. If the
package already exists, grant this fork's workflow repository write access to it.
See GitHub's [Container registry authentication and visibility documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
