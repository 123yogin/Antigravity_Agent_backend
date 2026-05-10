"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                        ANTIGRAVITY OPERATOR                                  ║
║                   Local Autonomous AI Operator                               ║
║                                                                              ║
║   PLAN → EXECUTE → CHECK → DEBUG → RETRY → STORE MEMORY                     ║
╚═══════════════════════════════════════════════════════════════════════════════╝

This is the CORE ENGINE. Not a chatbot. An operator.
"""

import json
import time
import logging
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Fix Windows Unicode encoding issues
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.logging import RichHandler
from rich.markdown import Markdown
from rich import box

# ─── Setup paths ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from configs.settings import (
    MAX_RETRIES,
    AUTONOMOUS_LOOP_LIMIT,
    LOG_FILE,
    LOG_LEVEL,
    LOGS_DIR,
    CODER_MODEL,
    ROUTER_MODEL,
)

from agents.planner import PlannerAgent
from agents.terminal import TerminalAgent
from agents.file_agent import FileAgent
from agents.memory import MemoryAgent
from agents.router import RouterAgent
from agents.browser_agent import BrowserAgent
from tools.project_scanner import ProjectScanner
from utils.health_check import full_health_check
from utils.metrics import MetricsTracker
from utils.session_store import SessionStore
from mcp_bridge.client import get_mcp_client

# ─── Logging ─────────────────────────────────────────────────────────────────
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(rich_tracebacks=True, markup=True),
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
    ],
)
logger = logging.getLogger("antigravity")
console = Console()


# ─── Data Structures ─────────────────────────────────────────────────────────

from core.state import OperatorState, TaskResult



# ─── The Operator ─────────────────────────────────────────────────────────────

class AntigravityOperator:
    """The autonomous operator engine."""

    def __init__(self, project_dir: str = None, on_metadata=None):
        self.project_dir = Path(project_dir).resolve() if project_dir else ROOT / "workspace"
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.on_metadata = on_metadata
        
        self.metrics = MetricsTracker(persist_path=str(LOGS_DIR / f"metrics_{int(time.time())}.json"))
        
        # Initialize agents
        self.planner = PlannerAgent(metrics=self.metrics)
        self.terminal = TerminalAgent(working_dir=str(self.project_dir), metrics=self.metrics)
        self.file_agent = FileAgent(base_dir=str(self.project_dir), metrics=self.metrics)
        self.router = RouterAgent(metrics=self.metrics)
        self.browser = BrowserAgent(headless=True, metrics=self.metrics)
        self.memory = MemoryAgent()
        self.scanner = ProjectScanner(str(self.project_dir))
        self.session_store = SessionStore(str(ROOT / "sessions"))

        logger.info(f"Operator initialized. Project dir: {self.project_dir}")

    def check_health(self) -> bool:
        """Verify Ollama and models before starting."""
        with console.status("[cyan]Checking system health..."):
            health = full_health_check([CODER_MODEL, ROUTER_MODEL])
            
            if not health["ollama"]["healthy"]:
                console.print(f"[bold red]✗ Ollama Error:[/] {health['ollama']['error']}")
                return False
                
            if not health["models"]["all_available"]:
                missing = ", ".join(health["models"]["missing"])
                console.print(f"[bold red]✗ Missing Models:[/] {missing}")
                console.print(f"Run: [white]ollama pull {missing}[/]")
                return False
                
            return True

    def run(self, goal: str) -> OperatorState:
        """Execute a goal autonomously."""
        state = OperatorState(goal=goal)
        session_id = f"sess_{int(state.start_time)}"
        
        self._print_header(goal)

        # ─── PHASE 1: CONTEXT GATHERING ──────────────────────────────────
        console.print("\n[bold cyan]◆ PHASE 1: CONTEXT GATHERING[/]")
        
        try:
            state.context = self.memory.get_relevant_context(goal) or ""
            if state.context: 
                console.print("  [green]✓[/] Retrieved past memory context")
                if self.on_metadata:
                    self.on_metadata({"type": "memory", "content": state.context})
            else: console.print("  [dim]i[/] No relevant past memory found")
        except Exception:
            pass

        try:
            with console.status("Scanning project directory..."):
                state.project_state = self.scanner.get_context_string()
            console.print("  [green]✓[/] Project state scanned")
        except Exception as e:
            console.print(f"  [yellow]⚠[/] Project scan failed: {e}")

        # ─── PHASE 2: PLANNING ───────────────────────────────────────────
        console.print("\n[bold cyan]◆ PHASE 2: PLANNING[/]")
        if self.on_metadata:
            self.on_metadata({"type": "status", "content": "Planning..."})
        
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            task = progress.add_task("Generating execution plan...", total=None)
            state.plan = self.planner.plan(goal, context=state.context, project_state=state.project_state)
            progress.update(task, completed=True)

        self._print_plan(state.plan)
        if self.on_metadata:
            self.on_metadata({"type": "plan", "steps": state.plan})

        if not state.plan or state.plan[0].startswith("ERROR"):
            state.status = "failed"
            state.end_time = time.time()
            console.print("[bold red]✗ Planning failed. Cannot proceed.[/]")
            return state

        # ─── PHASE 3: EXECUTION LOOP ─────────────────────────────────────
        console.print("\n[bold cyan]◆ PHASE 3: EXECUTION[/]")
        state.status = "running"
        loop_count = 0
        
        current_node = "route"
        route_data = {}
        task_result = None

        while state.status == "running" and loop_count < AUTONOMOUS_LOOP_LIMIT:
            loop_count += 1
            
            if current_node == "route":
                if not state.plan:
                    state.status = "completed"
                    break
                
                state.current_task = state.plan.pop(0)
                step_idx = len(state.completed) + 1
                console.print(f"\n  [bold]Step {step_idx}/{state.total_steps}:[/] {state.current_task}")
                if self.on_metadata:
                    self.on_metadata({"type": "step", "content": state.current_task, "index": step_idx, "total": state.total_steps})
                
                route_data = self.router.classify(state.current_task)
                current_node = "execute"
                
            elif current_node == "execute":
                task_type = route_data.get("task_type", "terminal")
                task_result = self._execute_task_by_type(state.current_task, task_type, state)
                task_result.task = state.current_task
                current_node = "evaluate"
                
            elif current_node == "evaluate":
                self.session_store.save(session_id, state.model_dump())
                
                if task_result.success:
                    state.completed.append(task_result)
                    console.print(f"    [green]✓[/] {task_result.output[:150]}")
                    try: self.memory.store_action(state.current_task, task_result.output[:500], True)
                    except: pass
                    current_node = "route"
                else:
                    state.failed.append(task_result)
                    console.print(f"    [red]✗[/] {task_result.error[:150]}")
                    current_node = "recover"
                    
            elif current_node == "recover":
                console.print(f"    [yellow]↻ Attempting dynamic recovery...[/]")
                try:
                    recovery_tasks = self.planner.replan(
                        goal=goal,
                        completed=[r.task for r in state.completed],
                        failed_task=state.current_task,
                        error=task_result.error[:500],
                        error_category=getattr(task_result, "error_category", "unknown")
                    )
                    
                    if recovery_tasks and not recovery_tasks[0].startswith("ERROR"):
                        console.print(f"    [cyan]i[/] Planner generated {len(recovery_tasks)} recovery steps")
                        state.plan = recovery_tasks + state.plan
                        current_node = "route"
                        continue
                except Exception as e:
                    logger.error(f"Replanning failed: {e}")
                
                console.print(f"    [red]✗ Recovery failed, halting execution.[/]")
                try: self.memory.store_error(state.current_task, task_result.error)
                except: pass
                state.status = "failed"
                break

        # ─── PHASE 4: WRAP UP ────────────────────────────────────────────
        state.end_time = time.time()
        if state.status == "running":
            state.status = "completed" if not state.failed else "completed_with_errors"
        
        self.metrics.save()
        self.session_store.save(session_id, state.model_dump())
        
        if self.browser:
            self.browser.close()
            
        get_mcp_client().close()

        try:
            self.memory.store_workflow(goal, [r.task for r in state.completed], success=len(state.failed) == 0)
        except: pass

        self._print_summary(state)
        return state

    def _execute_task_by_type(self, task: str, task_type: str, state: OperatorState) -> TaskResult:
        """Route to appropriate agent and format result."""
        start = time.time()
        
        # Clean prefix if present
        task_body = task
        if ":" in task:
            task_body = task.split(":", 1)[1].strip()

        try:
            if task_type == "terminal" or task_type == "validate":
                res = self.terminal.execute_task(task_body, project_dir=str(self.project_dir), state=state)
                return TaskResult(
                    task=task, task_type=task_type, success=res.success,
                    output=res.stdout[:2000] if res.success else "",
                    error=res.error or res.stderr[:500],
                    duration=res.duration
                )
                
            elif task_type == "file":
                res = self.file_agent.execute_task(task_body, state=state)
                return TaskResult(
                    task=task, task_type=task_type, success=res.success,
                    output=res.message, error="" if res.success else res.message,
                    duration=time.time() - start
                )
                
            elif task_type == "browser":
                res = self.browser.execute_task(task_body, state=state)
                return TaskResult(
                    task=task, task_type=task_type, success=res.success,
                    output=res.data[:2000] if res.success else res.message,
                    error="" if res.success else res.message,
                    duration=time.time() - start
                )
                
            else:
                return TaskResult(task=task, task_type=task_type, success=False, output="", error=f"Unknown task type: {task_type}", duration=time.time() - start)
                
        except Exception as e:
            return TaskResult(task=task, task_type=task_type, success=False, output="", error=f"Agent crash: {str(e)}", duration=time.time() - start)

    def _print_header(self, goal: str):
        console.print()
        console.print(Panel(
            f"[bold white]{goal}[/]",
            title="[bold cyan]⚡ ANTIGRAVITY OPERATOR[/]",
            subtitle="[dim]Local Autonomous AI Engine[/dim]",
            border_style="cyan",
            box=box.DOUBLE,
            padding=(1, 2),
        ))

    def _print_plan(self, plan: list[str]):
        table = Table(title="Execution Plan", box=box.ROUNDED, border_style="blue", show_lines=True)
        table.add_column("#", style="bold", width=4)
        table.add_column("Task", style="white")

        for i, task in enumerate(plan, 1):
            table.add_row(str(i), task)
        console.print(table)

    def _print_summary(self, state: OperatorState):
        console.print()
        table = Table(title="Session Summary", box=box.DOUBLE, border_style="cyan")
        table.add_column("Metric", style="bold")
        table.add_column("Value")

        status_color = "green" if state.status == "completed" else "yellow" if state.status == "completed_with_errors" else "red"
        table.add_row("Status", f"[{status_color}]{state.status.upper()}[/]")
        table.add_row("Duration", f"{state.duration:.1f}s")
        table.add_row("Steps", f"{len(state.completed)} completed, {len(state.failed)} failed")
        
        console.print(table)
        console.print(self.metrics.print_summary())

# ─── CLI Entry Point ─────────────────────────────────────────────────────────

def main():
    console.print(Panel(
        "[bold]ANTIGRAVITY OPERATOR[/]\n"
        "[dim]Local Autonomous AI Engine[/dim]\n\n"
        "Enter a goal and watch the operator execute it autonomously.\n"
        "Type [bold cyan]quit[/] or [bold cyan]exit[/] to stop.",
        border_style="cyan",
        box=box.DOUBLE,
    ))

    operator = AntigravityOperator()
    
    if not operator.check_health():
        sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] != "--interactive":
        goal = " ".join(sys.argv[1:])
        state = operator.run(goal)
        sys.exit(0 if state.status == "completed" else 1)

    while True:
        console.print()
        try:
            goal = console.input("[bold cyan]🎯 Goal:[/] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        if not goal: continue
        if goal.lower() in ("quit", "exit", "q"):
            break

        operator.run(goal)

if __name__ == "__main__":
    main()
