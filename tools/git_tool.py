"""
Git Tool — Safe git operations for version control integration.

Enables:
- Auto-committing after successful executions
- Branch creation for experimental changes
- Status checks and diff viewing
"""

import logging
from pathlib import Path
from tools.terminal_tool import TerminalTool, CommandResult

logger = logging.getLogger("antigravity.git_tool")


class GitTool:
    """
    Safe git operations tool.
    
    Wraps common git commands through the TerminalTool for safety validation.
    """

    def __init__(self, working_dir: str = "."):
        self.working_dir = Path(working_dir).resolve()
        self._terminal = TerminalTool(str(self.working_dir))

    def _run(self, command: str) -> CommandResult:
        """Execute a git command through the terminal tool."""
        return self._terminal.execute(command, cwd=str(self.working_dir))

    def is_repo(self) -> bool:
        """Check if the working directory is a git repository."""
        result = self._run("git rev-parse --is-inside-work-tree")
        return result.success and "true" in result.stdout.lower()

    def init(self) -> CommandResult:
        """Initialize a new git repository."""
        return self._run("git init")

    def status(self) -> CommandResult:
        """Get git status."""
        return self._run("git status --porcelain")

    def add_all(self) -> CommandResult:
        """Stage all changes."""
        return self._run("git add -A")

    def commit(self, message: str) -> CommandResult:
        """Create a commit with the given message."""
        # Sanitize message to prevent injection
        safe_msg = message.replace('"', "'").replace("$", "").replace("`", "")[:200]
        return self._run(f'git commit -m "{safe_msg}"')

    def create_branch(self, branch_name: str) -> CommandResult:
        """Create and switch to a new branch."""
        safe_name = "".join(c if c.isalnum() or c in "-_/" else "-" for c in branch_name)
        return self._run(f"git checkout -b {safe_name}")

    def diff(self, staged: bool = False) -> CommandResult:
        """Show diff of changes."""
        cmd = "git diff --staged" if staged else "git diff"
        return self._run(cmd)

    def log(self, n: int = 5) -> CommandResult:
        """Show recent commit log."""
        return self._run(f"git log --oneline -n {n}")

    def auto_commit(self, goal: str, status: str = "completed") -> CommandResult:
        """
        Auto-commit all changes with a descriptive message.
        
        Args:
            goal: The goal that was executed
            status: Execution status (completed, partial, etc.)
        """
        # Check if there's a repo
        if not self.is_repo():
            init_result = self.init()
            if not init_result.success:
                return init_result

        # Stage all
        add_result = self.add_all()
        if not add_result.success:
            return add_result

        # Check if there's anything to commit
        status_result = self.status()
        if status_result.success and not status_result.stdout.strip():
            return CommandResult(
                command="git commit",
                success=True,
                exit_code=0,
                stdout="Nothing to commit",
                stderr="",
                duration=0.0,
            )

        # Commit
        msg = f"[antigravity] {status}: {goal[:100]}"
        return self.commit(msg)


# ─── Quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from rich.console import Console
    console = Console()

    tool = GitTool(".")
    console.print(f"Is repo: {tool.is_repo()}")
    result = tool.status()
    console.print(result.summary())
