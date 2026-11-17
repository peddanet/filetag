#!/usr/bin/env bash
# Quality gates for the filetag monorepo (all packages in packages/*).
#
# Runs the same checks locally (pre-push hook) and in CI, so a green local
# run predicts a green pipeline. Every gate must pass; the script stops at
# the first failure and returns its exit code.
#
#   0. privacy  no locally listed term in files, paths or commit messages
#   1. format   pycodestyle, max line length 100
#   2. lint     pylint incl. Google-style docstring checks, score 10.00/10
#   3. types    mypy (config in pyproject.toml)
#   4. security bandit (config in pyproject.toml)
#   5. tests    pytest with branch coverage, threshold in pyproject.toml
#
# Usage: tools/check.sh [--fast]
#   --fast  skip the test gate (used for quick checks while editing)
#
# Runs as a normal user; needs no root privileges.

set -euo pipefail

cd "$(dirname "$0")/.."

FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1

SRC=(packages/protocol/src packages/core/src packages/worker/src packages/providers/src)

gate() {
    local name="$1"; shift
    printf '\n=== %-8s %s\n' "$name" "$*"
    "$@"
}

for tool in pycodestyle pylint mypy bandit; do
    command -v "$tool" >/dev/null || {
        echo "missing tool: $tool  ->  pip install -r requirements-dev.txt" >&2
        exit 2
    }
done

gate privacy  python3 tools/privacy_scan.py
gate format   pycodestyle --max-line-length=100 "${SRC[@]}" tests tools
gate lint     pylint --fail-under=10 "${SRC[@]}" tests tools
gate types    mypy
gate security bandit -q -c pyproject.toml -r "${SRC[@]}"
if (( FAST == 0 )); then
    gate tests python3 -m pytest -q -p no:cacheprovider \
        --cov=filetag_protocol --cov=filetag_core --cov=filetag_worker \
        --cov=filetag_providers --cov-report=term
fi

printf '\nAll quality gates passed.\n'
