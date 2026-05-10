from pydantic import BaseModel, Field
from typing import List, Optional, Literal
import time

class TaskResult(BaseModel):
    task: str
    task_type: str
    success: bool
    output: str
    error: str = ""
    attempts: int = 1
    duration: float = 0.0

class OperatorState(BaseModel):
    goal: str
    status: Literal["pending", "running", "completed", "completed_with_errors", "failed"] = "pending"
    context: str = ""
    project_state: str = ""
    plan: List[str] = Field(default_factory=list)
    completed: List[TaskResult] = Field(default_factory=list)
    failed: List[TaskResult] = Field(default_factory=list)
    current_task: Optional[str] = None
    start_time: float = Field(default_factory=time.time)
    end_time: float = 0.0

    @property
    def duration(self) -> float:
        return (self.end_time or time.time()) - self.start_time

    @property
    def total_steps(self) -> int:
        return len(self.plan) + len(self.completed) + len(self.failed)
