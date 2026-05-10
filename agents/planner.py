"""
Planner Agent — Converts a user goal into an ordered list of executable tasks.

Uses Ollama's native tool-calling API for structured output.
Receives project state context and memory for informed planning.
"""

import json
import logging
import time
from pathlib import Path

import ollama

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from configs.settings import (
    CODER_MODEL, PROMPTS_DIR, MAX_PLAN_STEPS,
    MODEL_CONTEXT_WINDOWS, OUTPUT_TOKEN_RESERVE, MODEL_FALLBACK_CHAIN,
)
from utils.token_counter import TokenCounter
from utils.metrics import MetricsTracker
from core.schemas import ExecutionPlan

logger = logging.getLogger("antigravity.planner")



class PlannerAgent:
    """
    Goal → Task List agent.
    
    Takes a high-level user goal and produces an ordered list of
    concrete, executable tasks that other agents can perform.
    
    Uses Ollama tool-calling for reliable structured output,
    with fallback to JSON text parsing.
    """

    def __init__(self, model: str = None, metrics: MetricsTracker = None):
        self.model = model or CODER_MODEL
        self._system_prompt = self._load_prompt()
        self._token_counter = TokenCounter(MODEL_CONTEXT_WINDOWS, OUTPUT_TOKEN_RESERVE)
        self._metrics = metrics

    def _load_prompt(self) -> str:
        """Load the planner system prompt from file."""
        prompt_file = PROMPTS_DIR / "planner.txt"
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return (
            "You are a task planner. Break the user's goal into a JSON array "
            "of concrete, ordered task strings. Output ONLY the JSON array."
        )

    def _call_llm(self, messages: list[dict]) -> dict:
        """
        Call the LLM using Pydantic format schemas.
        Includes model fallback chain support.
        """
        models_to_try = [self.model] + MODEL_FALLBACK_CHAIN.get(self.model, [])

        for model in models_to_try:
            try:
                start = time.time()
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "options": {"temperature": 0.3, "num_predict": 2048},
                    "format": ExecutionPlan.model_json_schema()
                }

                response = ollama.chat(**kwargs)
                duration = time.time() - start

                if self._metrics:
                    content = response.get("message", {}).get("content", "")
                    self._metrics.record_llm_call(
                        model=model,
                        agent="planner",
                        tokens_in=self._token_counter.count_messages_tokens(messages),
                        tokens_out=self._token_counter.count_tokens(content),
                        duration=duration,
                        success=True,
                    )

                return response

            except Exception as e:
                logger.warning(f"Model {model} failed: {e}")
                if self._metrics:
                    self._metrics.record_llm_call(
                        model=model, agent="planner",
                        tokens_in=0, tokens_out=0, duration=0, success=False,
                    )
                continue

        raise RuntimeError(f"All models failed: {models_to_try}")

    def plan(
        self,
        goal: str,
        context: str = "",
        project_state: str = "",
        execution_history: list[dict] = None,
    ) -> list[str]:
        """
        Generate a task plan from a user goal.
        
        Args:
            goal: The user's high-level objective
            context: Memory context from past experiences
            project_state: Current project file tree and state
            execution_history: Results from previously executed tasks
            
        Returns:
            Ordered list of task strings
        """
        logger.info(f"Planning for goal: {goal[:100]}...")

        messages = [
            {"role": "system", "content": self._system_prompt},
        ]

        # Build rich user message with all available context
        user_parts = []
        
        if project_state:
            user_parts.append(f"CURRENT PROJECT STATE:\n{project_state}")
        
        if context:
            user_parts.append(f"RELEVANT PAST EXPERIENCE:\n{context}")
        
        if execution_history:
            history_str = "\n".join(
                f"  {'✓' if h.get('success') else '✗'} {h.get('task', '')} → {h.get('output', h.get('error', ''))[:100]}"
                for h in execution_history[-5:]  # Last 5 results
            )
            user_parts.append(f"EXECUTION HISTORY:\n{history_str}")
        
        user_parts.append(f"GOAL: {goal}")
        
        messages.append({
            "role": "user",
            "content": "\n\n".join(user_parts),
        })

        # Fit messages to context window
        messages = self._token_counter.fit_messages_to_context(messages, self.model)

        try:
            response = self._call_llm(messages)
            raw = response.get("message", {}).get("content", "")
            
            if not raw:
                return ["ERROR: Empty response from planner"]

            plan_data = ExecutionPlan.model_validate_json(raw)
            logger.info(f"Plan reasoning: {plan_data.reasoning[:200]}")
            
            tasks = plan_data.tasks
            if len(tasks) > MAX_PLAN_STEPS:
                logger.warning(f"Plan has {len(tasks)} steps, truncating to {MAX_PLAN_STEPS}")
                tasks = tasks[:MAX_PLAN_STEPS]
            
            logger.info(f"Plan generated: {len(tasks)} tasks")
            return tasks

        except Exception as e:
            logger.error(f"Planning failed: {e}")
            return [f"ERROR: Planning failed — {str(e)}"]

    def replan(
        self,
        goal: str,
        completed: list[str],
        failed_task: str,
        error: str,
        error_category: str = "",
    ) -> list[str]:
        """
        Generate a recovery plan after a task failure.
        
        Args:
            goal: Original user goal
            completed: Tasks that completed successfully
            failed_task: The task that failed
            error: Error message from the failure
            error_category: Classified error type
            
        Returns:
            New list of tasks to attempt
        """
        recovery_hint = ""
        if error_category == "dependency":
            recovery_hint = "This is a missing dependency error. Install the required package first."
        elif error_category == "syntax":
            recovery_hint = "This is a code syntax error. Regenerate the file with corrected syntax."
        elif error_category == "permission":
            recovery_hint = "This is a permission error. Try with appropriate permissions or a different path."
        elif error_category == "file":
            recovery_hint = "File not found. Check the path and create the file if needed."

        context = (
            f"ORIGINAL GOAL: {goal}\n"
            f"COMPLETED TASKS: {json.dumps(completed)}\n"
            f"FAILED TASK: {failed_task}\n"
            f"ERROR: {error}\n"
            f"ERROR TYPE: {error_category}\n"
        )
        if recovery_hint:
            context += f"RECOVERY HINT: {recovery_hint}\n"
        
        context += (
            "\nGenerate a RECOVERY plan. Fix the failed task and continue toward the goal. "
            "Do NOT repeat already completed tasks."
        )
        return self.plan(f"RECOVER AND CONTINUE: {goal}", context=context)


# ─── Quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel
    console = Console()

    agent = PlannerAgent()
    
    goal = "Create a FastAPI server with a /health endpoint and automatic reload"
    console.print(Panel(f"[bold]Goal:[/] {goal}", title="Planner Agent Test"))
    
    tasks = agent.plan(goal)
    for i, task in enumerate(tasks, 1):
        console.print(f"  {i}. {task}")
