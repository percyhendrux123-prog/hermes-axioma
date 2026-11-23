#!/bin/sh
# Runs the mod-level tests with Claude Code's own test kit. The kit only finds *.test.ts inside the
# plugin folder, so this copies the plugin to a scratch folder, adds the tests there, and runs them.
# Nothing is added to the plugin itself.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd -P)
SCRATCH_BASE=${AXIOMA_SCRATCH:-$HOME/.hermes/cache/scratch}
[ -d "$SCRATCH_BASE" ] || SCRATCH_BASE=${TMPDIR:-/tmp}
TMP=$(mktemp -d "$SCRATCH_BASE/axioma-kit.XXXXXX")
TMP=$(cd "$TMP" && pwd -P)
trap 'rm -rf "$TMP"' EXIT
cp -R "$HERE/../axioma/." "$TMP/"
mkdir -p "$TMP/tests"
cp "$HERE"/*.test.ts "$TMP/tests/"
cd "$TMP"
claude plugin test
