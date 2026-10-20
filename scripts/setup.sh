#!/bin/sh
# One-time setup on a computer that is on the same network as the TV:
#   sh scripts/setup.sh
# Creates .venv with Python 3.10+ and installs agent-tv into it. If this
# computer has no Python 3.10+ (stock macOS ships 3.9), it downloads one with
# uv (https://docs.astral.sh/uv) into your user folder; nothing system-wide.
set -e
DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$DIR"

new_enough() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }
venv_python() {  # macOS/Linux: .venv/bin/python, Windows (Git Bash): .venv/Scripts/python.exe
  for p in .venv/bin/python .venv/Scripts/python.exe; do [ -x "$p" ] && { echo "$p"; return 0; }; done
  return 1
}

if VPY=$(venv_python) && new_enough "$VPY"; then
  echo "Using existing .venv"
else
  rm -rf .venv
  PY=""
  for cand in ${PYTHON:-} python3.13 python3.12 python3.11 python3.10 python3 python py; do
    if command -v "$cand" >/dev/null 2>&1 && new_enough "$cand"; then PY=$cand; break; fi
  done
  if [ -n "$PY" ]; then
    echo "Using $("$PY" --version 2>&1)"
    "$PY" -m venv .venv
  else
    echo "No Python 3.10+ found; getting one with uv..."
    if ! command -v uv >/dev/null 2>&1; then
      curl -LsSf https://astral.sh/uv/install.sh | sh
      PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi
    uv venv --python 3.12 --seed .venv
  fi
fi

VPY=$(venv_python) || { echo "setup failed: no .venv python" >&2; exit 1; }
echo "Installing agent-tv (takes a minute the first time)..."
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet -e ".[dev]"
chmod +x scripts/agent-tv-mcp

echo
echo "Done. Next:"
echo "  .venv/bin/agent-tv discover          # find the TV"
echo "  .venv/bin/agent-tv pair <TV-IP>      # then press Accept on the TV"
echo "  .venv/bin/agent-tv status            # check it works"
echo "Or just run 'claude' in this folder and ask it to find and pair your TV."
