#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 "$repo_dir/scripts/uninstall.py" "$@"
