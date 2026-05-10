"""
Metrics Tracker — Track API calls, token usage, success rates, and timing.

Provides observability into the operator's behavior without external dependencies.
"""

import time
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger("antigravity.metrics")


@dataclass
class LLMCallMetric:
    """Single LLM API call record."""
    model: str
    agent: str
    tokens_in: int
    tokens_out: int
    duration: float
    success: bool
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class MetricsTracker:
    """
    Tracks operator metrics for observability and debugging.
    
    Stores:
    - LLM call counts, tokens, and latency per model/agent
    - Task success/failure rates  
    - Error category frequencies
    - Session-level stats
    """

    def __init__(self, persist_path: str = None):
        self._calls: list[LLMCallMetric] = []
        self._task_results: dict = defaultdict(lambda: {"success": 0, "fail": 0})
        self._error_counts: dict = defaultdict(int)
        self._session_start = time.time()
        self._persist_path = Path(persist_path) if persist_path else None

    def record_llm_call(
        self,
        model: str,
        agent: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        duration: float = 0.0,
        success: bool = True,
    ):
        """Record an LLM API call."""
        metric = LLMCallMetric(
            model=model,
            agent=agent,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration=duration,
            success=success,
        )
        self._calls.append(metric)
        logger.debug(
            f"LLM call: {agent}/{model} — "
            f"{tokens_in}→{tokens_out} tokens, {duration:.2f}s, "
            f"{'ok' if success else 'FAIL'}"
        )

    def record_task_result(self, task_type: str, success: bool):
        """Record a task execution result."""
        key = "success" if success else "fail"
        self._task_results[task_type][key] += 1

    def record_error(self, category: str):
        """Record an error by category."""
        self._error_counts[category] += 1

    def get_summary(self) -> dict:
        """Get a complete metrics summary."""
        total_calls = len(self._calls)
        successful_calls = sum(1 for c in self._calls if c.success)
        total_tokens_in = sum(c.tokens_in for c in self._calls)
        total_tokens_out = sum(c.tokens_out for c in self._calls)
        total_duration = sum(c.duration for c in self._calls)

        # Per-model breakdown
        model_stats = defaultdict(lambda: {"calls": 0, "tokens": 0, "duration": 0.0})
        for c in self._calls:
            model_stats[c.model]["calls"] += 1
            model_stats[c.model]["tokens"] += c.tokens_in + c.tokens_out
            model_stats[c.model]["duration"] += c.duration

        return {
            "session_duration": time.time() - self._session_start,
            "llm_calls": {
                "total": total_calls,
                "successful": successful_calls,
                "failed": total_calls - successful_calls,
                "success_rate": (successful_calls / total_calls * 100) if total_calls else 0,
            },
            "tokens": {
                "total_input": total_tokens_in,
                "total_output": total_tokens_out,
                "total": total_tokens_in + total_tokens_out,
            },
            "timing": {
                "total_llm_seconds": round(total_duration, 2),
                "avg_call_seconds": round(total_duration / total_calls, 2) if total_calls else 0,
            },
            "models": dict(model_stats),
            "tasks": dict(self._task_results),
            "errors": dict(self._error_counts),
        }

    def save(self):
        """Persist metrics to disk."""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            summary = self.get_summary()
            # Convert nested defaultdicts
            summary["models"] = {k: dict(v) for k, v in summary["models"].items()}
            summary["tasks"] = {k: dict(v) for k, v in summary["tasks"].items()}
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")

    def print_summary(self):
        """Print a formatted metrics summary."""
        s = self.get_summary()
        lines = [
            f"Session Duration: {s['session_duration']:.1f}s",
            f"LLM Calls: {s['llm_calls']['total']} ({s['llm_calls']['success_rate']:.0f}% success)",
            f"Tokens: {s['tokens']['total']:,} (in: {s['tokens']['total_input']:,}, out: {s['tokens']['total_output']:,})",
            f"LLM Time: {s['timing']['total_llm_seconds']}s (avg: {s['timing']['avg_call_seconds']}s/call)",
        ]
        if s["errors"]:
            lines.append(f"Errors: {dict(s['errors'])}")
        return "\n".join(lines)
