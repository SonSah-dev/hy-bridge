#!/usr/bin/env bash
# Move /export transcripts (YYYY-MM-DD-HHMMSS-*.md) from the project root into chats/.
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0
mkdir -p chats
for f in [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]-*.md; do
  [ -f "$f" ] && mv -n "$f" chats/
done
exit 0
