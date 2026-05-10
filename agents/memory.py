"""
Memory Agent — Persistent memory using ChromaDB for embeddings.

Stores actions, results, errors, and fixes so the operator can:
- Learn from past mistakes
- Avoid repeating failures
- Recall successful workflows
- Build context across sessions
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from configs.settings import (
    EMBED_MODEL,
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
)

logger = logging.getLogger("antigravity.memory")


class MemoryAgent:
    """
    Persistent memory agent backed by ChromaDB.
    
    Stores documents with embeddings for semantic retrieval.
    Each memory entry has: content, metadata, timestamp.
    """

    def __init__(self):
        self._client = None
        self._collection = None
        self._embed_model = EMBED_MODEL
        self._initialized = False

    def _ensure_initialized(self):
        """Lazily initialize ChromaDB on first use."""
        if self._initialized:
            return

        try:
            import chromadb
            from chromadb.config import Settings

            persist_dir = Path(CHROMA_PERSIST_DIR)
            persist_dir.mkdir(parents=True, exist_ok=True)

            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=Settings(anonymized_telemetry=False),
            )

            self._collection = self._client.get_or_create_collection(
                name=CHROMA_COLLECTION_NAME,
                metadata={"description": "Antigravity Operator memory store"},
            )

            self._initialized = True
            count = self._collection.count()
            logger.info(f"Memory initialized: {count} existing entries in '{CHROMA_COLLECTION_NAME}'")

        except ImportError:
            logger.error("ChromaDB not installed. Run: pip install chromadb")
            raise
        except Exception as e:
            logger.error(f"Memory initialization failed: {e}")
            raise

    def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding using Ollama's embedding model."""
        try:
            import ollama
            response = ollama.embed(model=self._embed_model, input=text)
            return response["embeddings"][0]
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            # Return None to let ChromaDB use its default embedding
            return None

    def store(
        self,
        content: str,
        category: str = "action",
        metadata: dict = None,
    ) -> str:
        """
        Store a memory entry.
        
        Args:
            content: The text content to remember
            category: Type of memory (action, error, fix, workflow, context)
            metadata: Additional key-value metadata
            
        Returns:
            The ID of the stored memory
        """
        self._ensure_initialized()

        entry_id = f"{category}_{int(time.time() * 1000)}"
        
        meta = {
            "category": category,
            "timestamp": time.time(),
            "time_human": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if metadata:
            meta.update({k: str(v) for k, v in metadata.items()})

        try:
            embedding = self._get_embedding(content)
            
            kwargs = {
                "documents": [content],
                "metadatas": [meta],
                "ids": [entry_id],
            }
            if embedding:
                kwargs["embeddings"] = [embedding]

            self._collection.add(**kwargs)
            logger.info(f"Stored memory [{category}]: {content[:80]}...")
            return entry_id

        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            return ""

    def recall(
        self,
        query: str,
        n_results: int = 5,
        category: str = None,
    ) -> list[dict]:
        """
        Recall memories relevant to a query.
        
        Args:
            query: The search query
            n_results: Max number of results to return
            category: Optional filter by category
            
        Returns:
            List of dicts with 'content', 'metadata', 'distance' keys
        """
        self._ensure_initialized()

        if self._collection.count() == 0:
            return []

        try:
            embedding = self._get_embedding(query)
            
            where_filter = {"category": category} if category else None
            
            kwargs = {
                "n_results": min(n_results, self._collection.count()),
            }
            if embedding:
                kwargs["query_embeddings"] = [embedding]
            else:
                kwargs["query_texts"] = [query]
            
            if where_filter:
                kwargs["where"] = where_filter

            results = self._collection.query(**kwargs)

            memories = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    memories.append({
                        "content": doc,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if results["distances"] else 0,
                    })

            logger.info(f"Recalled {len(memories)} memories for: {query[:60]}...")
            return memories

        except Exception as e:
            logger.error(f"Memory recall failed: {e}")
            return []

    def store_action(self, task: str, result: str, success: bool):
        """Convenience: store an action and its result."""
        content = f"TASK: {task}\nRESULT: {result}\nSUCCESS: {success}"
        self.store(content, category="action", metadata={"success": str(success)})

    def store_error(self, task: str, error: str, fix: str = ""):
        """Convenience: store an error and optional fix."""
        content = f"TASK: {task}\nERROR: {error}"
        if fix:
            content += f"\nFIX: {fix}"
        self.store(content, category="error", metadata={"has_fix": str(bool(fix))})

    def store_workflow(self, goal: str, steps: list[str], success: bool):
        """Convenience: store a complete workflow."""
        content = f"GOAL: {goal}\nSTEPS:\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
        self.store(content, category="workflow", metadata={"success": str(success), "steps": str(len(steps))})

    def get_relevant_context(self, goal: str) -> str:
        """Get relevant past memories formatted as context string."""
        memories = self.recall(goal, n_results=3)
        if not memories:
            return ""
        
        context_parts = ["RELEVANT PAST EXPERIENCE:"]
        for m in memories:
            context_parts.append(f"- {m['content'][:200]}")
        return "\n".join(context_parts)

    def stats(self) -> dict:
        """Get memory statistics."""
        self._ensure_initialized()
        return {
            "total_entries": self._collection.count(),
            "collection": CHROMA_COLLECTION_NAME,
            "persist_dir": CHROMA_PERSIST_DIR,
        }


# ─── Quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel
    console = Console()

    agent = MemoryAgent()
    
    console.print(Panel("[bold]Memory Agent Test[/]"))
    
    # Store some memories
    agent.store_action("install flask", "Successfully installed Flask-3.0.0", True)
    agent.store_error("run server", "ModuleNotFoundError: No module named 'flask'", "pip install flask")
    agent.store_workflow("Create REST API", ["install flask", "create app.py", "run server"], True)
    
    # Recall
    console.print("\n[bold cyan]Recalling memories about 'flask':[/]")
    memories = agent.recall("flask installation")
    for m in memories:
        console.print(f"  [{m['metadata'].get('category', '?')}] {m['content'][:100]}...")

    # Stats
    console.print(f"\n[bold]Stats:[/] {agent.stats()}")
