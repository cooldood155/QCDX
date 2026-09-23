#!/usr/bin/env bash
set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PK_REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export PK_REPO_ROOT

exec "${PK_REPO_ROOT}/cmake/projectkit/scripts/package.sh" "$@"
