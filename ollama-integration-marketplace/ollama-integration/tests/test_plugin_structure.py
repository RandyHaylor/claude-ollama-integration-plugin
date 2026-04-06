"""
Tests for plugin structure: ollama_writer copy, plugin.json, and SKILL.md.
"""

import json
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent.parent
REPO_ROOT = PLUGIN_ROOT.parent.parent


# ---------------------------------------------------------------------------
# Feature 2: ollama_writer.py copy is identical to the original
# ---------------------------------------------------------------------------

def test_ollama_writer_exists():
    assert (PLUGIN_ROOT / "scripts" / "ollama_writer.py").exists(), \
        "scripts/ollama_writer.py does not exist"


def test_ollama_writer_identical_to_original():
    original = (REPO_ROOT / "examples" / "ollama_writer.py").read_bytes()
    copy = (PLUGIN_ROOT / "scripts" / "ollama_writer.py").read_bytes()
    assert original == copy, "scripts/ollama_writer.py is not byte-for-byte identical to examples/ollama_writer.py"


# ---------------------------------------------------------------------------
# Feature 3: plugin.json is valid and well-formed
# ---------------------------------------------------------------------------

def test_plugin_json_exists():
    assert (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").exists(), \
        ".claude-plugin/plugin.json does not exist"


def test_plugin_json_is_valid_json():
    path = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    content = path.read_text(encoding="utf-8")
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        raise AssertionError(f"plugin.json is not valid JSON: {e}")


def test_plugin_json_name():
    path = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("name") == "ollama-integration", \
        f"Expected name 'ollama-integration', got {data.get('name')!r}"


def test_plugin_json_references_skill():
    path = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    content = path.read_text(encoding="utf-8")
    assert "ollama-completion" in content, \
        "plugin.json does not reference the 'ollama-completion' skill"


# ---------------------------------------------------------------------------
# Feature 4: SKILL.md exists and contains key content
# ---------------------------------------------------------------------------

def test_skill_md_exists():
    assert (PLUGIN_ROOT / "skills" / "ollama-completion" / "SKILL.md").exists(), \
        "skills/ollama-completion/SKILL.md does not exist"


def test_skill_md_references_ollama_writer():
    path = PLUGIN_ROOT / "skills" / "ollama-completion" / "SKILL.md"
    content = path.read_text(encoding="utf-8")
    assert "ollama_writer" in content, \
        "SKILL.md does not reference 'ollama_writer'"


def test_skill_md_references_run_command():
    path = PLUGIN_ROOT / "skills" / "ollama-completion" / "SKILL.md"
    content = path.read_text(encoding="utf-8")
    assert "run_command" in content, \
        "SKILL.md does not reference 'run_command'"
