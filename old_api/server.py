"""
FastAPI Server — HTTP interface for the Antigravity Operator.

Provides a REST API to submit goals, check status, query memory,
and view session history.
"""

import sys
import time
import logging
from pathlib import Path
from threading import Thread
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from configs.settings import API_HOST, API_PORT, PROJECT_ROOT
from utils.session_store import SessionStore

logger = logging.getLogger("antigravity.api")

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Antigravity Operator API",
    description="Local Autonomous AI Operator — submit goals, track execution, query memory.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── State ────────────────────────────────────────────────────────────────────
_operator = None
_session_store = SessionStore(str(PROJECT_ROOT / "sessions"))


def _get_operator():
    global _operator
    if _operator is None:
        from main import AntigravityOperator
        _operator = AntigravityOperator()
    return _operator


# ─── Request/Response Models ─────────────────────────────────────────────────

class GoalRequest(BaseModel):
    goal: str
    project_dir: Optional[str] = None


class GoalResponse(BaseModel):
    session_id: str
    status: str
    message: str


class MemoryQuery(BaseModel):
    query: str
    n_results: int = 5
    category: Optional[str] = None


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": "Antigravity Operator",
        "version": "0.2.0",
        "status": "running",
        "endpoints": [
            "/health", "/run", "/sessions", "/sessions/{id}",
            "/memory/query", "/memory/stats", "/metrics"
        ],
    }


@app.get("/health")
async def health():
    operator = _get_operator()
    # Lightweight check without full LLM validation
    return {"status": "online", "timestamp": time.time()}


@app.post("/run", response_model=GoalResponse)
async def run_goal(request: GoalRequest, background_tasks: BackgroundTasks):
    """Submit a goal for autonomous execution."""
    operator = _get_operator()
    
    # Pre-flight health check
    if not operator.check_health():
        raise HTTPException(status_code=503, detail="System health check failed. Check Ollama and required models.")
        
    session_id = f"sess_{int(time.time())}"

    # Run in background
    def _execute():
        # Initialize a basic session record immediately
        _session_store.save(session_id, {
            "goal": request.goal,
            "status": "starting",
            "start_time": time.time()
        })
        # The operator will take over saving the session using the same ID logic
        operator.run(request.goal)

    background_tasks.add_task(_execute)

    return GoalResponse(
        session_id=session_id,
        status="started",
        message=f"Goal submitted: {request.goal}",
    )


@app.get("/sessions")
async def list_sessions(limit: int = 20):
    """Get recent sessions."""
    return {"sessions": _session_store.list_sessions(limit=limit)}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get full details of a specific session."""
    session = _session_store.load(session_id)
    if not session:
        # Fallback for sessions that might be actively spinning up
        # We don't have the active memory dict anymore, so we rely purely on the store.
        raise HTTPException(status_code=404, detail="Session not found or not yet saved")
    return session


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a saved session."""
    success = _session_store.delete(session_id)
    if success:
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Session not found")


@app.post("/memory/query")
async def query_memory(request: MemoryQuery):
    """Query the operator's memory."""
    operator = _get_operator()
    try:
        memories = operator.memory.recall(
            request.query,
            n_results=request.n_results,
            category=request.category,
        )
        return {"results": memories, "count": len(memories)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/memory/stats")
async def memory_stats():
    """Get memory statistics."""
    operator = _get_operator()
    try:
        return operator.memory.stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
async def get_metrics():
    """Get real-time operational metrics for the current engine instance."""
    operator = _get_operator()
    if operator and hasattr(operator, "metrics"):
        return operator.metrics.get_summary()
    return {"status": "No metrics available"}


# ─── Run ──────────────────────────────────────────────────────────────────────

def start_server():
    """Start the API server."""
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")


if __name__ == "__main__":
    start_server()
