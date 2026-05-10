"""
Terminal Tool — Safe command execution with validation, timeout, and output capture.

Architecture rule: LLM → structured action → validated tool → execution
Never let the LLM execute raw commands.

Security: Validates ALL commands in a chain (&&, ;, |, etc.)
"""

import subprocess
import re
import time
import logging
import platform
from pathlib import Path
from dataclasses import dataclass, field

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from configs.settings import (
    BLOCKED_COMMANDS,
    ALLOWED_COMMAND_PREFIXES,
    COMMAND_TIMEOUT,
    IS_WINDOWS,
    ERROR_CATEGORIES,
    USE_DOCKER_SANDBOX,
    PROJECT_ROOT,
)
from core.docker_manager import get_docker_manager

logger = logging.getLogger("antigravity.terminal")


@dataclass
class CommandResult:
    """Result of a terminal command execution."""
    command: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    error: str = ""
    error_category: str = ""

    def summary(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        lines = [
            f"{status} | exit={self.exit_code} | {self.duration:.1f}s",
            f"$ {self.command}",
        ]
        if self.stdout.strip():
            out = self.stdout.strip()
            if len(out) > 2000:
                out = out[:2000] + "\n... (truncated)"
            lines.append(f"STDOUT:\n{out}")
        if self.stderr.strip():
            err = self.stderr.strip()
            if len(err) > 1000:
                err = err[:1000] + "\n... (truncated)"
            lines.append(f"STDERR:\n{err}")
        if self.error:
            lines.append(f"ERROR: {self.error}")
        if self.error_category:
            lines.append(f"CATEGORY: {self.error_category}")
        return "\n".join(lines)


def classify_error(error_text: str) -> str:
    """
    Classify an error into a known category for smarter recovery.
    
    Returns category string or 'unknown'.
    """
    error_lower = error_text.lower()
    for category, patterns in ERROR_CATEGORIES.items():
        for pattern in patterns:
            if pattern.lower() in error_lower:
                return category
    return "unknown"


class TerminalTool:
    """
    Safe command execution tool.
    
    Validates commands against allowlists and blocklists before execution.
    Now validates ALL commands in chains (&&, ;, ||, |) — not just the first word.
    Captures output, enforces timeouts, and returns structured results.
    """

    # Patterns that split commands in both bash and PowerShell
    CHAIN_SEPARATORS = re.compile(r'\s*(?:&&|\|\||;|\|)\s*')
    # Dangerous subshell / substitution patterns
    INJECTION_PATTERNS = [
        r'\$\(',       # $(command)
        r'`[^`]+`',   # `command`
        r'\$\{',      # ${var}
        r'>\s*/dev/',  # > /dev/sda
        r'>>\s*/dev/', # >> /dev/sda
    ]

    def __init__(self, working_dir: str = "."):
        self.working_dir = Path(working_dir).resolve()
        if not self.working_dir.exists():
            self.working_dir.mkdir(parents=True, exist_ok=True)

    def _extract_all_commands(self, command: str) -> list[str]:
        """
        Extract ALL individual commands from a chained command string.
        Handles: &&, ||, ;, | operators.
        """
        # Split by chain operators
        parts = self.CHAIN_SEPARATORS.split(command)
        commands = [p.strip() for p in parts if p.strip()]
        return commands

    def validate_command(self, command: str) -> tuple[bool, str]:
        """
        Check if a command is safe to execute.
        Validates ALL commands in a chain, not just the first.
        Returns (is_valid, reason).
        """
        cmd_full = command.strip()

        # Check for injection patterns
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, cmd_full):
                return False, f"BLOCKED: Command contains dangerous pattern matching '{pattern}'"

        # Check blocklist against full command
        cmd_lower = cmd_full.lower()
        for blocked in BLOCKED_COMMANDS:
            if blocked.lower() in cmd_lower:
                return False, f"BLOCKED: Command contains forbidden pattern '{blocked}'"

        # Extract all individual commands from chains
        all_cmds = self._extract_all_commands(cmd_full)

        if not all_cmds:
            return False, "DENIED: Empty command"

        # Validate EACH command in the chain
        for i, sub_cmd in enumerate(all_cmds):
            first_word = sub_cmd.split()[0].lower() if sub_cmd.split() else ""
            
            # Handle path prefixes (e.g., "python3" -> "python3", "./script.py" -> excluded)
            base_cmd = Path(first_word).name.lower()
            
            allowed = any(
                base_cmd.startswith(prefix.lower())
                for prefix in ALLOWED_COMMAND_PREFIXES
            )

            if not allowed:
                return False, (
                    f"DENIED: Command #{i+1} '{first_word}' in chain not in allowed prefixes. "
                    f"Full chain: {cmd_full[:100]}... "
                    f"Allowed: {', '.join(ALLOWED_COMMAND_PREFIXES[:10])}..."
                )

        return True, "OK"

    def execute(self, command: str, cwd: str | None = None, timeout: int | None = None) -> CommandResult:
        """
        Execute a validated command and return structured results.
        
        Args:
            command: The shell command to execute
            cwd: Working directory (defaults to self.working_dir)
            timeout: Execution timeout in seconds (defaults to COMMAND_TIMEOUT)
            
        Returns:
            CommandResult with stdout, stderr, exit code, timing, and error classification
        """
        # Validate first
        is_valid, reason = self.validate_command(command)
        if not is_valid:
            logger.warning(f"Command rejected: {command} — {reason}")
            return CommandResult(
                command=command,
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration=0.0,
                error=reason,
                error_category="permission",
            )

        work_dir = Path(cwd) if cwd else self.working_dir
        if not work_dir.exists():
            work_dir.mkdir(parents=True, exist_ok=True)

        effective_timeout = timeout or COMMAND_TIMEOUT

        logger.info(f"Executing: {command} (cwd={work_dir}, timeout={effective_timeout}s)")
        start = time.time()

        try:
            if USE_DOCKER_SANDBOX:
                docker = get_docker_manager()
                # Inside Docker, we use linux paths, so we convert workspace-relative paths
                # If cwd is a full path on windows, we try to make it relative to the workspace
                docker_cwd = "/workspace"
                if cwd:
                    try:
                        # Attempt to resolve relative to workspace
                        rel_path = Path(cwd).relative_to(Path(PROJECT_ROOT) / "workspace")
                        docker_cwd = f"/workspace/{str(rel_path).replace('\\', '/')}"
                    except ValueError:
                        pass # Fallback to /workspace
                
                exit_code, stdout, stderr = docker.execute(command, cwd=docker_cwd)
                duration = time.time() - start
                
                # Mock result object to match subprocess
                class MockResult:
                    def __init__(self, rc, so, se):
                        self.returncode = rc
                        self.stdout = so
                        self.stderr = se
                result = MockResult(exit_code, stdout, stderr)
            else:
                # Use appropriate shell for the platform
                if IS_WINDOWS:
                    result = subprocess.run(
                        ["powershell", "-NoProfile", "-Command", command],
                        capture_output=True,
                        text=True,
                        cwd=str(work_dir),
                        timeout=effective_timeout,
                        encoding="utf-8",
                        errors="replace",
                    )
                else:
                    result = subprocess.run(
                        command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        cwd=str(work_dir),
                        timeout=effective_timeout,
                        encoding="utf-8",
                        errors="replace",
                    )
            duration = time.time() - start

            error_cat = ""
            error_msg = ""
            if result.returncode != 0:
                combined_err = f"{result.stderr}\n{result.stdout}"
                error_cat = classify_error(combined_err)
                error_msg = result.stderr[:500] if result.stderr else ""

            cmd_result = CommandResult(
                command=command,
                success=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration=duration,
                error=error_msg,
                error_category=error_cat,
            )
            logger.info(f"Command completed: exit={result.returncode}, {duration:.1f}s")
            return cmd_result

        except subprocess.TimeoutExpired:
            duration = time.time() - start
            logger.error(f"Command timed out after {effective_timeout}s: {command}")
            return CommandResult(
                command=command,
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration=duration,
                error=f"TIMEOUT: Command exceeded {effective_timeout}s limit",
                error_category="timeout",
            )
        except Exception as e:
            duration = time.time() - start
            logger.error(f"Command execution error: {e}")
            return CommandResult(
                command=command,
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration=duration,
                error=f"EXECUTION ERROR: {str(e)}",
                error_category=classify_error(str(e)),
            )


# ─── Quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from rich.console import Console
    console = Console()

    tool = TerminalTool()
    
    # Safe command
    console.print("\n[bold green]Testing safe command:[/]")
    result = tool.execute("python --version")
    console.print(result.summary())

    # Blocked command
    console.print("\n[bold red]Testing blocked command:[/]")
    result = tool.execute("rm -rf /")
    console.print(result.summary())

    # Chain bypass attempt (should be caught now)
    console.print("\n[bold red]Testing chain bypass:[/]")
    result = tool.execute("echo hello && rm -rf /")
    console.print(result.summary())

    # Injection attempt
    console.print("\n[bold red]Testing injection:[/]")
    result = tool.execute("echo $(whoami)")
    console.print(result.summary())

    # Denied command
    console.print("\n[bold yellow]Testing denied command:[/]")
    result = tool.execute("whoami")
    console.print(result.summary())
