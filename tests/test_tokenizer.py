"""Tests for the lexical tokenizer."""

from src.tokenizer import tokenize


def test_identifiers_are_kept_whole_and_split() -> None:
    tokens = tokenize("FusedMoEActivationFormat triton_flash_attention")
    assert "fusedmoeactivationformat" in tokens
    assert {"fused", "activation", "format"} <= set(tokens)
    assert "triton_flash_attention" in tokens
    assert {"triton", "flash", "attention"} <= set(tokens)


def test_stop_words_and_plurals() -> None:
    assert tokenize("the adapters of a model") == ["adapter", "model"]


def test_empty_and_symbols() -> None:
    assert tokenize("") == []
    assert tokenize("!!! ???") == []
