"""Decline detection for live-board answers (design-rag.md §4.2.4).

No imports, so eval/summarize.py can load this file by path without the
backend's dependencies. The phrase list is the initial one, frozen before the
eval run (§11.3).
"""

DECLINE_PREFIX = "INSUFFICIENT_CONTEXT"
DECLINE_PHRASES = (
    "does not contain enough information",
    "doesn't contain enough information",
    "not enough information",
    "cannot answer",
    "can't answer",
    "no information about",
)
# Longer answers that happen to contain a phrase are real answers
MAX_DECLINE_CHARS = 400


def matched_decline_phrase(answer):
    """The prefix or phrase that makes `answer` a decline, or None."""
    text = answer.strip()
    if text.startswith(DECLINE_PREFIX):
        return DECLINE_PREFIX
    if len(text) >= MAX_DECLINE_CHARS:
        return None
    lowered = text.lower()
    for phrase in DECLINE_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def is_decline(answer):
    return matched_decline_phrase(answer) is not None
