"""Turn Cursor chat transcript JSONL into readable Markdown.

The raw transcript is one JSON object per line with nested content blocks. That is
fine for a machine and useless for a person, so this flattens it: turns, text,
tool calls and tool results, in order.

Images are referenced by path rather than inlined, because a transcript embeds
them as base64 and a Markdown file full of base64 is worse than useless.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAX_RESULT_CHARS = 1200
MAX_COMMAND_CHARS = 300


def _text_of(content) -> str:
    """Flatten a content value into plain text, skipping binary blobs."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            parts.append(_text_of(block))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        block_type = content.get("type")

        if block_type in ("text", "input_text", "output_text"):
            return str(content.get("text", ""))

        if block_type == "image":
            source = content.get("source") or {}
            path = source.get("path") or source.get("data", "")
            if isinstance(path, str) and path.startswith("/"):
                return f"_[image: {path}]_"
            return "_[image]_"

        if block_type == "tool_use":
            name = content.get("name", "tool")
            params = content.get("input") or {}
            rendered = _render_tool_input(name, params)
            return f"**-> {name}**\n\n{rendered}"

        if block_type == "tool_result":
            body = _text_of(content.get("content"))
            body = _truncate(body, MAX_RESULT_CHARS)
            return f"```\n{body}\n```"

        # Fall back to any obvious text field.
        for key in ("text", "content", "message"):
            if key in content:
                return _text_of(content[key])
        return ""
    return ""


def _render_tool_input(name: str, params: dict) -> str:
    """Show what a tool was asked to do, not the whole payload."""
    if not isinstance(params, dict):
        return f"```\n{_truncate(str(params), MAX_COMMAND_CHARS)}\n```"

    for key in ("command", "cmd"):
        if key in params:
            command = _truncate(str(params[key]), MAX_COMMAND_CHARS)
            return f"```bash\n{command}\n```"

    if "file_path" in params or "path" in params:
        target = params.get("file_path") or params.get("path")
        detail = params.get("pattern") or params.get("old_string") or ""
        line = f"`{target}`"
        if detail:
            line += f"\n\n`{_truncate(str(detail), 120)}`"
        return line

    interesting = {
        k: v
        for k, v in params.items()
        if k in ("pattern", "query", "search_term", "glob_pattern", "rootPath", "description")
    }
    if interesting:
        return "```\n" + "\n".join(f"{k}: {_truncate(str(v), 200)}" for k, v in interesting.items()) + "\n```"

    return ""


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n... [{len(text) - limit} more characters]"


ARABIC = re.compile(r"[\u0600-\u06FF]")
ENGLISH_MARKER = re.compile(
    r"\b(let me|i should|i need to|i'll|the user|actually|wait|hmm|let's|i think|maybe i)\b",
    re.IGNORECASE,
)


def looks_like_reasoning(paragraph: str) -> bool:
    """True for text that is internal narration or a plan, not the reply.

    A transcript stores reasoning, plan drafts and the visible reply in the same
    text block. Splitting by block is therefore not enough, and neither is looking
    for "let me" alone -- plan drafts are written in plain English without those
    markers.

    The reliable signal in a session conducted in Arabic is the language itself: a
    paragraph with no Arabic in it is not what the user read. Code fences, tables
    and headings are kept regardless, because they are content.
    """
    text = paragraph.strip()
    if not text:
        return False

    # Structural content is never reasoning.
    if text.startswith(("```", "|")):
        return False

    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False

    arabic = sum(1 for c in text if ARABIC.match(c))
    if arabic:
        return False

    ascii_ratio = sum(1 for c in letters if c.isascii()) / len(letters)
    if ascii_ratio < 0.6:
        return False

    # English with no Arabic: reasoning, unless it is a short label or a list item
    # that belongs to a reply.
    if text.startswith(("-", "*", ">", "#")) and len(text) < 200:
        return False
    return True


