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

If the optional GitHub graph is enabled, either remove `--network=none` to acquire
public activity or append `--github-calendar tex/github-contributions.json` after
`build` and pin `profile.github.contributions.as_of` to that saved calendar's end date.
The TeX compiler itself never needs network access. See
[calendar configuration](README.md#github-contribution-graph).

Only `linux/amd64` is published because the pinned TeX image contains x86-64
binaries. Docker Desktop can emulate it on Apple Silicon. The production image
contains neither Poetry nor development dependencies.

## Capture with Firefox

The packaged browser is Firefox. For `capture.browser: chrome`, capture locally
with Chrome installed, then use this image to render or build the saved snapshot.

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

Package version tags such as `v0.1.0` set the version installed in the container
to match the Python distributions. Other tags and branch builds use the committed
package version. CI applies this metadata during the build without committing it;
see [package releases](development.md#publish-to-pypi).

All pushed tags trigger the existing pipeline. Ordinary branches and pull requests
also build and smoke-test the container. Publication happens only for tag pushes,
after both the test and build stages succeed:

1. The entry workflow resolves one immutable source commit.
2. The build stage installs the wheel in the production image, smoke-tests it,
   and uploads the tested image archive for tag runs.
3. The verification gate checks all required stage results.
4. Alongside the tag's signed PDF release, the container publication jobs load that archive, check its source revision,
   and push it to GHCR and, for `astrivant/resumeme` only, Docker Hub with exponential retries. They do not rebuild the image.
5. After the signed release and registry jobs finish, one job collects successful uploads and updates the Git tag's
   GitHub release notes with the exact image paths and copyable `docker pull`
   commands, including `--platform linux/amd64`.

GHCR uses `ghcr.io/<lowercase-owner>/<lowercase-repository>`; the upstream Docker Hub
image is `emmeowzing/resumeme`. Docker's
[metadata action](https://github.com/docker/metadata-action#typeref) derives the
tag from the Git tag, replacing characters unsupported by container tags, and
also publishes `sha-<full-commit-sha>` using the pipeline's verified source commit.
For example, tag `v0.1.0` publishes `emmeowzing/resumeme:v0.1.0` and
`emmeowzing/resumeme:sha-<full-commit-sha>`, alongside the corresponding GHCR aliases.
No moving `latest` tag is published. OCI labels
record the source repository and commit. Publication references appear in the
workflow summary and tag release notes. Reruns replace only the generated container
section, preserving other notes, assets, and an existing release's draft status.
Only successful registry jobs contribute pull commands; a failed upload still fails
the pipeline. The notes job runs for forks even though their Docker Hub job is skipped.
The pipeline appends container instructions after the signed PDF release is
published on the same tag. Main-branch and monthly runs update the working PDF
without creating a release; see [monthly refresh and release](automation.md).

GHCR publication uses the automatic `GITHUB_TOKEN` with `packages: write`;
the notes job uses `contents: write`. GHCR requires no PAT or extra repository secret.
GHCR initially creates packages as private. Set the package visibility
to public to allow anonymous pulls. If the
package already exists, grant this fork's workflow repository write access to it.
See GitHub's [Container registry authentication and visibility documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

Docker Hub publication requires the organization Actions secret
`DOCKER_HUB_TOKEN_EMMEOWZING`, accessible to `astrivant/resumeme`. Its Docker Hub
token must permit pushes to `emmeowzing/resumeme`; the login username is
`emmeowzing`. The job runs only on upstream tag pushes and is skipped on forks,
even if they define a secret with the same name. Forks need no Docker Hub setup.
