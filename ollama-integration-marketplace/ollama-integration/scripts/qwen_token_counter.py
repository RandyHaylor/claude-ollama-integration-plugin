"""
qwen_token_counter.py — Token counting and truncation using Qwen2.5-Coder-32B tokenizer.

Provides:
  count(text: str) -> int
  truncate(text: str, max_tokens: int = 100000) -> str
"""

from __future__ import annotations

_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        from transformers import AutoTokenizer
        _tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-Coder-32B-Instruct")
    return _tokenizer


def count(text: str) -> int:
    """Return the number of tokens in text."""
    if not text:
        return 0
    tokenizer = _get_tokenizer()
    return len(tokenizer.encode(text, add_special_tokens=False))


def truncate(text: str, max_tokens: int = 100000) -> str:
    """Truncate text so it fits within max_tokens. Returns text unchanged if already within budget."""
    if not text:
        return text
    tokenizer = _get_tokenizer()
    token_ids = tokenizer.encode(text, add_special_tokens=False)
    if len(token_ids) <= max_tokens:
        return text
    truncated_ids = token_ids[:max_tokens]
    return tokenizer.decode(truncated_ids, skip_special_tokens=True)
