"""
Browser Agent — Interprets tasks and drives the browser tool autonomously.

Uses Ollama's native tool-calling to map natural language tasks to browser actions
(navigate, click, fill, extract).
"""

import json
import logging
import time
from pathlib import Path
import ollama
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from configs.settings import (
    CODER_MODEL, PROMPTS_DIR, MAX_RETRIES,
    MODEL_CONTEXT_WINDOWS, OUTPUT_TOKEN_RESERVE, MODEL_FALLBACK_CHAIN,
)
from tools.browser_tool import BrowserResult
from utils.token_counter import TokenCounter
from utils.metrics import MetricsTracker
from mcp_bridge.client import get_mcp_client

logger = logging.getLogger("antigravity.browser_agent")

BROWSER_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "browser_action",
        "description": "Perform an action in the web browser.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["navigate", "get_text", "screenshot", "click", "fill", "close"],
                    "description": "The browser action to perform."
                },
                "url": {"type": "string", "description": "URL to navigate to (for 'navigate' action)"},
                "selector": {"type": "string", "description": "CSS selector (for 'click', 'fill' actions)"},
                "value": {"type": "string", "description": "Text to fill (for 'fill' action)"},
                "path": {"type": "string", "description": "File path (for 'screenshot' action)"},
            },
            "required": ["action"]
        }
    }
}


class BrowserAgent:
    """Agent that drives web automation tasks."""

    def __init__(self, headless=True, model=None, metrics=None):
        self.model = model or CODER_MODEL
        self.mcp = get_mcp_client()
        self._token_counter = TokenCounter(MODEL_CONTEXT_WINDOWS, OUTPUT_TOKEN_RESERVE)
        self._metrics = metrics
        self._system_prompt = self._load_prompt()

    def _load_prompt(self):
        prompt_file = PROMPTS_DIR / "browser_agent.txt"
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return "You are a browser agent. Choose the correct browser action to fulfill the task."

    def _call_llm(self, messages):
        models_to_try = [self.model] + MODEL_FALLBACK_CHAIN.get(self.model, [])
        for model in models_to_try:
            try:
                start = time.time()
                response = ollama.chat(
                    model=model, messages=messages,
                    tools=[BROWSER_TOOL_DEF],
                    options={"temperature": 0.1, "num_predict": 512},
                )
                duration = time.time() - start
                if self._metrics:
                    self._metrics.record_llm_call(model=model, agent="browser",
                        tokens_in=self._token_counter.count_messages_tokens(messages),
                        tokens_out=self._token_counter.count_tokens(response.get("message",{}).get("content","")),
                        duration=duration, success=True)
                return response
            except Exception as e:
                logger.warning(f"Model {model} failed: {e}")
                continue
        raise RuntimeError(f"All models failed: {models_to_try}")

    def execute_task(self, task: str, state=None) -> BrowserResult:
        logger.info(f"Browser task: {task}")
        
        user_msg = ""
        if state and state.completed:
            recent_tasks = "\n".join([f"- {r.task}: {r.output[:200]}" for r in state.completed[-3:]])
            user_msg += f"RECENT EXECUTION CONTEXT:\n{recent_tasks}\n\n"
        user_msg += f"TASK: {task}"
        
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_msg}
        ]
        
        try:
            response = self._call_llm(messages)
            msg = response.get("message", {})
            tool_calls = msg.get("tool_calls", [])
            
            action_args = {}
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    if fn.get("name") == "browser_action":
                        action_args = fn.get("arguments", {})
                        break
            
            if not action_args:
                # Naive fallback
                if "http" in task:
                    url = [w for w in task.split() if w.startswith("http")][0]
                    action_args = {"action": "navigate", "url": url}
                else:
                    return BrowserResult("unknown", False, "Could not determine browser action.")

            action = action_args.pop("action", None)
            if not action:
                return BrowserResult("unknown", False, "No browser action specified.")
            
            
            logger.info(f"Browser executing via MCP: {action} ({action_args})")
            output = self.mcp.call_tool("browser_action", {"action": action, **action_args})
            success = not output.startswith("ERROR")
            
            return BrowserResult(action, success, output if not success else "Action completed", data=output if success else "")
            
        except Exception as e:
            return BrowserResult("execute", False, f"Agent error: {str(e)}")

    def close(self):
        """Close browser via MCP."""
        self.mcp.call_tool("browser_action", {"action": "close"})
