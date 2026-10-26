"""
Unit tests for live-board decline detection (design §4.2.4).

Run with:
    cd tests/unit && pytest test_decline.py -v
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from app.services.rag import decline
from app.services.rag.decline import DECLINE_PHRASES, is_decline, matched_decline_phrase


def test_prefix_is_a_decline_at_any_length():
    assert is_decline("INSUFFICIENT_CONTEXT")
    assert is_decline("  INSUFFICIENT_CONTEXT: the materials don't cover this." + " x" * 500)


@pytest.mark.parametrize("phrase", DECLINE_PHRASES)
def test_each_phrase_in_a_short_answer_is_a_decline(phrase):
    answer = f"Sorry, the course material {phrase} on that topic."
    assert matched_decline_phrase(answer) == phrase


def test_matching_ignores_case():
    assert is_decline("I CANNOT ANSWER that from the provided context.")


def test_long_answer_containing_a_phrase_is_not_a_decline():
    answer = "Slip days work as follows. " * 20 + "If you cannot answer the quiz, ask staff."
    assert len(answer) >= decline.MAX_DECLINE_CHARS
    assert not is_decline(answer)


def test_ordinary_answer_is_not_a_decline():
    assert not is_decline("You get three slip days for the semester (Syllabus > Late Policy).")


def test_prefix_must_lead():
    assert not is_decline("The token INSUFFICIENT_CONTEXT is what the prompt asks for. " * 10)


def test_module_has_no_imports():
    """eval/summarize.py loads decline.py by path, outside the backend (§11.3)."""
    tree = ast.parse(pathlib.Path(decline.__file__).read_text())
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
