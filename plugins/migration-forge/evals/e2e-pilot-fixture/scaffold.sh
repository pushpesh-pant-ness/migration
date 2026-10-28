#!/usr/bin/env bash
# Legacy fixture as its own git repo next to an empty workspace.
set -e
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$here/../fixtures/legacy-shop" ./legacy-shop-src
git -C legacy-shop-src init -q && git -C legacy-shop-src add -A
git -C legacy-shop-src -c user.email=e2e@example.test -c user.name=e2e commit -qm "legacy baseline"
mkdir -p work