def strip_reasoning(text: str) -> str:
    """Keep only the parts of a block that belong to the visible reply.

    Filtering by paragraph is not enough. Reasoning often continues on the same
    paragraph as the reply, separated only by a newline, and a single Arabic word
    inside that trailing English is enough to make the whole paragraph look like
    reply content. So the filter works line by line inside any paragraph that
    contains Arabic, and paragraph by paragraph otherwise.
    """
    kept: list[str] = []
    for paragraph in text.split("\n\n"):
        if not paragraph.strip():
            continue

        if not ARABIC.search(paragraph):
            if not looks_like_reasoning(paragraph):
                kept.append(paragraph)
            continue

        # Paragraph mixes Arabic reply with English narration: keep the reply lines.
        lines = [
            line
            for line in paragraph.split("\n")
            if not _is_english(line)
        ]
        remainder = "\n".join(lines).strip()
        if remainder:
            kept.append(remainder)

    return "\n\n".join(kept)


def _is_english(line: str) -> bool:
    """True for a line that is narration rather than reply content.

    Deliberately simple: mostly Latin letters and long enough to be a sentence.
    A stray Arabic word inside an English sentence does not make the line Arabic,
    which is the case that used to slip through.

    Structural lines are never narration -- a code fence, a table row or a bullet
    is content even when it is English.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("`", "|", "#", ">", "!", "[")):
        return False
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if c.isascii())
    return latin / len(letters) >= 0.8 and len(stripped) > 30


def _is_english(line: str) -> bool:
    """True for a line that is narration rather than reply content.

    Deliberately simple: if the line is mostly Latin letters and is long enough to
    be a sentence, it is narration. A stray Arabic word inside an English sentence
    ("...barcode-generator في ~/Projects...") does not make the line Arabic, which
    is exactly the case that used to slip through.
    """
    stripped = line.strip()
    if not stripped:
        return False
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if c.isascii())
    return latin / len(letters) >= 0.8 and len(stripped) > 30


def _has_query(text: str) -> bool:
    """True when a user message is an actual question, not a system notice.

    Task-completion notices arrive as user messages containing only a timestamp and
    the tool wrapper, with no ``<user_query>``. They are not turns.

    A second kind of notice carries a ``<user_query>`` but it is machine-authored
    boilerplate ("inform the user about the task result"), not something the person
    typed. Those are recognised by their wording and dropped, because including
    them makes the transcript look like the user asked those things.
    """
    query = re.search(r"<user_query>(.*?)</user_query>", text, re.S)
    if query:
        body = query.group(1).strip()
        if body.lower().startswith("briefly inform the user about the task result"):
            return False
        return bool(body)

    stripped = re.sub(r"<[^>]+>", "", text).strip()
    return bool(stripped)


def _user_key(text: str) -> str:
    """A stable identity for a user turn, ignoring timestamps.

    The same question resent later keeps the same key, so an accidental replay (a
    workspace move re-emitting the history) collapses while a genuine resend
    appears once.
    """
    query = re.search(r"<user_query>(.*?)</user_query>", text, re.S)
    body = query.group(1) if query else text
    body = re.sub(r"\s+", " ", body).strip()
    return body[:200]


def _pick_visible(replies: list[str]) -> str:
    """Pick the text that was actually shown to the user.

    Within one turn the assistant writes several text blocks: reasoning, then a
    reply, then a plan, then another reply. A turn can therefore have many
    candidates. The last block is not always the visible one -- a plan summary or a
    tool-narration can come after the reply.

    The rule used here: take the **last block that still has content after
    reasoning is stripped**, preferring Arabic where Arabic is present. That picks
    the final thing the user read, not the internal narration that followed it.
    """
    best = ""
    for block in reversed(replies):
        cleaned = strip_reasoning(block)
        if not cleaned.strip():
            continue
        if ARABIC.search(cleaned):
            return cleaned
        if not best:
            best = cleaned
    return best


def convert(paths: list[Path], out_path: Path) -> tuple[int, int]:
    """Extract the visible conversation.

    A Cursor transcript interleaves the assistant's visible replies with its
    internal reasoning and its tool calls, and both are stored as ordinary ``text``
    blocks. Dumping every block produces a file where 428 "assistant turns" sit
    against 23 user messages -- unreadable, and misleading about what was said.

    The rule used here: a turn's visible reply is the **last text block of the last
    assistant record before the next user message**. Everything earlier in the turn
    is reasoning or a tool call. This matches what the user actually saw.
    """
    turns: list[dict] = []
    current: dict | None = None
    seen_users: set[str] = set()

    for path in paths:
        if not path.exists():
            print(f"skipping missing file: {path}", file=sys.stderr)
            continue

        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                role = record.get("role")
                message = record.get("message") or record
                if not isinstance(message, dict):
                    continue
                content = message.get("content")

                if role == "user":
                    text = _text_of(content).strip()
                    if not text:
                        continue
                    # Tool notifications arrive as user messages with no query in
                    # them -- only a timestamp. They are not turns.
                    if not _has_query(text):
                        continue
                    # Moving the agent to a new workspace starts a new transcript
                    # that replays the earlier messages. Deduplicate only that
                    # replay: a repeat is a replay when it arrives with the same
                    # key *and* no new replies were added since. A genuine resend
                    # by the user comes after assistant activity, so it is kept.
                    key = _user_key(text)
                    if key in seen_users and current is not None and not current["replies"]:
                        current = next(
                            (t for t in turns if _user_key(t["user"]) == key), None
                        )
                        continue
                    seen_users.add(key)
                    current = {"user": text, "replies": [], "tools": []}
                    turns.append(current)
                elif role == "assistant" and current is not None:
                    texts = [
                        b.get("text", "")
                        for b in (content or [])
                        if isinstance(b, dict)
                        and b.get("type") == "text"
                        and b.get("text", "").strip()
                    ]
                    tools = [
                        b.get("name", "")
                        for b in (content or [])
                        if isinstance(b, dict) and b.get("type") == "tool_use"
                    ]
                    if texts:
                        current["replies"].extend(texts)
                    current["tools"].extend(tools)

    out: list[str] = [
        "# Barcode generator - chat transcript",
        "",
        "Exported from a Cursor session. Only the visible conversation is kept; the",
        "assistant's internal reasoning is omitted and tool calls are listed by name.",
        "",
        "---",
        "",
    ]

    for index, turn in enumerate(turns, start=1):
        out.append(f"## Turn {index}")
        out.append("")

        user_text = turn["user"]
        query = re.search(r"<user_query>(.*?)</user_query>", user_text, re.S)
        body = (query.group(1) if query else user_text).strip()
        body = re.sub(r"</?timestamp>[^<]*", "", body)
        body = re.sub(r"<system_reminder>.*?</system_reminder>", "", body, flags=re.S)
        body = re.sub(r"<image_files>.*?</image_files>", "[images attached]", body, flags=re.S)
        body = body.strip()

        if body:
            out.append("**User:**")
            out.append("")
            out.append(body)
        else:
            # A turn with no typed question is a background notice: a task
            # finishing or a subagent reporting. Saying so is more honest than
            # printing a bare timestamp and letting it look like a user turn.
            out.append("_Background task notice (no message from the user)._")
        out.append("")

        replies = turn["replies"]
        chosen = _pick_visible(replies)
        if chosen:
            out.append("**Assistant:**")
            out.append("")
            out.append(chosen.strip())
        else:
            out.append("_No visible reply was recorded for this turn._")
        out.append("")

        if turn["tools"]:
            unique: list[str] = []
            for name in turn["tools"]:
                if name and name not in unique:
                    unique.append(name)
            out.append(f"_[tools used: {', '.join(unique)}]_")
            out.append("")
        out.append("---")
        out.append("")

    out_path.write_text("\n".join(out), encoding="utf-8")
    return len(turns), len(out)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: export_chat.py OUT.md IN1.jsonl [IN2.jsonl ...]", file=sys.stderr)
        return 2
    out_path = Path(argv[1])
    paths = [Path(a) for a in argv[2:]]
    turns, _ = convert(paths, out_path)
    size = out_path.stat().st_size
    print(f"wrote {out_path} ({turns} turns, {size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
