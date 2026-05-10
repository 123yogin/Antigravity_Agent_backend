"""
Router Agent — Classifies tasks and routes them to the appropriate specialized agent.

Uses the fast ROUTER_MODEL (llama3.2) for quick classification decisions.
Determines task type, complexity, and optimal handling strategy.
"""

import json
import logging
import time
from pathlib import Path
import ollama
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from configs.settings import (
    ROUTER_MODEL, MODEL_FALLBACK_CHAIN,
    MODEL_CONTEXT_WINDOWS, OUTPUT_TOKEN_RESERVE,
)
from utils.token_counter import TokenCounter
from utils.metrics import MetricsTracker
from core.schemas import TaskClassification

logger = logging.getLogger("antigravity.router")


ROUTER_SYSTEM_PROMPT = """You are a task router. Classify incoming tasks to determine the right handler.

TASK TYPES:
- terminal: Commands to run (install, build, run, test, create dirs)
- file: Create or edit files (write code, create configs, edit content)
- browser: Web interactions (navigate URLs, scrape, fill forms)
- validate: Verification checks (test endpoints, check files exist, verify output)
- compound: Multi-step tasks that need to be broken into subtasks

COMPLEXITY:
- simple: One-step, obvious action (e.g., "install flask")
- moderate: Requires some reasoning (e.g., "create a REST API endpoint")
- complex: Multi-step or requires deep understanding (e.g., "refactor the auth system")

Classify the task and call the classify_task function."""


class RouterAgent:
    """
    Fast task classifier using the lightweight router model.
    
    Routes tasks to the appropriate specialized agent based on type and complexity.
    """

    def __init__(self, model=None, metrics=None):
        self.model = model or ROUTER_MODEL
        self._token_counter = TokenCounter(MODEL_CONTEXT_WINDOWS, OUTPUT_TOKEN_RESERVE)
        self._metrics = metrics

    def classify(self, task: str) -> dict:
        """
        Classify a task to determine how it should be handled.
        
        Args:
            task: The task string to classify
            
        Returns:
            dict with task_type, complexity, needs_context, subtasks
        """
        # Quick heuristic pre-check for obvious cases
        quick = self._quick_classify(task)
        if quick:
            return quick

        messages = [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": f"CLASSIFY THIS TASK: {task}"},
        ]

        models_to_try = [self.model] + MODEL_FALLBACK_CHAIN.get(self.model, [])

        for model in models_to_try:
            try:
                start = time.time()
                response = ollama.chat(
                    model=model, messages=messages,
                    format=TaskClassification.model_json_schema(),
                    options={"temperature": 0.0, "num_predict": 256},
                )
                duration = time.time() - start

                if self._metrics:
                    self._metrics.record_llm_call(
                        model=model, agent="router",
                        tokens_in=self._token_counter.count_messages_tokens(messages),
                        tokens_out=50, duration=duration, success=True,
                    )

                raw = response.get("message", {}).get("content", "")
                if raw:
                    parsed = TaskClassification.model_validate_json(raw)
                    logger.info(f"Classified '{task[:60]}' → {parsed.task_type} ({parsed.complexity})")
                    return parsed.model_dump()
                

            except Exception as e:
                logger.warning(f"Router model {model} failed: {e}")
                continue

        # Ultimate fallback
        return self._quick_classify(task) or {
            "task_type": "terminal", "complexity": "moderate",
            "needs_context": False, "subtasks": [],
        }

    def _quick_classify(self, task: str) -> dict | None:
        """
        Fast heuristic classification for obvious task types.
        Returns None if not obvious enough for heuristic.
        """
        task_lower = task.lower().strip()

        # Already has a type prefix
        if ":" in task:
            prefix = task.split(":")[0].strip().lower()
            if prefix in ("terminal", "file", "browser", "validate"):
                return {
                    "task_type": prefix,
                    "complexity": "simple",
                    "needs_context": prefix == "file",
                    "subtasks": [],
                }

        # Terminal indicators
        terminal_words = ["install", "run ", "execute", "pip ", "npm ", "mkdir", "start ", "build ", "test "]
        if any(w in task_lower for w in terminal_words):
            return {"task_type": "terminal", "complexity": "simple", "needs_context": False, "subtasks": []}

        # File indicators
        file_words = ["create ", "write ", "edit ", "modify ", "update file", "add to file"]
        if any(w in task_lower for w in file_words):
            return {"task_type": "file", "complexity": "moderate", "needs_context": True, "subtasks": []}

        # Browser indicators
        browser_words = ["http://", "https://", "navigate", "browse", "scrape", "open url"]
        if any(w in task_lower for w in browser_words):
            return {"task_type": "browser", "complexity": "moderate", "needs_context": False, "subtasks": []}

        # Validate indicators
        validate_words = ["check ", "verify ", "test ", "validate ", "confirm "]
        if any(w in task_lower for w in validate_words):
            return {"task_type": "validate", "complexity": "simple", "needs_context": False, "subtasks": []}

        return None

