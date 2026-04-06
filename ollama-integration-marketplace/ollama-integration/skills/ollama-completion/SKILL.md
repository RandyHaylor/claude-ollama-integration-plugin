# ollama-completion

Run a task using a local ollama model via the sandboxed `ollama_writer` agent loop.

## When to use this skill

Use this skill when the user wants to delegate a coding or file-manipulation task to a local ollama model instead of the cloud Claude model.

## Inputs

- **task** (required) — A description of what the local model should do.
- **sandbox** (required) — Absolute path to the working directory. The model can only read/write files inside this directory.
- **model** (optional, default: `qwen3-coder:30b`) — The ollama model name to use.
- **session_id** (optional) — A string ID for persisting conversation across multiple calls. Pass the same ID to resume a previous session.
- **tools** (optional, default: `["read", "write"]`) — Which file tools to enable. Valid values: `"read"`, `"write"`.
- **think** (optional, default: omitted) — Reasoning effort level: `"low"`, `"medium"`, or `"high"`. Supported by OpenAI-style models via ollama (e.g. qwen3). Omit for models that don't support it.

## Ask the user: think level

Before running, ask the user which think level to use:

> **Think level** — controls how much the model reasons before responding.
>
> - **low** — brief, direct, follows your instructions closely. Does not mean "dumb" — often *more* accurate because it stays closer to what you asked.
> - **medium** — balanced reasoning effort.
> - **high** — extended reasoning, infers user needs and fills in gaps. Can be powerful but may introduce assumptions you didn't intend.
> - **omit** — use the model's default (no `think` parameter sent).

Pass the chosen value as `think="low"` / `think="medium"` / `think="high"` to `ollama_writer.run()`, or omit it entirely.

## How to invoke

```python
import sys
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/scripts")
import ollama_writer

result = ollama_writer.run(
    task=task,
    sandbox=sandbox,
    model=model,           # optional
    tools=["read", "write"],
    session_id=session_id, # optional
)
```

## Handling the result

The model returns a terminal response dict. There are two cases:

### Case 1: Task complete

```json
{"is_execution_done": true, "summary": "what was accomplished"}
```

Return the summary to the user.

### Case 2: run_command requested

```json
{"tool": "run_command", "args": {"command": "python3 script.py"}}
```

When the model returns `run_command`, execute the command in the sandbox directory and resume the session:

```python
import subprocess

while True:
    result = ollama_writer.run(task, sandbox=sandbox, session_id=session_id, tools=["read", "write"])

    if result.get("is_execution_done"):
        print(result.get("summary"))
        break

    if result.get("tool") == "run_command":
        command = result["args"]["command"]
        proc = subprocess.run(command, shell=True, cwd=sandbox, capture_output=True, text=True)
        output = proc.stdout + proc.stderr
        task = f'Command result for "{command}":\n{output}\n\nContinue your task.'
        continue
```

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
    think: str = None,      # "low", "medium", "high", or None (omit)
)
# Returns: dict — terminal response object from the model
```

## Session persistence

Conversation is saved to `{sandbox}/.ollama-sessions/{session_id}/conversation.txt` after every turn. Passing the same `session_id` on the next call resumes the conversation with full context.

## Prerequisites

- ollama must be running locally: `ollama serve`
- The chosen model must be pulled: `ollama pull qwen3-coder:30b`
- Python package: `pip install transformers` (for the Qwen tokenizer used by `qwen_token_counter`)
