![claude+ollama](claude+ollama.jpg)

# claude-ollama-integration-plugin

A Claude Code plugin that exposes a local [ollama](https://ollama.com) model as a sandboxed task-execution agent. Gives Claude Code (or any orchestrator) a way to run tasks using a local LLM instead of a cloud model — with controlled file access, session persistence, and configurable reasoning effort.

## What it does

The core is `ollama_writer` — a conversation loop that:

- Sends a task prompt to a local ollama model
- Lets the model use sandboxed file tools (`read_file`, `write_file`, `edit_file`, `list_files`)
- Optionally lets the model run shell commands (`run_command`)
- Persists conversation across calls via `session_id` so the model can resume where it left off
- Supports a `think` parameter (`"low"` / `"medium"` / `"high"`) for models that expose reasoning effort (e.g. qwen3)
- Returns a structured terminal response (`is_execution_done`, `run_command`, etc.)

## Repository structure

```
claude-ollama-integration-plugin/
  README.md
  CLAUDE.md                               — design spec and API reference
  examples/
    ollama_writer.py                      — reference implementation (standalone)
  ollama-integration-marketplace/
    .claude-plugin/
      marketplace.json                    — marketplace manifest
    ollama-integration/                   — the Claude Code plugin
      .claude-plugin/
        plugin.json
      scripts/
        ollama_writer.py                  — agent loop (matches examples/)
        qwen_token_counter.py             — token counting via Qwen tokenizer
        test_qwen_token_counter.py
      skills/
        ollama-completion/
          SKILL.md                        — /ollama-integration:ollama-completion skill
      tests/
        test_plugin_structure.py
```

## Prerequisites

### 1. Ollama running locally

```bash
ollama serve
ollama pull qwen3-coder:30b   # or any supported model
```

Verify: `curl http://localhost:11434/api/tags`

### 2. Python dependency

```bash
pip install transformers
```

The `qwen_token_counter` module uses the Qwen2.5-Coder-32B tokenizer (downloads ~2MB of tokenizer config on first use — no model weights).

## Installation as a Claude Code plugin

```bash
# 1. Add the local marketplace
claude plugin marketplace add /path/to/claude-ollama-integration-plugin/ollama-integration-marketplace

# 2. Install the plugin
claude plugin install ollama-integration@ollama-integration-marketplace
```

Then use the skill:

```
/ollama-integration:ollama-completion
```

## Usage from Python

```python
import sys
sys.path.insert(0, "ollama-integration-marketplace/ollama-integration/scripts")
import ollama_writer

result = ollama_writer.run(
    task="Write a Flask hello-world app",
    sandbox="/tmp/my-flask-app",
    tools=["read", "write"],
    session_id="flask-job-001",
    think="low",   # optional: "low", "medium", "high"
)
```

### Handling `run_command`

When the model wants to execute a command, `run()` returns immediately with a `run_command` object. The caller runs the command and resumes with the same `session_id`:

```python
session_id = "my-session"
task = "Write check.py that prints 2+2, then run it"

while True:
    result = ollama_writer.run(task, sandbox="/tmp/sandbox", session_id=session_id, tools=["read", "write"])

    if result.get("is_execution_done"):
        print(result["summary"])
        break

    if result.get("tool") == "run_command":
        import subprocess
        command = result["args"]["command"]
        proc = subprocess.run(command, shell=True, cwd="/tmp/sandbox", capture_output=True, text=True)
        task = f'Command result for "{command}":\n{proc.stdout}{proc.stderr}\n\nContinue your task.'
        continue
```

## API reference

```python
result = ollama_writer.run(
    task: str,              # task description (ignored if session already exists)
    sandbox: str | Path,    # working directory — model can only read/write here
    mode: str = "execute",  # "execute" or plan modes
    model: str = "qwen3-coder:30b",
    tools: list[str] = [],  # enable "read" and/or "write"
    max_turns: int = None,
    session_id: str = None,
    think: str = None,      # "low", "medium", "high", or None (model default)
)
# Returns: dict — terminal response from the model
```

## think level

For OpenAI-style models via ollama (e.g. qwen3), the `think` parameter controls reasoning effort:

| Level | Behavior |
|-------|----------|
| `"low"` | Brief, direct, closely follows your instructions. Often more accurate for well-specified tasks. |
| `"medium"` | Balanced reasoning effort. |
| `"high"` | Extended reasoning, infers user needs and fills in gaps. May introduce assumptions. |
| omitted | Uses model default. |

## Tools available to the model

The model receives tool descriptions in its system prompt and must output one JSON tool call per response:

```json
{"tool": "read_file",  "args": {"path": "rel/path"}}
{"tool": "read_file",  "args": {"path": "rel/path", "start_line": 1, "end_line": 50}}
{"tool": "write_file", "args": {"path": "rel/path", "content": "full file content"}}
{"tool": "edit_file",  "args": {"path": "rel/path", "old_string": "find this", "new_string": "replace with"}}
{"tool": "list_files", "args": {}}
```

All paths are relative to the sandbox. Paths that escape the sandbox are rejected.

## Session persistence

Conversation is saved to `{sandbox}/.ollama-sessions/{session_id}/conversation.txt` after every turn. Pass the same `session_id` on the next call to resume with full context.

## Model notes

- **qwen3-coder:30b** — recommended. Reliable JSON tool output, strong at code tasks.
- Any ollama model works; JSON output reliability varies with smaller models.
- API endpoint: `http://localhost:11434/api/generate` with `stream: false`. Timeout: 180s per turn.
