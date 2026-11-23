"""Lexical tokenizer shared by the indexer and the retriever.

Questions rarely use the exact same words as the code they refer to: they
paraphrase an idea, or quote an identifier verbatim.  To match both, every
identifier is kept as a whole token *and* split into its camelCase /
snake_case parts.  ``FusedMoEActivationFormat`` therefore yields
``fusedmoeactivationformat``, ``fused``, ``moe``, ``activation`` and
``format``.
"""

from __future__ import annotations

import re
from typing import List

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(
    r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+"
)

STOP_WORDS: frozenset[str] = frozenset(
    """
    a an the and or of to in on for with by as at from is are was were be
    been being it its this that these those there here what which who whom
    whose when where why how do does did doing done can could should would
    will shall may might must have has had having not no nor so than then
    if else into over under out up down about between through during
    before after above below any each few more most other some such only
    own same too very just also i you he she we they them their our your
    me my him her us
    """.split()
)


def _strip_plural(token: str) -> str:
    """Remove a trailing plural ``s`` from long enough tokens."""
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _split_identifier(word: str) -> List[str]:
    """Split ``snake_case`` and ``camelCase`` identifiers into parts."""
    parts: List[str] = []
    for piece in word.split("_"):
        if not piece:
            continue
        parts.extend(match.group(0) for match in _CAMEL_RE.finditer(piece))
    return parts


def tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase lexical tokens.

    Args:
        text: Any natural-language or source text.

    Returns:
        The list of tokens, with stop words removed.  Identifiers appear
        both whole and split into their parts.
    """
    tokens: List[str] = []
    for match in _WORD_RE.finditer(text):
        word = match.group(0)
        whole = word.lower()
        parts = _split_identifier(word)
        lowered_parts = [_strip_plural(part.lower()) for part in parts]
        if len(lowered_parts) > 1:
            if whole not in STOP_WORDS:
                tokens.append(whole)
            tokens.extend(
                part for part in lowered_parts if part not in STOP_WORDS
            )
        else:
            stripped = _strip_plural(whole)
            if stripped not in STOP_WORDS and stripped:
                tokens.append(stripped)
    return tokens
