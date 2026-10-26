"""Chunk tokens (design-rag.md Terms): all-MiniLM-L6-v2 WordPiece tokens,
without [CLS]/[SEP], for every profile whatever its embedding model."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tokenizers import Tokenizer

TOKENIZER_PATH = Path(__file__).parent / "assets" / "minilm_tokenizer.json"


@dataclass(frozen=True)
class Token:
    """Character span [start, end) of one token in the original text."""

    start: int
    end: int


@lru_cache(maxsize=1)
def _tokenizer() -> Tokenizer:
    tok = Tokenizer.from_file(str(TOKENIZER_PATH))
    # The vendored file truncates and pads to 128; chunk sizes need real counts
    tok.no_truncation()
    tok.no_padding()
    return tok


def tokenize(text: str) -> list[Token]:
    """Tokens with offsets into `text` (they survive lowercasing and accents)."""
    encoding = _tokenizer().encode(text, add_special_tokens=False)
    return [Token(a, b) for a, b in encoding.offsets]


def count_tokens(text: str) -> int:
    return len(_tokenizer().encode(text, add_special_tokens=False).ids)
