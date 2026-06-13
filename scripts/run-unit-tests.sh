#!/usr/bin/env bash
# Run every charm's unit test suite. Used by the pre-commit hook and handy to
# run by hand. Exits non-zero if any charm's tests fail.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

status=0
for charm in charms/*/; do
    [ -d "${charm}tests/unit" ] || continue
    name=$(basename "$charm")
    echo "== unit tests: ${name} =="
    if ! (cd "$charm" && PYTHONPATH="lib:src" uv run --group unit pytest tests/unit -q); then
        status=1
    fi
done

if [ "$status" -eq 0 ]; then
    echo "All unit tests passed."
else
    echo "Unit tests FAILED." >&2
fi
exit "$status"
