#!/usr/bin/env bash
# Reuse locked Markdown math tooling, then check syntax and executable scheduling examples.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
package_dir="$root/scripts/validation/math"
cd "$root"

# Reinstall only when dependency inputs or the Node runtime change; npm's download cache survives lock updates.
lock_hash=$({
    node --version
    cat "$package_dir/package.json" "$package_dir/package-lock.json"
} | shasum -a 256)
stamp="$package_dir/node_modules/.resumeme-math-lock"

if [[ ! -f "$stamp" ]] || [[ "$(cat "$stamp")" != "$lock_hash" ]]; then
    npm --prefix "$package_dir" ci --engine-strict --ignore-scripts --no-audit --no-fund
    printf '%s\n' "$lock_hash" >"$stamp"
fi

node --test "$package_dir/check.test.mjs"
node "$package_dir/check.mjs"
bash scripts/tooling/project-python.sh -m doctest docs/capture-scheduling.md studies/capture-convergence/README.md
