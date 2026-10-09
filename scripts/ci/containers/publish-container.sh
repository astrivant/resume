#!/usr/bin/env bash
# Publish the verified archive from this pipeline using tags provided by Docker metadata-action.
set -euo pipefail
: "${SOURCE_SHA:?Set SOURCE_SHA to the verified source commit}"
: "${IMAGE_TAGS:?Set IMAGE_TAGS to the newline-separated registry references}"

# Deploy the exact image tested by the build stage; rebuilding here could change dependencies or generated layers.
docker load --input .cache/container/resumeme.tar.gz
revision=$(docker image inspect resumeme:ci --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')

# Fail before assigning public tags if the downloaded archive belongs to another source revision.
if [[ "$revision" != "$SOURCE_SHA" ]]; then
    echo 'Container source revision does not match the verified pipeline source.' >&2
    exit 1
fi

# Publish both the Git-tag and commit aliases; retry uploads without introducing another image build.
while IFS= read -r reference; do
    [[ -n "$reference" ]] || continue
    docker tag resumeme:ci "$reference"
    bash scripts/tooling/retry.sh docker push "$reference"

    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        printf -- '- Published %s\n' "$reference" >>"$GITHUB_STEP_SUMMARY"
    fi
done <<<"$IMAGE_TAGS"
