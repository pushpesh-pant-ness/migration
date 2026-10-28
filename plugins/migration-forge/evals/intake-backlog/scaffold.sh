#!/usr/bin/env bash
set -e
cp -r "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../fixtures/legacy-shop" ./legacy-shop-src
mkdir -p work
