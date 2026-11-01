"""Claude Code session transcripts -> one Markdown file per session in chats/ (PLAN.md Step 10).

    python chats/export_chats.py                     # every session of this project
    python chats/export_chats.py --check-only        # completeness check, nothing written

Claude Code keeps each session as JSON lines under ~/.claude/projects/<project folder>/<session id>.jsonl
(one folder per checkout, including worktrees). Only `user` and `assistant` records are the
conversation; everything else is app bookkeeping (API requests, file snapshots, titles, queue
state) and is not rendered. Every content block of every message is rendered in file order and
unedited: text, reasoning (as far as the transcript stores it), tool calls with their exact input,
and tool results. The check counts blocks in the JSON and markers in the Markdown and fails on any
difference.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = Path.home() / ".claude" / "projects"
PROJECT_PREFIX = "C--Users-User-armenian-live-translate"
FENCE = "````"          # longer than any ``` inside tool output


def sessions(prefix: str = PROJECT_PREFIX) -> list[Path]:
    return sorted(p for d in PROJECTS.glob(prefix + "*") for p in d.glob("*.jsonl"))


def load(path: Path) -> tuple[list[dict], str | None]:
    messages, title = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("type") in ("custom-title", "ai-title"):
            title = r.get("customTitle") or r.get("aiTitle") or title
        elif r.get("type") in ("user", "assistant") and isinstance(r.get("message"), dict):
            messages.append(r)
    return messages, title


def blocks(record: dict) -> list[dict]:
    content = record["message"].get("content")
    return [{"type": "text", "text": content}] if isinstance(content, str) else list(content or [])


def _fenced(text: str, lang: str = "") -> str:
    return f"{FENCE}{lang}\n{text}\n{FENCE}"


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for c in content or []:
        if c.get("type") == "text":
            parts.append(c["text"])
        else:                                   # images and other non-text results
            parts.append(f"[{c.get('type')} block]")
    return "\n".join(parts)


def render_block(b: dict) -> str:
    t = b.get("type")
    if t == "text":
        return f"<!-- block:text -->\n{b['text']}"
    if t == "thinking":
        body = b.get("thinking") or "(reasoning not stored in the transcript)"
        return f"<!-- block:thinking -->\n<details><summary>Reasoning</summary>\n\n{body}\n\n</details>"
    if t == "tool_use":
        return (f"<!-- block:tool_use -->\n**Tool call:** `{b.get('name')}` (id `{b.get('id')}`)\n\n"
                + _fenced(json.dumps(b.get("input"), ensure_ascii=False, indent=2), "json"))
    if t == "tool_result":
        err = " (error)" if b.get("is_error") else ""
        return (f"<!-- block:tool_result -->\n**Tool result{err}** for `{b.get('tool_use_id')}`:\n\n"
                + _fenced(_result_text(b.get("content"))))
    return f"<!-- block:{t} -->\n" + _fenced(json.dumps(b, ensure_ascii=False, indent=2), "json")


def render(path: Path) -> tuple[str, dict]:
    messages, title = load(path)
    sid = path.stem
    start = messages[0]["timestamp"] if messages else ""
    head = [f"# {title or 'Untitled session'}", "",
            f"- Session ID: `{sid}`", f"- Started (UTC): {start}",
            f"- Source: `{path.parent.name}/{path.name}` (Claude Code transcript), converted by chats/export_chats.py",
            f"- Messages: {len(messages)}", ""]
    out, counts = head, {}
    for r in messages:
        role = r["type"]
        side = " (subagent)" if r.get("isSidechain") else ""
        out.append(f"## {role.capitalize()}{side} · {r.get('timestamp', '')}\n<!-- message:{r.get('uuid')} -->")
        for b in blocks(r):
            counts[b.get("type")] = counts.get(b.get("type"), 0) + 1
            out.append(render_block(b))
        out.append("")
    return "\n\n".join(out) + "\n", {"messages": len(messages), "blocks": counts}


def check(md: str, expected: dict) -> list[str]:
    errors = []
    if (n := md.count("<!-- message:")) != expected["messages"]:
        errors.append(f"messages: {n} rendered, {expected['messages']} in the transcript")
    for t, n in expected["blocks"].items():
        got = md.count(f"<!-- block:{t} -->")
        if got < n:        # >= : a tool result may itself contain such a marker
            errors.append(f"{t}: {got} rendered, {n} in the transcript")
    return errors


def filename(path: Path, md: str) -> str:
    title = md.splitlines()[0][2:]
    start = re.search(r"Started \(UTC\): (\d{4}-\d\d-\d\d)", md)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "session"
    return f"{start.group(1) if start else 'undated'}_{path.stem[:8]}_{slug}.md"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "chats"))
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    failed = 0
    for path in sessions():
        md, expected = render(path)
        errors = check(md, expected)
        name = filename(path, md)
        status = "OK" if not errors else "FAIL " + "; ".join(errors)
        print(f"{name}: {expected['messages']} messages, {sum(expected['blocks'].values())} blocks -> {status}")
        failed += bool(errors)
        if not args.check_only and not errors:
            Path(args.out, name).write_text(md, encoding="utf-8", newline="\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
