#!/usr/bin/env bash
# Run the locked ShellCheck and shfmt binaries against repository shell code.
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$PWD/.venv/bin:$PATH"
shellcheck -x "$@"
shfmt -d -i 4 -ci "$@"
