"""
Token Counter — Approximate token counting for context window management.

Uses a simple heuristic (chars / 4) for speed, with optional tiktoken support.
Prevents context window overflow by truncating intelligently.
"""

import logging
from typing import Optional

logger = logging.getLogger("antigravity.tokens")


class TokenCounter:
    """
    Approximate token counter for managing LLM context windows.
    
    Uses character-based estimation (1 token ≈ 4 chars for English).
    Good enough for local models where exact counts aren't critical.
    """

    # Approximate ratio: 1 token ≈ 4 characters for English text
    CHARS_PER_TOKEN = 4

    def __init__(self, model_context_windows: dict = None, output_reserve: int = 4096):
        self._context_windows = model_context_windows or {}
        self._output_reserve = output_reserve

    def count_tokens(self, text: str) -> int:
        """Estimate token count for a string."""
        if not text:
            return 0
        return max(1, len(text) // self.CHARS_PER_TOKEN)

    def count_messages_tokens(self, messages: list[dict]) -> int:
        """Estimate total tokens in a message list (OpenAI/Ollama format)."""
        total = 0
        for msg in messages:
            # ~4 tokens overhead per message for role, separators
            total += 4
            content = msg.get("content", "")
            total += self.count_tokens(content)
        return total

    def get_context_limit(self, model: str) -> int:
        """Get the context window size for a model."""
        # Try exact match first
        if model in self._context_windows:
            return self._context_windows[model]
        # Try base name match
        base = model.split(":")[0] if ":" in model else model
        for key, value in self._context_windows.items():
            if key.startswith(base):
                return value
        # Default fallback
        return 8192

    def get_available_tokens(self, model: str, messages: list[dict]) -> int:
        """Calculate how many tokens are still available for new content."""
        limit = self.get_context_limit(model)
        used = self.count_messages_tokens(messages)
        available = limit - used - self._output_reserve
        return max(0, available)

    def truncate_to_fit(
        self,
        text: str,
        max_tokens: int,
        strategy: str = "tail",
    ) -> str:
        """
        Truncate text to fit within a token budget.
        
        Args:
            text: The text to potentially truncate
            max_tokens: Maximum allowed tokens
            strategy: 'tail' (keep end), 'head' (keep start), 'middle' (keep both ends)
            
        Returns:
            Truncated text with indicator if truncated
        """
        current_tokens = self.count_tokens(text)
        if current_tokens <= max_tokens:
            return text

        max_chars = max_tokens * self.CHARS_PER_TOKEN

        if strategy == "head":
            return text[:max_chars] + "\n... [TRUNCATED — showing first portion]"
        elif strategy == "tail":
            return "... [TRUNCATED — showing last portion]\n" + text[-max_chars:]
        elif strategy == "middle":
            half = max_chars // 2
            return (
                text[:half]
                + "\n... [TRUNCATED — middle removed] ...\n"
                + text[-half:]
            )
        else:
            return text[:max_chars] + "\n... [TRUNCATED]"

    def fit_messages_to_context(
        self,
        messages: list[dict],
        model: str,
        preserve_system: bool = True,
        preserve_last_n: int = 2,
    ) -> list[dict]:
        """
        Trim messages to fit within the model's context window.
        
        Preserves system message and most recent messages,
        drops oldest non-essential messages first.
        
        Args:
            messages: List of message dicts
            model: Model name (to look up context window)
            preserve_system: Always keep the system message
            preserve_last_n: Always keep the last N messages
            
        Returns:
            Trimmed message list that fits in context
        """
        limit = self.get_context_limit(model) - self._output_reserve

        if self.count_messages_tokens(messages) <= limit:
            return messages

        # Separate protected and droppable messages
        system_msgs = []
        other_msgs = []
        
        for msg in messages:
            if preserve_system and msg.get("role") == "system":
                system_msgs.append(msg)
            else:
                other_msgs.append(msg)

        # Protected tail
        protected_tail = other_msgs[-preserve_last_n:] if preserve_last_n else []
        droppable = other_msgs[:-preserve_last_n] if preserve_last_n else other_msgs

        # Build result, adding droppable messages from newest to oldest
        result = system_msgs.copy()
        remaining_budget = limit - self.count_messages_tokens(system_msgs + protected_tail)

        kept = []
        for msg in reversed(droppable):
            msg_tokens = self.count_tokens(msg.get("content", "")) + 4
            if remaining_budget >= msg_tokens:
                kept.insert(0, msg)
                remaining_budget -= msg_tokens
            else:
                break

        result.extend(kept)
        result.extend(protected_tail)

        logger.info(
            f"Trimmed messages: {len(messages)} → {len(result)} "
            f"(dropped {len(messages) - len(result)} to fit {limit} token limit)"
        )
        return result
