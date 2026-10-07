#!/usr/bin/env bash
# Publish a verified artifact only while main still points at its source commit.
set -euo pipefail

if [[ "$GITHUB_REF" != refs/heads/main || "$GITHUB_EVENT_NAME" == pull_request ]]; then
    echo 'Publication requires a main-branch push, monthly schedule, or manual run.' >&2
    exit 1
fi

# Compare against a freshly fetched branch, not the event's potentially stale view of main.
bash scripts/tooling/retry.sh git fetch --no-tags origin main
test "$(git rev-parse HEAD)" = "$SOURCE_SHA"

# Commit exactly the fresh inputs that passed verification alongside the PDF produced from them.
if [[ "${REFRESH_PROFILE:-false}" == true ]]; then
    poetry run python scripts/ci/profile-artifact.py stage
fi

# Tree comparison below recognizes an identical publication from a previous attempt, including refreshed inputs.
poetry run python scripts/ci/restore-pdf.py

# A fresh coffee stain accompanies real resume changes; unchanged builds must not create logo-only bot commits.
# Use the source revision so a retry reconstructs the exact tree of a successful earlier publication.
if ! git diff --cached --quiet; then
    poetry run python scripts/ci/refresh-logo.py --seed "$SOURCE_SHA"
    git add -- docs/assets/branding/resumeme-logo.png
fi

if [[ "$(git rev-parse origin/main)" != "$SOURCE_SHA" ]]; then
    # A release retry may start after the previous attempt already committed this exact PDF.
    if [[ "$(git rev-parse 'origin/main^')" == "$SOURCE_SHA" && "$(git rev-parse 'origin/main^{tree}')" == "$(git write-tree)" ]]; then
        echo 'The identical resume and inputs were already committed.'
        echo "published-sha=$(git rev-parse origin/main)" >>"$GITHUB_OUTPUT"
        exit 0
    fi

    echo 'Main advanced after this build; a newer pipeline owns publication.'
    exit 0
fi

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'

# Avoid empty bot commits when neither the PDF nor its captured inputs changed.
if git diff --cached --quiet; then
    echo 'The resume PDF is unchanged.'
    echo "published-sha=$(git rev-parse HEAD)" >>"$GITHUB_OUTPUT"
    exit 0
fi

git commit -m 'docs: update resume, captured profile, and coffee stain'

# An intervening push rejects this normal fast-forward update; never force or rebase stale output.
bash scripts/tooling/retry.sh git push origin HEAD:refs/heads/main
echo "published-sha=$(git rev-parse HEAD)" >>"$GITHUB_OUTPUT"
