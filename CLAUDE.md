# claude-ollama-integration-plugin

A Claude Code plugin that exposes a local ollama model as a sandboxed task-execution agent. Gives Claude Code (or any orchestrator) a way to run tasks using a local LLM instead of a cloud model — with controlled file access, session persistence, and optional command execution.

## What this plugin does

The core is `ollama_writer` — a conversation loop that:
- Sends a task to a local ollama model
- Lets the model use sandboxed file tools (`read_file`, `write_file`, `edit_file`, `list_files`)
- Optionally lets the model run shell commands (`run_command`)
- Persists conversation across calls via `session_id` so the model can resume where it left off
- Returns a structured terminal response (`is_execution_done`, `run_command`, etc.)

## Repository structure

```
claude-ollama-integration-plugin/
  CLAUDE.md                          — this file
  examples/
    ollama_writer.py                 — the core agent loop (reference implementation)
  ollama-integration-marketplace/
    ollama-integration/              — the actual Claude Code plugin
      .claude-plugin/
        plugin.json
      scripts/
        ollama_writer.py
        qwen_token_counter.py
      skills/
        ollama-completion/
          SKILL.md                   — /ollama-integration:ollama-completion skill
```

## Prerequisites

### 1. Ollama running locally

```bash
ollama serve
ollama pull qwen3-coder:30b   # or your preferred model
```

Verify: `curl http://localhost:11434/api/tags`

### 2. Python dependencies

```bash
pip install transformers
```

The `qwen_token_counter` module uses the Qwen2.5-Coder-32B tokenizer to accurately count and truncate prompts. It downloads ~2MB of tokenizer files (no model weights) on first use.

## ollama_writer design

### Tools available to the model

The model is told about tools in its system prompt and must output one JSON tool call per response:

```json
{"tool": "read_file", "args": {"path": "rel/path"}}
{"tool": "read_file", "args": {"path": "rel/path", "start_line": 1, "end_line": 50}}
{"tool": "write_file", "args": {"path": "rel/path", "content": "full file content"}}
{"tool": "edit_file", "args": {"path": "rel/path", "old_string": "find this", "new_string": "replace with"}}
{"tool": "list_files", "args": {}}
```

All paths are relative to the sandbox directory. The sandbox is enforced — paths that escape it are rejected.

### Terminal responses

When the model is done (or wants to escalate), it returns a terminal JSON object. ollama_writer exits and returns it to the caller:

```json
{"is_execution_done": true, "summary": "what was accomplished"}
{"tool": "run_command", "args": {"command": "python3 script.py"}}
```

### run_command — two modes

**Terminal mode (default, `run_commands=False`):**
- `run_command` exits the loop and returns the call object to the caller
- The caller runs the command, gets the result, and resumes ollama_writer with the same `session_id`
- Used by NTT orchestrator to route commands through the message bus to Claude Code

**Self-executing mode (`run_commands=True`, planned):**
- ollama_writer runs the command itself via subprocess
- Injects the result into the conversation and continues the loop
- Used by the standalone `/ollama-integration:ollama-completion` skill

### Session persistence

Pass `session_id` to persist conversation across calls:

```python
result = ollama_writer.run(task, sandbox="/tmp/myproject", session_id="job-001", tools=["read", "write"])

# If result["tool"] == "run_command":
#   run the command
#   resume:
result2 = ollama_writer.run(resume_task, sandbox="/tmp/myproject", session_id="job-001", tools=["read", "write"])
```

Conversation is saved to `{sandbox}/.ollama-sessions/{session_id}/conversation.txt` after every turn. On the next call with the same `session_id`, the prior conversation is loaded and the model continues with full context.

### Token budget

Prompts are truncated to 100,000 tokens (real count via Qwen tokenizer) before being sent to ollama. This prevents context window overflows on long-running tasks.

## API reference

```python
result = ollama_writer.run(
    task: str,              # task description (used only if no session exists)
    sandbox: str | Path,    # working directory — model can only read/write here
    mode: str = "execute",  # "execute" or plan modes
    model: str = "qwen3-coder:30b",  # ollama model name
    tools: list[str] = [],  # enable "read" and/or "write"
    max_turns: int = None,  # limit turns (default: unlimited)
    session_id: str = None, # for session persistence and run_command resume
)
# Returns: dict — terminal response object from the model
```

## Verified behavior

Tested round-trip (from `examples/ollama_writer.py`, NTT scripts):

1. Task: "Write check.py that prints 2+2, then run it"
2. Turn 1: model writes `check.py` via `write_file`, then returns `{"tool": "run_command", "args": {"command": "python3 check.py"}}`
3. Caller runs `python3 check.py` → output: `4`
4. Turn 2: resume with same `session_id`, pass `"Command result: 4"`
5. Model returns `{"is_execution_done": true, "summary": "Created check.py and ran it, output was 4"}`

Full conversation persisted across turns via session file. Model saw its own prior tool calls and continued correctly.

## Integration patterns

### Standalone (skill calling ollama_writer directly)

```python
result = ollama_writer.run(
    task="Build a Flask hello-world app",
    sandbox="/tmp/my-flask-app",
    tools=["read", "write"],
    session_id="flask-job-001",
    run_commands=True,   # model executes commands itself (planned)
)
```

### Orchestrated (NTT-style, caller handles run_command)

```python
session_id = "node-root-1234"
while True:
    result = ollama_writer.run(task, sandbox=sandbox, session_id=session_id, tools=["read", "write"])
    if result.get("is_execution_done"):
        break
    if result.get("tool") == "run_command":
        command = result["args"]["command"]
        output = subprocess.run(command, shell=True, cwd=sandbox, capture_output=True, text=True).stdout
        task = f'Command result for "{command}": {output}\n\nContinue your task.'
        continue
```

## Model notes

- **qwen3-coder:30b** — recommended. Follows JSON tool format reliably, good at code tasks. Uses `/no_think` token to suppress reasoning output.
- Any ollama model works, but JSON output reliability varies. Smaller models (7B, 14B) work for simple tasks.
- Model is called at `http://localhost:11434/api/generate` with `stream: false`. Timeout: 180 seconds per turn.
