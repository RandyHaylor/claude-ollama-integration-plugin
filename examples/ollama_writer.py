"""
ollama_writer.py — Sandboxed agent loop for ollama with file tools.

Tools:
  - read_file(path, start_line?, end_line?)  — read file or line range
  - write_file(path, content)                — create/overwrite file
  - edit_file(path, old_string, new_string)  — find/replace in file
  - list_files()                             — list all files in sandbox

Token budget: prompts are truncated to stay under MAX_PROMPT_CHARS
(~100k tokens at ~3.5 chars/token for qwen3).

Conversation accumulates within a node attempt — model sees its
own responses and tool results. Truncated at 100k tokens.

CLI:
  python ollama_writer.py [--read] [--write] <sandbox> <task>
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.request
from pathlib import Path

from qwen_token_counter import count as count_tokens, truncate as truncate_tokens

log = logging.getLogger("ntt.ollama_writer")


# ---------------------------------------------------------------------------
# Tool instructions
# ---------------------------------------------------------------------------

def _build_tool_instructions(tools: list[str]) -> str:
    lines = []
    if tools:
        lines.append("Tools (output one JSON tool call per response):")
        lines.append("")
        if "read" in tools:
            lines.append('  {"tool": "read_file", "args": {"path": "rel/path"}}')
            lines.append('  {"tool": "read_file", "args": {"path": "rel/path", "start_line": 1, "end_line": 50}}')
        if "write" in tools:
            lines.append('  {"tool": "write_file", "args": {"path": "rel/path", "content": "full file"}}')
            lines.append('  {"tool": "edit_file", "args": {"path": "rel/path", "old_string": "find this", "new_string": "replace with"}}')
        lines.append('  {"tool": "list_files", "args": {}}')
        lines.append("")
        lines.append("Paths are relative to project folder. One tool call per response.")
    else:
        lines.append("No tools available.")
    return "\n".join(lines)


def _build_terminal_instructions(mode: str) -> str:
    if mode == "execute":
        return (
            "Output only tool calls or the terminal response. No explanation, no markdown.\n\n"
            "When finished:\n"
            ' - When your work is complete, return this format:\n'
            '  {"is_execution_done": true, "summary": "what you accomplished"}'
        )
    # For plan modes, the orchestrator builds the full prompt including response format.
    return ""


# ---------------------------------------------------------------------------
# Ollama API
# ---------------------------------------------------------------------------

TURN_TIMEOUT_SECONDS = 180
OLLAMA_BASE_URL = "http://localhost:11434"


def _call_ollama(prompt: str, model: str = "qwen3-coder:30b", think: str | None = None) -> str:
    """Single call to ollama. Returns response text or raises on timeout."""
    prompt = truncate_tokens(prompt)

    body: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if think is not None:
        body["think"] = think

    payload = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TURN_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("response", "")
    except (TimeoutError, OSError) as exc:
        log.warning("OLLAMA TIMEOUT (%ds): %s", TURN_TIMEOUT_SECONDS, exc)
        raise


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _resolve_path(sandbox: Path, rel_path: str) -> Path | None:
    """Resolve a relative path within the sandbox. Returns None if it escapes."""
    target = (sandbox / rel_path).resolve()
    try:
        target.relative_to(sandbox.resolve())
        return target
    except ValueError:
        return None


def _execute_tool(tool_name: str, args: dict, sandbox: Path, tools: list[str]) -> str:
    if tool_name == "read_file":
        if "read" not in tools:
            return "ERROR: read_file not enabled"
        target = _resolve_path(sandbox, args.get("path", ""))
        if target is None:
            return "ERROR: path escapes sandbox"
        if not target.exists():
            return f"ERROR: not found: {args.get('path', '')}"
        lines = target.read_text(encoding="utf-8").splitlines()
        start = args.get("start_line")
        end = args.get("end_line")
        if start is not None or end is not None:
            s = (int(start) - 1) if start else 0
            e = int(end) if end else len(lines)
            selected = lines[s:e]
            return "\n".join(f"{s + i + 1}| {l}" for i, l in enumerate(selected))
        # Full file — add line numbers.
        return "\n".join(f"{i + 1}| {l}" for i, l in enumerate(lines))

    if tool_name == "write_file":
        if "write" not in tools:
            return "ERROR: write_file not enabled"
        target = _resolve_path(sandbox, args.get("path", ""))
        if target is None:
            return "ERROR: path escapes sandbox"
        content = args.get("content", "")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"OK: wrote {len(content)} chars to {args.get('path', '')}"

    if tool_name == "edit_file":
        if "write" not in tools:
            return "ERROR: edit_file not enabled"
        target = _resolve_path(sandbox, args.get("path", ""))
        if target is None:
            return "ERROR: path escapes sandbox"
        if not target.exists():
            return f"ERROR: not found: {args.get('path', '')}"
        old = args.get("old_string", "")
        new = args.get("new_string", "")
        content = target.read_text(encoding="utf-8")
        if old not in content:
            return f"ERROR: old_string not found in {args.get('path', '')}"
        updated = content.replace(old, new, 1)
        target.write_text(updated, encoding="utf-8")
        return f"OK: edited {args.get('path', '')} (replaced {len(old)} chars)"

    if tool_name == "list_files":
        files = []
        for f in sorted(sandbox.rglob("*")):
            if f.is_file():
                files.append(str(f.relative_to(sandbox)))
        return "\n".join(files) if files else "No files."

    return f"ERROR: unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def _extract_all_json(text: str) -> list[dict]:
    """Extract all JSON objects from the model's response text."""
    results = []
    # Try whole text as one object first.
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return [obj]
    except (json.JSONDecodeError, ValueError):
        pass
    # Try each line.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                results.append(obj)
        except (json.JSONDecodeError, ValueError):
            continue
    return results


