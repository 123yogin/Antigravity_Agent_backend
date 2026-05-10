import sys
import os
from pathlib import Path

# Add project root to sys.path so 'tools' module can be found
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP
from tools.terminal_tool import TerminalTool
from tools.file_tool import FileTool
from tools.browser_tool import BrowserTool
import logging

# Configure logging to stderr to avoid corrupting stdio transport
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("antigravity.mcp_server")

from configs.settings import USE_DOCKER_SANDBOX, PROJECT_ROOT
from core.docker_manager import get_docker_manager

if USE_DOCKER_SANDBOX:
    logger.info("Docker Sandbox enabled. Initializing...")
    docker = get_docker_manager()
    # Build image and start container with workspace mounted
    if docker.build_image():
        docker.start_container(workspace_path=PROJECT_ROOT / "workspace")

mcp = FastMCP("Antigravity Operator Tools")

# Initialize underlying tools with the correct workspace path
terminal = TerminalTool(working_dir=str(PROJECT_ROOT / "workspace"))
file_tool = FileTool(base_dir=str(PROJECT_ROOT / "workspace"))
browser = BrowserTool()

@mcp.tool()
def run_terminal_command(command: str, cwd: str = ".") -> str:
    """Execute a shell command in the terminal and return stdout/stderr."""
    logger.info(f"MCP Terminal: {command} in {cwd}")
    result = terminal.execute(command, cwd=cwd)
    if result.success:
        return result.stdout or "Command executed successfully (no output)."
    else:
        return f"ERROR [exit {result.exit_code}]: {result.error or result.stderr}"

@mcp.tool()
def read_file(path: str) -> str:
    """Read the contents of a file from disk."""
    logger.info(f"MCP File: read {path}")
    res = file_tool.read(path)
    return res.content if res.success else f"ERROR: {res.message}"

@mcp.tool()
def write_file(path: str, content: str = "", action: str = "create") -> str:
    """Create, edit, delete, or append to a file on disk."""
    logger.info(f"MCP File: {action} {path}")
    if action == "create":
        res = file_tool.create(path, content)
    elif action in ["edit", "update"]:
        res = file_tool.edit(path, content)
    elif action == "append":
        res = file_tool.append(path, content)
    elif action == "delete":
        res = file_tool.delete(path)
    elif action == "read":
        res = file_tool.read(path)
        return res.content if res.success else f"ERROR: {res.message}"
    else:
        return f"ERROR: Unknown action {action}"
    
    return res.message if res.success else f"ERROR: {res.message}"

@mcp.tool()
def browser_action(action: str, url: str = None, selector: str = None, value: str = None) -> str:
    """Perform web browser actions: navigate, click, fill, or get_text."""
    logger.info(f"MCP Browser: {action} {url or selector or ''}")
    res = browser.execute(action, url=url, selector=selector, value=value)
    if res.success:
        return res.data or res.message
    else:
        return f"ERROR: {res.message}"

if __name__ == "__main__":
    mcp.run()
