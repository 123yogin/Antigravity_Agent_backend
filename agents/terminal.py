"""
Terminal Agent — Receives task descriptions, generates commands, and executes them safely.

Uses Ollama's native tool-calling API for structured command output.
Includes error classification for smarter retry strategies.
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
    USE_DOCKER_SANDBOX,
)
from tools.terminal_tool import CommandResult
from utils.token_counter import TokenCounter
from utils.metrics import MetricsTracker
from mcp_bridge.client import get_mcp_client

logger = logging.getLogger("antigravity.terminal_agent")

EXECUTE_COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": "Execute a terminal/shell command.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The exact shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory (use '.' for current)"},
            },
            "required": ["command"]
        }
    }
}


class TerminalAgent:
    """Task Description -> Command Execution agent with tool-calling and retry."""

    def __init__(self, working_dir=".", model=None, metrics=None):
        self.model = model or CODER_MODEL
        self.working_dir = working_dir
        self.mcp = get_mcp_client()
        self._system_prompt = self._load_prompt()
        self._token_counter = TokenCounter(MODEL_CONTEXT_WINDOWS, OUTPUT_TOKEN_RESERVE)
        self._metrics = metrics

    def _load_prompt(self):
        prompt_file = PROMPTS_DIR / "terminal.txt"
        if prompt_file.exists():
            content = prompt_file.read_text(encoding="utf-8")
            os_info = "Linux (Bash)" if USE_DOCKER_SANDBOX else "Windows (PowerShell)"
            return content.replace("{{OPERATING_SYSTEM}}", os_info)
        return "You are a terminal agent. Given a task, produce the exact command to execute."

    def _call_llm(self, messages):
        models_to_try = [self.model] + MODEL_FALLBACK_CHAIN.get(self.model, [])
        for model in models_to_try:
            try:
                start = time.time()
                response = ollama.chat(
                    model=model, messages=messages,
                    tools=[EXECUTE_COMMAND_TOOL],
                    options={"temperature": 0.1, "num_predict": 512},
                )
                duration = time.time() - start
                if self._metrics:
                    self._metrics.record_llm_call(model=model, agent="terminal",
                        tokens_in=self._token_counter.count_messages_tokens(messages),
                        tokens_out=self._token_counter.count_tokens(response.get("message",{}).get("content","")),
                        duration=duration, success=True)
                return response
            except Exception as e:
                logger.warning(f"Model {model} failed: {e}")
                continue
        raise RuntimeError(f"All models failed: {models_to_try}")

    def _generate_command(self, task, error_context="", state=None):
        messages = [{"role": "system", "content": self._system_prompt}]
        
        user_msg = ""
        if state and state.completed:
            recent_tasks = "\n".join([f"- {r.task}: {r.output[:200]}" for r in state.completed[-3:]])
            user_msg += f"RECENT EXECUTION CONTEXT:\n{recent_tasks}\n\n"
            
        if error_context:
            user_msg += f"PREVIOUS ATTEMPT FAILED:\n{error_context}\n\nTASK (retry with fix): {task}"
        else:
            user_msg += f"TASK: {task}"
            
        messages.append({"role": "user", "content": user_msg})
        messages = self._token_counter.fit_messages_to_context(messages, self.model)
        try:
            response = self._call_llm(messages)
            msg = response.get("message", {})
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    if fn.get("name") == "execute_command":
                        args = fn.get("arguments", {})
                        return {"command": args.get("command", ""), "cwd": args.get("cwd", ".")}
            raw = msg.get("content", "").strip()
            if raw:
                return self._parse_command(raw)
            return {"command": "", "cwd": ".", "error": "Empty LLM response"}
        except Exception as e:
            return {"command": "", "cwd": ".", "error": str(e)}

    def _parse_command(self, raw):
        if "```" in raw:
            for part in raw.split("```"):
                cleaned = part.strip()
                if cleaned.startswith("json"): cleaned = cleaned[4:].strip()
                if cleaned.startswith("{"):
                    try: return json.loads(cleaned)
                    except json.JSONDecodeError: continue
        try:
            start = raw.index("{"); end = raw.rindex("}") + 1
            return json.loads(raw[start:end])
        except (ValueError, json.JSONDecodeError): pass
        # Check for python-style function call hallucination
        if raw.startswith("execute_command(") or raw.startswith("```python\nexecute_command"):
            import re
            match = re.search(r'command\s*=\s*[\'"]([^\'"]+)[\'"]', raw)
            if match:
                return {"command": match.group(1), "cwd": "."}

        return {"command": raw.split("\n")[0].strip(), "cwd": "."}

    def execute_task(self, task, project_dir=None, state=None):
        """Execute a terminal task with automatic retry on failure."""
        logger.info(f"Terminal task: {task}")
        error_context = ""
        last_result = None
        for attempt in range(1, MAX_RETRIES + 1):
            cmd_spec = self._generate_command(task, error_context, state)
            if cmd_spec.get("error"):
                logger.warning(f"Attempt {attempt}: Generation error — {cmd_spec['error']}")
                error_context = f"Generation error: {cmd_spec['error']}"
                continue
                
            if "arguments" in cmd_spec and isinstance(cmd_spec["arguments"], dict):
                cmd_spec = cmd_spec["arguments"]

            command = cmd_spec.get("command", "").strip()
            cwd = project_dir or cmd_spec.get("cwd", ".")
            if not command:
                logger.warning(f"Attempt {attempt}: Empty command was generated. Raw LLM output: {cmd_spec}")
                error_context = "Empty command was generated. Try a different approach."
                continue
            logger.info(f"Attempt {attempt}: $ {command} (cwd={cwd})")
            
            output = self.mcp.call_tool("run_terminal_command", {"command": command, "cwd": cwd})
            success = not output.startswith("ERROR")
            
            # Reconstruct result object for downstream metrics/logic
            result = CommandResult(
                command=command, 
                success=success, 
                stdout=output if success else "", 
                stderr=output if not success else "", 
                exit_code=0 if success else 1, 
                duration=0.0
            )
            
            last_result = result
            if self._metrics: self._metrics.record_task_result("terminal", result.success)
            if result.success:
                logger.info(f"Task completed successfully on attempt {attempt}")
                return result
            error_context = f"Command: {result.command}\nOutput: {output}"
            logger.warning(f"Attempt {attempt} failed: {output[:200]}")
        if last_result is None:
            return CommandResult(command=f"[failed: {task}]", success=False, exit_code=-1, stdout="", stderr="", duration=0.0, error=f"All {MAX_RETRIES} attempts failed", error_category="unknown")
        return last_result
