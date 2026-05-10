"""
Session Store — Save and resume operator sessions to/from disk.

Enables:
- Resuming incomplete goals after crashes
- Reviewing past execution history
- Building long-term analytics
"""

import json
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("antigravity.sessions")


class SessionStore:
    """
    Persist operator sessions to JSON files.
    
    Each session gets a unique file in the sessions directory.
    Sessions can be saved incrementally and resumed.
    """

    def __init__(self, sessions_dir: str):
        self._dir = Path(sessions_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        """Get the file path for a session."""
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return self._dir / f"{safe_id}.json"

    def save(self, session_id: str, session_data: dict):
        """
        Save a session to disk.
        
        Args:
            session_id: Unique session identifier
            session_data: Serializable dict of session state
        """
        path = self._session_path(session_id)
        try:
            session_data["_saved_at"] = time.time()
            session_data["_session_id"] = session_id
            with open(path, "w", encoding="utf-8") as f:
                json.dump(session_data, f, indent=2, default=str)
            logger.info(f"Session saved: {path}")
        except Exception as e:
            logger.error(f"Failed to save session {session_id}: {e}")

    def load(self, session_id: str) -> Optional[dict]:
        """
        Load a session from disk.
        
        Returns:
            Session dict or None if not found
        """
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """
        List recent sessions.
        
        Returns list of summary dicts sorted by recency.
        """
        sessions = []
        for path in sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if len(sessions) >= limit:
                break
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append({
                    "session_id": data.get("_session_id", path.stem),
                    "goal": data.get("goal", "unknown"),
                    "status": data.get("status", "unknown"),
                    "saved_at": data.get("_saved_at", 0),
                    "file": str(path),
                })
            except Exception:
                continue
        return sessions

    def delete(self, session_id: str) -> bool:
        """Delete a saved session."""
        path = self._session_path(session_id)
        if path.exists():
            path.unlink()
            logger.info(f"Session deleted: {session_id}")
            return True
        return False

    def serialize_session(self, session) -> dict:
        """
        Convert an OperatorSession dataclass to a serializable dict.
        
        Args:
            session: OperatorSession instance
        """
        completed = []
        for r in getattr(session, "completed", []):
            completed.append({
                "task": r.task,
                "task_type": r.task_type,
                "success": r.success,
                "output": r.output[:500],
                "error": r.error[:300],
                "attempts": r.attempts,
                "duration": r.duration,
            })

        failed = []
        for r in getattr(session, "failed", []):
            failed.append({
                "task": r.task,
                "task_type": r.task_type,
                "success": r.success,
                "output": r.output[:500],
                "error": r.error[:300],
                "attempts": r.attempts,
                "duration": r.duration,
            })

        return {
            "goal": session.goal,
            "plan": list(session.plan),
            "completed": completed,
            "failed": failed,
            "status": session.status,
            "start_time": session.start_time,
            "end_time": session.end_time,
            "total_steps": session.total_steps,
            "duration": session.duration,
        }
