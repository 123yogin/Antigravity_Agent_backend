import asyncio
import sys
import os
import logging
import threading
from typing import Any, Optional, Dict
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack

logger = logging.getLogger("antigravity.mcp_client")

class AntigravityMCPClient:
    """
    Thread-safe synchronous bridge for the Antigravity MCP Server.
    Runs an asyncio loop in a background thread to maintain task consistency.
    """
    
    def __init__(self, server_path: str = None):
        if server_path is None:
            # Default to the server.py in the same directory
            server_path = os.path.join(os.path.dirname(__file__), "server.py")
        
        self.server_params = StdioServerParameters(
            command=sys.executable,
            args=[server_path],
            env=os.environ.copy()
        )
        self.session: Optional[ClientSession] = None
        self._exit_stack = AsyncExitStack()
        
        # Start background event loop thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

    def _run_event_loop(self):
        """Thread target: run the asyncio loop forever."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_sync(self, coro):
        """Helper to run a coroutine on the background loop and wait for result."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    async def _async_connect(self):
        """Internal async connection logic."""
        logger.info("Connecting to Antigravity MCP Server...")
        read, write = await self._exit_stack.enter_async_context(stdio_client(self.server_params))
        self.session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        logger.info("MCP Session initialized.")

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Synchronous wrapper to call an MCP tool.
        """
        if not self.session:
            self._run_sync(self._async_connect())
            
        async def _call():
            result = await self.session.call_tool(tool_name, arguments)
            if hasattr(result, 'content') and len(result.content) > 0:
                return result.content[0].text
            return str(result)
            
        try:
            return self._run_sync(_call())
        except Exception as e:
            logger.error(f"MCP Tool Call Failed ({tool_name}): {e}")
            return f"ERROR: MCP Tool call failed: {str(e)}"

    def close(self):
        """Gracefully close the MCP session and stop the background thread."""
        logger.info("Closing MCP Client...")
        if self._exit_stack:
            try:
                self._run_sync(self._exit_stack.aclose())
            except Exception as e:
                logger.debug(f"Error during exit stack closure: {e}")
        
        # Stop the loop and join thread
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("MCP Client bridge shutdown complete.")

# Singleton instance for the operator
_client_instance = None

def get_mcp_client() -> AntigravityMCPClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = AntigravityMCPClient()
    return _client_instance
