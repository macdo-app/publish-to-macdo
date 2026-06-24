#!/usr/bin/env bash
# Install / refresh the publish-to-macdo skill into a Codex (OpenAI) skills dir.
#
# Claude Code users get this skill from the plugin marketplace; Codex and Cursor have
# no marketplace, so they load skills from a flat directory under ~/.codex/skills. This
# script assembles that flat layout from THIS repo — the single source of truth — so the
# Codex copy never drifts from the published plugin. Re-run it after pulling new changes.
#
# To target a local mac.do instance, set MACDO_API_BASE=http://localhost:8080 when you
# run the skill; the copied script keeps the production default (https://app-api.mac.do).
#
# Usage:
#   scripts/install-codex.sh            # -> ~/.codex/skills/publish-to-macdo
#   scripts/install-codex.sh <dir>      # -> <dir>/publish-to-macdo
#   CODEX_SKILLS_DIR=<dir> scripts/install-codex.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_ROOT="${1:-${CODEX_SKILLS_DIR:-$HOME/.codex/skills}}"
DEST="$DEST_ROOT/publish-to-macdo"
SRC_SKILL="$REPO_ROOT/skills/publish-to-macdo"

[ -f "$SRC_SKILL/SKILL.md" ] || { echo "error: run from the publish-to-macdo repo (no $SRC_SKILL/SKILL.md)" >&2; exit 1; }

rm -rf "$DEST"
mkdir -p "$DEST/scripts" "$DEST/agents"
cp "$SRC_SKILL/SKILL.md"                 "$DEST/SKILL.md"
cp "$SRC_SKILL/scripts/macdo_publish.py" "$DEST/scripts/macdo_publish.py"
cp "$REPO_ROOT/agents/openai.yaml"       "$DEST/agents/openai.yaml"

echo "installed publish-to-macdo -> $DEST"
echo "  SKILL.md + scripts/macdo_publish.py + agents/openai.yaml"
