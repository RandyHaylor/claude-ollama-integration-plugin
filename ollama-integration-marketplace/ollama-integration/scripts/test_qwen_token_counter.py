"""Tests for qwen_token_counter.py"""

import pytest
import qwen_token_counter


def test_count_returns_positive_integer():
    result = qwen_token_counter.count("hello world")
    assert isinstance(result, int)
    assert result > 0


def test_count_empty_string_returns_zero():
    result = qwen_token_counter.count("")
    assert result == 0


def test_truncate_short_text_unchanged():
    text = "hello world"
    result = qwen_token_counter.truncate(text, max_tokens=100000)
    assert result == text


def test_truncate_reduces_long_text():
    # Repeat a word enough times to exceed 1 token budget
    text = "hello " * 100
    result = qwen_token_counter.truncate(text, max_tokens=1)
    assert len(result) < len(text)
