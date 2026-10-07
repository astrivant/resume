#!/usr/bin/env bash
# Exercise the installed CLI, packaged template, word cloud, and bundled TeX without network access.
set -euo pipefail
image="${1:-resume:ci}"
project=$(mktemp -d)
trap 'rm -rf "$project"' EXIT
# Synthetic inputs exercise packaged resources without reading or modifying the owner's captured profile.
cat >"$project/resume.config.yaml" <<'YAML'
linkedin:
  username: container-check
YAML
mkdir "$project/data"
cat >"$project/data/profile.json" <<'JSON'
{
  "username": "container-check",
  "name": "Container Check",
  "intro": ["Engineering & plants 🪴"],
  "sections": [{"key": "skills", "title": "Skills", "entries": [
    {"title": "Python", "skills": [{"name": "Python", "endorsements": 3}]},
    {"title": "C++", "skills": [{"name": "C++", "endorsements": 1}]}
  ]}]
}
JSON
# Give caches a bounded writable tmpfs while proving that generation needs neither network access nor a writable image layer.
options=(--rm --platform linux/amd64 --network=none --read-only --tmpfs "/tmp:rw,nosuid,size=256m" --cap-drop=ALL --security-opt=no-new-privileges)
docker run "${options[@]}" "$image" --help
docker run "${options[@]}" --entrypoint sh "$image" -c 'test "$(id -u)" != 0 && ! command -v poetry && ! command -v pytest'
# Match the invoking user's ownership on the mounted workspace, as documented for Linux consumers.
docker run "${options[@]}" --user "$(id -u):$(id -g)" \
    --mount "type=bind,source=$project,target=/workspace" "$image" build
# CLI success alone is insufficient: require the PDF, score manifest, and second compiler pass to have produced output.
test "$(head -c 5 "$project/resume.pdf")" = '%PDF-'
test -s "$project/tex/skills.weights.json"
test -s "$project/.cache/build/pdflatex-2.log"
