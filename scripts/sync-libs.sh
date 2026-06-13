#!/usr/bin/env bash
# Vendor the in-repo charm libraries (libs/<name>) into each charm that depends
# on them, as a `library/` directory. charmcraft only stages a charm's own
# directory at pack time, so the library has to live physically inside it (a
# symlink to ../../libs/... breaks in the build instance). Run this after
# changing a library, and it is run in CI before packing.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Map of library distribution name -> source directory.
declare -A LIBS=(
    ["charmlibs-interfaces-sentry-dsn"]="libs/sentry-dsn"
)

shopt -s nullglob
for project in charms/*/ demos/*/; do
    pyproject="${project}pyproject.toml"
    [ -f "$pyproject" ] || continue
    for dist in "${!LIBS[@]}"; do
        if grep -q "$dist" "$pyproject"; then
            src="${LIBS[$dist]}"
            dest="${project}library"
            rm -rf "$dest"
            mkdir -p "$dest"
            cp -r "$src/pyproject.toml" "$src/README.md" "$src/src" "$dest/"
            echo "synced $src -> $dest"
        fi
    done
done
