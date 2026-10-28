#!/usr/bin/env bash
set -e
bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../fixtures/seed_workspace.sh" gate FAIL
