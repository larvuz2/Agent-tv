#!/bin/sh
# One-time setup on a computer that is on the same network as the TV.
#   sh scripts/setup.sh
set -e
DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$DIR"
PY=${PYTHON:-python3}
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e ".[dev]"
chmod +x scripts/agent-tv-mcp
echo
echo "Installed. Next:"
echo "  .venv/bin/agent-tv discover          # find the TV"
echo "  .venv/bin/agent-tv pair <TV-IP>      # accept the prompt on the TV"
echo "  .venv/bin/agent-tv status            # check it works"
echo "Then run 'claude' in this folder (or 'claude remote-control' to use it from the Claude app)."
