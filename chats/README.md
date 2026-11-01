# Chat history

The challenge requires complete, unedited histories of the Claude Cowork sessions: one Markdown file per session. The original conversations stay in the Claude app and will be shown at the interview.

## Process
See DECISIONS.md D-006 for what the official export preserves and what it doesn't.
1. Export from Settings → Privacy → Export data. Keep the raw ZIPs privately as evidence; they are **not** committed.
2. Select sessions by the conversation ID listed below. The export has no Project field.
3. Convert each conversation to `chats/<date>_<id8>_<slug>.md`, rendering every content block in order. A completeness check compares message and block counts against the JSON.
4. Review for privacy without editing the content.

## Session list
| # | Conversation ID | Title | Started (UTC) | Notes |
|---|---|---|---|---|
| 1 | 7b2d3efa-3a4e-41e1-b4a4-4425c908295c | Armenian speech translation plan | 2026-10-24 17:26 | Planning, Step 0 export check, Step 1 spike; still ongoing |

## Claude Code sessions (2026-11-01)
The work ran in Claude Code, which keeps every session locally as a JSON-lines transcript under `~/.claude/projects/`. `python chats/export_chats.py` writes one Markdown file per session into `chats/`: every message, reasoning block, tool call and tool result, in order and unedited. It then checks the rendered blocks against the transcript. `--check-only` writes nothing.
- **Privacy:** the sessions contain transcripts of the recorded test calls (other people's speech), which `runs/` keeps out of git. The developer reviews each file before anything here is committed.
- A session that is still running is exported after it ends.
