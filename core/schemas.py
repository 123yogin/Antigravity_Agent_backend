from pydantic import BaseModel, Field
from typing import List, Literal

class TaskClassification(BaseModel):
    task_type: Literal["terminal", "file", "browser", "validate", "compound"] = Field(
        description="The type of agent that should handle this task"
    )
    complexity: Literal["simple", "moderate", "complex"] = Field(
        description="How complex the task is"
    )
    needs_context: bool = Field(
        description="Whether the task needs project context to execute"
    )
    subtasks: List[str] = Field(
        default_factory=list,
        description="If compound, break into subtasks. Empty otherwise."
    )

class ExecutionPlan(BaseModel):
    tasks: List[str] = Field(
        description="Ordered list of executable tasks. Each prefixed with type: 'terminal: ...', 'file: ...', 'browser: ...', or 'validate: ...'"
    )
    reasoning: str = Field(
        description="Brief explanation of why this plan was chosen"
    )
