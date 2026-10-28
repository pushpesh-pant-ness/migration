#!/usr/bin/env bash
# Portable Python launcher: py.sh <script.py> [args...]
# Picks the first interpreter >= 3.9 among python3, python, py -3 (Windows launcher).
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$1"; shift
for cand in "python3" "python" "py -3"; do
  if $cand -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    exec $cand "$dir/$script" "$@"
  fi
done
echo "migration-forge: Python >= 3.9 not found (tried python3, python, py -3)" >&2
exit 1
