#!/bin/bash
set -euo pipefail
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo 'Claude Voice requires macOS.' >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Install Python 3 from https://www.python.org/downloads/macos/ first.' >&2
  exit 1
fi
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
computer_name="${1:-$(scutil --get ComputerName 2>/dev/null || hostname -s)}"
exec python3 "$script_dir/install.py" --computer "$computer_name"
