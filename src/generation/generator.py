"""Grounded answer generation with Qwen/Qwen3-0.6B.

The retrieved sources are placed in the prompt, in rank order, until a
token budget is exhausted.  The model is asked to answer only from that
context and to say so when the context does not contain the answer.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence

from src.models import ScoredSource

DEFAULT_MODEL = "Qwen/Qwen3-0.6B"
SYSTEM_PROMPT = (
    "You are a precise assistant answering questions about the vLLM "
    "codebase. Use ONLY the provided context snippets. Quote identifiers, "
    "values and commands exactly as they appear. If the context does not "
    "contain the answer, say that the context does not contain it. Answer "
    "in a few clear sentences, without repeating the question."
)
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _pick_device() -> str:
    """Choose the best available torch device."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and (
        torch.backends.mps.is_available()
    ):
        return "mps"
    return "cpu"


class Generator:
    """Generates answers from retrieved context with a causal LM.

    The model is loaded lazily on first use so that retrieval-only
    commands never pay for it.

    Args:
        model_name: Hugging Face model identifier.
        context_token_budget: Maximum number of tokens spent on sources.
        max_new_tokens: Maximum number of generated tokens.
        device: Torch device, or None to auto-detect.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        context_token_budget: int = 3000,
        max_new_tokens: int = 256,
        device: Optional[str] = None,
    ) -> None:
        self.model_name = model_name
        self.context_token_budget = context_token_budget
        self.max_new_tokens = max_new_tokens
        self.device = device
        self._tokenizer: Any = None
        self._model: Any = None

    def load(self) -> None:
        """Load the tokenizer and the model (idempotent)."""
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = self.device or _pick_device()
        dtype = torch.float32 if device == "cpu" else torch.float16
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        model: Any = AutoModelForCausalLM.from_pretrained(
            self.model_name, dtype=dtype
        )
        self._model = model.to(device)
        self._model.eval()
        self.device = device

    def count_tokens(self, text: str) -> int:
        """Number of tokens the model sees for ``text``."""
        self.load()
        return len(self._tokenizer.encode(text, add_special_tokens=False))

    def build_context(self, sources: Sequence[ScoredSource]) -> str:
        """Concatenate sources, in rank order, within the token budget.

        Args:
            sources: Retrieved sources, best first.

        Returns:
            The context block, possibly empty.
        """
        blocks: List[str] = []
        used = 0
        for rank, source in enumerate(sources, start=1):
            block = (
                f"[Source {rank}] {source.file_path} "
                f"(chars {source.first_character_index}-"
                f"{source.last_character_index})\n{source.text.strip()}\n"
            )
            cost = self.count_tokens(block)
            if used + cost > self.context_token_budget:
                if not blocks:
                    block = self._truncate(block)
                    blocks.append(block)
                break
            blocks.append(block)
            used += cost
        return "\n".join(blocks)

    def _truncate(self, text: str) -> str:
        """Cut a text down to the context token budget."""
        ids = self._tokenizer.encode(text, add_special_tokens=False)
        ids = ids[: self.context_token_budget]
        return str(self._tokenizer.decode(ids))

    def build_prompt(
        self, question: str, sources: Sequence[ScoredSource]
    ) -> str:
        """Render the chat prompt for a question and its sources."""
        self.load()
        context = self.build_context(sources) or "(no context retrieved)"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Context:\n{context}\n\nQuestion: {question}\n"
                    "Answer using only the context above."
                ),
            },
        ]
        return str(
            self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        )

    def answer(self, question: str, sources: Sequence[ScoredSource]) -> str:
        """Generate an answer grounded in the sources.

        Args:
            question: The user question.
            sources: Retrieved sources, best first.

        Returns:
            The generated answer, stripped of any reasoning block.
        """
        if not question.strip():
            return "The question is empty."
        if not sources:
            return (
                "No relevant source was retrieved for this question, so it "
                "cannot be answered from the codebase."
            )
        import torch

        prompt = self.build_prompt(question, sources)
        inputs = self._tokenizer(prompt, return_tensors="pt").to(
            self._model.device
        )
        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                repetition_penalty=1.1,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        generated = output[0][inputs["input_ids"].shape[1]:]
        text = str(self._tokenizer.decode(generated, skip_special_tokens=True))
        return _THINK_RE.sub("", text).strip()
