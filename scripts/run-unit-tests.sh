#!/usr/bin/env bash
# Run every charm's and library's unit test suite. Used by the pre-commit hook
# and handy to run by hand. Exits non-zero if any suite fails.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

status=0

# Charms keep their code under src/ + vendored lib/, so put both on the path.
for charm in charms/*/; do
    [ -d "${charm}tests/unit" ] || continue
    echo "== unit tests: $(basename "$charm") =="
    if ! (cd "$charm" && PYTHONPATH="lib:src" uv run --group unit pytest tests/unit -q); then
        status=1
    fi
done

# Libraries are installed packages, so no PYTHONPATH is needed.
for lib in libs/*/; do
    [ -d "${lib}tests/unit" ] || continue
    echo "== unit tests: $(basename "$lib") (library) =="
    if ! (cd "$lib" && uv run --group unit pytest tests/unit -q); then
        status=1
    fi
done

if [ "$status" -eq 0 ]; then
    echo "All unit tests passed."
else
    echo "Unit tests FAILED." >&2
fi
exit "$status"
