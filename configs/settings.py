"""
Antigravity Operator — Central Configuration
All system-wide settings live here. No magic strings scattered across files.
Supports .env overrides for all values.
"""

import os
import platform
from pathlib import Path
from dotenv import load_dotenv

# ─── Load .env ───────────────────────────────────────────────────────────────
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)
SETTINGS_PATH = Path(__file__).resolve()

# ─── Project Paths ───────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
MEMORY_DIR = PROJECT_ROOT / "memory"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
SESSIONS_DIR = PROJECT_ROOT / "sessions"

# Ensure directories exist
LOGS_DIR.mkdir(exist_ok=True)
MEMORY_DIR.mkdir(exist_ok=True)
SESSIONS_DIR.mkdir(exist_ok=True)

# ─── Platform Detection ─────────────────────────────────────────────────────
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
IS_MAC = platform.system() == "Darwin"
SHELL_TYPE = "powershell" if IS_WINDOWS else "bash"

# ─── Ollama Models ───────────────────────────────────────────────────────────
CODER_MODEL = os.getenv("CODER_MODEL", "qwen2.5-coder:latest")
ROUTER_MODEL = os.getenv("ROUTER_MODEL", "llama3.2:latest")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Model fallback chain — if primary fails, try these in order
MODEL_FALLBACK_CHAIN = {
    CODER_MODEL: ["qwen2.5-coder:7b", "llama3.2:latest"],
    ROUTER_MODEL: ["llama3.2:3b", "qwen2.5-coder:latest"],
    EMBED_MODEL: ["nomic-embed-text:latest"],
}

# ─── Execution Limits ────────────────────────────────────────────────────────
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
COMMAND_TIMEOUT = int(os.getenv("COMMAND_TIMEOUT", "60"))
MAX_PLAN_STEPS = int(os.getenv("MAX_PLAN_STEPS", "15"))
AUTONOMOUS_LOOP_LIMIT = int(os.getenv("AUTONOMOUS_LOOP_LIMIT", "50"))

# ─── Sandbox Settings ───────────────────────────────────────────────────────
USE_DOCKER_SANDBOX = os.getenv("USE_DOCKER_SANDBOX", "true").lower() == "true"
DOCKER_IMAGE = "antigravity-sandbox"
DOCKER_CONTAINER = "antigravity-worker"

# ─── Token Budgets ───────────────────────────────────────────────────────────
# Approximate context window sizes (in tokens) for local models
MODEL_CONTEXT_WINDOWS = {
    "qwen2.5-coder:latest": 32768,
    "qwen2.5-coder:7b": 32768,
    "llama3.2:latest": 8192,
    "llama3.2:3b": 8192,
    "nomic-embed-text": 8192,
}
# Reserve this many tokens for the LLM output
OUTPUT_TOKEN_RESERVE = 4096

# ─── Safety ──────────────────────────────────────────────────────────────────
# Commands that are ALWAYS blocked (checked against full command string)
BLOCKED_COMMANDS = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf .",
    "format c:",
    "format d:",
    "del /s /q C:",
    "del /s /q c:",
    "shutdown",
    "restart",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "Remove-Item -Recurse -Force C:",
    "> /dev/sda",
    "chmod -R 777 /",
    ":(){ :|:& };:",
]

# Only these command prefixes are allowed to execute
ALLOWED_COMMAND_PREFIXES = [
    "python", "python3", "py",
    "pip", "pip3",
    "npm", "npx", "yarn", "pnpm",
    "node",
    "git",
    "mkdir",
    "echo",
    "cat", "type", "more",
    "dir", "ls",
    "cd",
    "curl", "wget",
    "flask", "uvicorn", "gunicorn", "django-admin",
    "pytest", "unittest",
    "playwright",
    "ollama",
    "cargo", "rustc",
    "go",
    "javac", "java",
    "dotnet",
    "docker", "docker-compose",
    "make", "cmake",
    "tar", "unzip", "zip",
    "touch", "cp", "copy", "move", "mv",
    "find", "grep", "head", "tail", "wc",
    "sed", "awk", "cut", "sort", "uniq", "diff",
    "set", "export",
    "powershell",
    "cmd",
    "where", "which",
]

# ─── ChromaDB ────────────────────────────────────────────────────────────────
CHROMA_COLLECTION_NAME = "operator_memory"
CHROMA_PERSIST_DIR = str(MEMORY_DIR / "chromadb")

# ─── API ─────────────────────────────────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE = LOGS_DIR / "operator.log"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ─── Error Categories ────────────────────────────────────────────────────────
ERROR_CATEGORIES = {
    "network": ["ConnectionError", "TimeoutError", "ConnectionRefused", "ECONNREFUSED", "getaddrinfo"],
    "syntax": ["SyntaxError", "IndentationError", "TabError", "invalid syntax"],
    "import": ["ModuleNotFoundError", "ImportError", "No module named"],
    "permission": ["PermissionError", "Access is denied", "EACCES", "Permission denied"],
    "file": ["FileNotFoundError", "No such file or directory", "ENOENT"],
    "dependency": ["pip install", "npm install", "ModuleNotFoundError", "Cannot find module"],
    "memory": ["MemoryError", "OutOfMemoryError", "killed"],
    "timeout": ["TimeoutError", "timed out", "TIMEOUT"],
}
