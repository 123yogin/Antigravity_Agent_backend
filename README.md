# Antigravity Operator

A **Local Autonomous AI Operator** that understands goals, breaks them into tasks, and executes them autonomously.

## What This Is

Not a chatbot. An **execution engine**.

```
PLAN → EXECUTE → CHECK → DEBUG → RETRY → STORE MEMORY
```

## Capabilities

- 🎯 Understand user goals
- 📋 Break goals into executable tasks
- 💻 Execute terminal commands safely
- 📁 Create and edit files
- 🌐 Control browsers via Playwright
- 🔧 Debug errors automatically
- 🔄 Retry failures with recovery plans
- 🧠 Maintain persistent memory
- 📊 Track project state

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Ensure Ollama Models Are Available

```bash
ollama pull qwen2.5-coder:7b
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### 3. Run the Operator (CLI)

```bash
python main.py
```

Then enter a goal:

```
🎯 Goal: Create a FastAPI server with JWT authentication
```

The operator will plan, execute, debug, and complete the task autonomously.

### 4. Run the API Server

```bash
python api/server.py
```

Then submit goals via HTTP:

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"goal": "Create a TODO API with Flask"}'
```

## Architecture

```
antigravity-operator/
├── agents/
│   ├── planner.py      # Goal → task breakdown
│   ├── terminal.py     # Command execution with retry
│   ├── file_agent.py   # File create/edit via LLM
│   └── memory.py       # ChromaDB-backed persistent memory
├── tools/
│   ├── terminal_tool.py # Safe command execution
│   ├── file_tool.py     # Safe file operations
│   └── browser_tool.py  # Playwright browser control
├── prompts/             # System prompts for each agent
├── configs/settings.py  # Central configuration
├── api/server.py        # FastAPI HTTP interface
└── main.py              # Core orchestrator
```

## Models

| Model | Purpose |
|-------|---------|
| qwen2.5-coder:7b | Code generation, planning, tool calls |
| llama3.2:3b | Fast routing, simple decisions |
| nomic-embed-text | Memory embeddings |

## Safety

- All commands go through validated tool schemas
- Command allowlist prevents dangerous operations
- File paths are validated to prevent traversal
- Max retry limits prevent infinite loops
- Execution timeouts prevent hanging

## License

MIT
