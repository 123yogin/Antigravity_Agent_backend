"""
File Agent — Receives task descriptions, generates file content via LLM, and writes files safely.

Uses Ollama's native tool-calling API for structured file spec output.
"""

import json
import logging
import time
from pathlib import Path
import ollama
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from configs.settings import (
    CODER_MODEL, PROMPTS_DIR,
    MODEL_CONTEXT_WINDOWS, OUTPUT_TOKEN_RESERVE, MODEL_FALLBACK_CHAIN,
)
from tools.file_tool import FileResult
from utils.token_counter import TokenCounter
from utils.metrics import MetricsTracker
from mcp_bridge.client import get_mcp_client

logger = logging.getLogger("antigravity.file_agent")

CREATE_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Create or edit a file with the given content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path to create/edit"},
                "content": {"type": "string", "description": "Complete file content to write"},
                "action": {"type": "string", "enum": ["create", "edit", "append"], "description": "File operation type"},
            },
            "required": ["path", "content", "action"]
        }
    }
}


class FileAgent:
    """Task Description -> File Operation agent with tool-calling."""

    def __init__(self, base_dir=".", model=None, metrics=None):
        self.model = model or CODER_MODEL
        self.mcp = get_mcp_client()
        self._system_prompt = self._load_prompt()
        self._token_counter = TokenCounter(MODEL_CONTEXT_WINDOWS, OUTPUT_TOKEN_RESERVE)
        self._metrics = metrics

    def _load_prompt(self):
        prompt_file = PROMPTS_DIR / "file_agent.txt"
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return "You are a file agent. Given a task, produce the file content to create or edit. If no filename is provided, invent a reasonable one."

    def _call_llm(self, messages):
        models_to_try = [self.model] + MODEL_FALLBACK_CHAIN.get(self.model, [])
        for model in models_to_try:
            try:
                start = time.time()
                response = ollama.chat(
                    model=model, messages=messages,
                    tools=[CREATE_FILE_TOOL],
                    options={"temperature": 0.2, "num_predict": 4096},
                )
                duration = time.time() - start
                if self._metrics:
                    self._metrics.record_llm_call(model=model, agent="file_agent",
                        tokens_in=self._token_counter.count_messages_tokens(messages),
                        tokens_out=self._token_counter.count_tokens(response.get("message",{}).get("content","")),
                        duration=duration, success=True)
                return response
            except Exception as e:
                logger.warning(f"Model {model} failed: {e}")
                continue
        raise RuntimeError(f"All models failed: {models_to_try}")

    def _generate_file_spec(self, task, existing_content="", state=None):
        messages = [{"role": "system", "content": self._system_prompt}]
        user_msg = f"TASK: {task}"
        if state and state.completed:
            recent_tasks = "\n".join([f"- {r.task}: {r.output[:200]}" for r in state.completed[-3:]])
            user_msg += f"\n\nRECENT EXECUTION CONTEXT:\n{recent_tasks}"
        if existing_content:
            user_msg += f"\n\nEXISTING FILE CONTENT:\n```\n{existing_content[:3000]}\n```"
        messages.append({"role": "user", "content": user_msg})
        messages = self._token_counter.fit_messages_to_context(messages, self.model)
        try:
            response = self._call_llm(messages)
            msg = response.get("message", {})
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    if fn.get("name") == "write_file":
                        args = fn.get("arguments", {})
                        return args
            raw = msg.get("content", "").strip()
            if raw:
                return self._parse_file_spec(raw)
            return {"error": "Empty LLM response"}
        except Exception as e:
            return {"error": str(e)}

    def _parse_file_spec(self, raw):
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
        return {"error": f"Unparseable output: {raw[:200]}"}

    def execute_task(self, task, state=None):
        """Execute a file operation task."""
        logger.info(f"File task: {task}")
        existing_content = ""
        if any(w in task.lower() for w in ["edit", "update", "modify", "refactor", "fix"]):
            words = task.split()
            for word in words:
                if "." in word and ("/" in word or "\\" in word):
                    # We still use the tool directly for reading context if needed
                    from tools.file_tool import FileTool
                    temp_tool = FileTool()
                    read_result = temp_tool.read(word.strip("'\""))
                    if read_result.success:
                        existing_content = read_result.content
                    break
        spec = self._generate_file_spec(task, existing_content, state)
        if "error" in spec:
            return FileResult("", "generate", False, f"Generation failed: {spec['error']}")
        if "arguments" in spec and isinstance(spec["arguments"], dict):
            spec = spec["arguments"]

        path = spec.get("path", "")
        content = spec.get("content", "")
        action = spec.get("action", "create")
        
        if not path:
            logger.warning(f"Malformed LLM output: {spec}")
            return FileResult("", action, False, f"No file path specified by LLM. The LLM output: {spec}")
        
        # Validation
        if content is None and action not in ["delete", "read"]:
            return FileResult(path, action, False, "No content generated by LLM (content is None)")
            
        logger.info(f"File {action}: {path}")
        if self._metrics: self._metrics.record_task_result("file", True)
        
        # Route to correct tool
        if action == "read":
            output = self.mcp.call_tool("read_file", {"path": path})
        else:
            output = self.mcp.call_tool("write_file", {"path": path, "content": content, "action": action})
            
        success = not output.startswith("ERROR")
        return FileResult(path, action, success, output)

    def create_file(self, path, content):
        """Direct file creation via MCP."""
        output = self.mcp.call_tool("write_file", {"path": path, "content": content, "action": "create"})
        return output

    def read_file(self, path):
        """Direct file read (currently via direct tool for speed)."""
        from tools.file_tool import FileTool
        return FileTool().read(path)
