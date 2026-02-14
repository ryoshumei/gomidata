#!/bin/bash
# Stop hook: remind Claude to update STATUS.md before ending a session.
# Only blocks if there are uncommitted changes to project files (skips Q&A-only turns).
# On second pass (stop_hook_active=true), always allows stop.

INPUT=$(cat)

STOP_HOOK_ACTIVE=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stop_hook_active', False))" 2>/dev/null)

if [ "$STOP_HOOK_ACTIVE" = "True" ] || [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

# Use git to detect real changes — much more reliable than find -newer
# Show modified/added/untracked files, excluding STATUS.md and .claude/
CHANGED=$(git status --porcelain 2>/dev/null \
  | grep -v 'STATUS.md' \
  | grep -v '\.claude/' \
  | grep -v '\.venv/' \
  | sed 's/^...//' \
  | head -10)

if [ -z "$CHANGED" ]; then
  exit 0
fi

# Include the changed file list so Claude knows what to document
REASON="Project files were modified this session:\\n\\n${CHANGED}\\n\\nPlease update STATUS.md to reflect what was accomplished — update phase statuses, move items between Completed/In Progress/Blocked sections, and set the Last Updated date."

printf '{"decision": "block", "reason": "%s"}\n' "$REASON"
exit 0