def _is_terminal(obj: dict) -> bool:
    if obj.get("tool") == "run_command":
        return True
    if obj.get("is_planning_done") is not None:
        return True
    if obj.get("is_execution_done") is not None:
        return True
    if "task-can-be-split" in obj:
        return True
    if "sub-tasks" in obj:
        return True
    if "split-makes-it-harder" in obj:
        return True
    if "sub-tasks-under-a-minute" in obj:
        return True
    return False


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _session_file_path(sandbox: Path, session_id: str) -> Path:
    """Return the conversation file path for a session."""
    return sandbox / ".ollama-sessions" / session_id / "conversation.txt"


def _save_session(sandbox: Path, session_id: str, conversation: str) -> None:
    """Persist conversation to the session file."""
    path = _session_file_path(sandbox, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(conversation, encoding="utf-8")


def run(
    task: str,
    sandbox: str | Path,
    mode: str = "execute",
    model: str = "qwen3-coder:30b",
    tools: list[str] | None = None,
    max_turns: int | None = None,
    session_id: str | None = None,
    think: str | None = None,
) -> dict:
    """Run the agent loop. Returns dict with terminal response."""
    if tools is None:
        tools = []
    sandbox = Path(sandbox).resolve()
    sandbox.mkdir(parents=True, exist_ok=True)

    tool_inst = _build_tool_instructions(tools)
    term_inst = _build_terminal_instructions(mode)

    # Load existing session or build fresh conversation.
    if session_id and _session_file_path(sandbox, session_id).exists():
        conversation = _session_file_path(sandbox, session_id).read_text(encoding="utf-8")
    else:
        conversation = f"## TASK DESCRIPTION ##\n{task}\n## END TASK DESCRIPTION ##\n\n{tool_inst}\n\n{term_inst}"
    log.info("START task=%s sandbox=%s tools=%s think=%s", task[:80], sandbox, tools, think)

    turn = 0
    while True:
        log.info("TURN %d (%d chars)", turn, len(conversation))
        try:
            response = _call_ollama(conversation, model=model, think=think)
        except (TimeoutError, OSError):
            key = "is_planning_done" if mode == "plan" else "is_execution_done"
            return {key: False, "summary": f"[FAILED] timeout on turn {turn}"}
        log.info("TURN %d → %s", turn, response[:200])

        # Always save the model's response.
        conversation += f"\n\n{response}"

        # Extract all JSON objects from the response.
        objects = _extract_all_json(response)
        if not objects:
            conversation += "\n\nNo valid JSON found. Output a tool call or terminal response."
            if session_id:
                _save_session(sandbox, session_id, conversation)
            continue

        # Process each JSON object.
        for obj in objects:
            if _is_terminal(obj):
                log.info("TERMINAL: %s", json.dumps(obj)[:200])
                if session_id:
                    _save_session(sandbox, session_id, conversation)
                return obj

            tool_name = obj.get("tool")
            if tool_name is None:
                continue  # Skip non-tool, non-terminal JSON.

            args = obj.get("args", {})
            log.info("TOOL %s %s", tool_name, {k: (str(v)[:50]) for k, v in args.items()})

            result = _execute_tool(tool_name, args, sandbox, tools)
            log.info("RESULT: %s", result[:200])

            # Append tool result.
            if tool_name == "read_file":
                conversation += f"\n\nResult:\n{result[:3000]}"
            elif tool_name == "write_file":
                conversation += f"\n\nResult: wrote {args.get('path', '?')} ({len(args.get('content', ''))} chars) OK"
            elif tool_name == "edit_file":
                conversation += f"\n\nResult: edited {args.get('path', '?')} OK"
            elif tool_name == "list_files":
                conversation += f"\n\nResult:\n{result}"

        if session_id:
            _save_session(sandbox, session_id, conversation)
        turn += 1


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    argv = sys.argv[1:]
    enabled = []
    sid = None
    while argv and argv[0].startswith("--"):
        flag = argv.pop(0)
        if flag == "--read":
            enabled.append("read")
        elif flag == "--write":
            enabled.append("write")
        elif flag == "--session-id":
            sid = argv.pop(0)

    if len(argv) < 2:
        print(f"Usage: {sys.argv[0]} [--read] [--write] [--session-id ID] <sandbox> <task>")
        sys.exit(1)

    result = run(" ".join(argv[1:]), sandbox=argv[0], tools=enabled, session_id=sid)
    print(f"\nResult: {json.dumps(result, indent=2)}")
