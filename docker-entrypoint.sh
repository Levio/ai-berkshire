#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_BERKSHIRE_ROOT:-/app}"
VAR_DIR="${AI_BERKSHIRE_VAR_DIR:-/var/lib/ai-berkshire}"
CLAUDE_BIN="${CLAUDE_CLI:-claude}"
COMMANDS_DIR="${CLAUDE_COMMANDS_DIR:-$HOME/.claude/commands}"

mkdir -p "$ROOT/reports" "$VAR_DIR" "$HOME/.claude" "$HOME/.config/anthropic" "$COMMANDS_DIR"

test -w "$ROOT/reports" || { echo "ERROR: $ROOT/reports is not writable" >&2; exit 1; }
test -w "$VAR_DIR" || { echo "ERROR: $VAR_DIR is not writable" >&2; exit 1; }
test -w "$HOME/.claude" || { echo "ERROR: $HOME/.claude is not writable" >&2; exit 1; }

cd "$ROOT"
CLAUDE_COMMANDS_DIR="$COMMANDS_DIR" ./scripts/install-claude-commands.sh

if command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
  CLAUDE_VERSION="$($CLAUDE_BIN --version 2>/dev/null || true)"
else
  CLAUDE_VERSION="not found: $CLAUDE_BIN"
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  AUTH_STATUS="ANTHROPIC_API_KEY=set"
else
  AUTH_STATUS="ANTHROPIC_API_KEY=unset"
fi

cat <<EOF
AI Berkshire Web Skill Runner starting
user=$(id -u):$(id -g)
AI_BERKSHIRE_ROOT=$ROOT
AI_BERKSHIRE_VAR_DIR=$VAR_DIR
CLAUDE_CLI=$CLAUDE_BIN
claude_version=$CLAUDE_VERSION
$AUTH_STATUS
commands_dir=$COMMANDS_DIR
EOF

exec "$@"
