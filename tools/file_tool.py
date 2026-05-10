"""
File Tool — Safe file operations with path validation.

Handles create, edit, append, and read operations.
All paths are validated to prevent writes outside the project directory.
"""

import os
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger("antigravity.file_tool")


@dataclass
class FileResult:
    """Result of a file operation."""
    path: str
    action: str
    success: bool
    message: str
    content: str = ""

    def summary(self) -> str:
        status = "✅" if self.success else "❌"
        return f"{status} [{self.action.upper()}] {self.path} — {self.message}"


class FileTool:
    """
    Safe file operations tool.
    
    All paths are resolved relative to a base directory.
    Prevents path traversal attacks and writes outside the project.
    """

    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir).resolve()

    def _resolve_safe_path(self, relative_path: str) -> tuple[Path | None, str]:
        """
        Resolve a path safely within the base directory.
        Returns (resolved_path, error_message).
        """
        try:
            # Handle absolute-looking paths from Docker context
            path_str = relative_path.replace("\\", "/")
            if path_str.startswith("/workspace/"):
                path_str = path_str[11:]
            elif path_str.startswith("/workspace"):
                path_str = path_str[10:]
            elif path_str.startswith("/"):
                path_str = path_str[1:]
            
            target = (self.base_dir / path_str).resolve()
            
            # Ensure the resolved path is within the base directory
            if not str(target).lower().startswith(str(self.base_dir).lower()):
                return None, f"PATH TRAVERSAL BLOCKED: {relative_path} resolves outside project ({target} vs {self.base_dir})"
            return target, ""
        except Exception as e:
            return None, f"PATH ERROR: {str(e)}"

    def create(self, relative_path: str, content: str) -> FileResult:
        """Create a new file with the given content."""
        target, error = self._resolve_safe_path(relative_path)
        if error:
            return FileResult(relative_path, "create", False, error)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            logger.info(f"Created file: {target} ({len(content)} bytes)")
            return FileResult(
                str(relative_path), "create", True,
                f"Created ({len(content)} bytes, {content.count(chr(10))+1} lines)"
            )
        except Exception as e:
            logger.error(f"Failed to create {relative_path}: {e}")
            return FileResult(relative_path, "create", False, str(e))

    def edit(self, relative_path: str, content: str) -> FileResult:
        """Replace a file's entire content (full overwrite)."""
        target, error = self._resolve_safe_path(relative_path)
        if error:
            return FileResult(relative_path, "edit", False, error)

        if not target.exists():
            return FileResult(relative_path, "edit", False, "File does not exist")

        try:
            old_size = target.stat().st_size
            target.write_text(content, encoding="utf-8")
            new_size = len(content.encode("utf-8"))
            logger.info(f"Edited file: {target} ({old_size} → {new_size} bytes)")
            return FileResult(
                str(relative_path), "edit", True,
                f"Updated ({old_size} → {new_size} bytes)"
            )
        except Exception as e:
            logger.error(f"Failed to edit {relative_path}: {e}")
            return FileResult(relative_path, "edit", False, str(e))

    def append(self, relative_path: str, content: str) -> FileResult:
        """Append content to a file."""
        target, error = self._resolve_safe_path(relative_path)
        if error:
            return FileResult(relative_path, "append", False, error)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Appended to file: {target} (+{len(content)} bytes)")
            return FileResult(
                str(relative_path), "append", True,
                f"Appended {len(content)} bytes"
            )
        except Exception as e:
            logger.error(f"Failed to append to {relative_path}: {e}")
            return FileResult(relative_path, "append", False, str(e))

    def read(self, relative_path: str) -> FileResult:
        """Read a file's content."""
        target, error = self._resolve_safe_path(relative_path)
        if error:
            return FileResult(relative_path, "read", False, error)

        if not target.exists():
            return FileResult(relative_path, "read", False, "File does not exist")

        try:
            content = target.read_text(encoding="utf-8")
            return FileResult(
                str(relative_path), "read", True,
                f"Read {len(content)} bytes",
                content=content,
            )
        except Exception as e:
            logger.error(f"Failed to read {relative_path}: {e}")
            return FileResult(relative_path, "read", False, str(e))

    def delete(self, relative_path: str) -> FileResult:
        """Delete a file."""
        target, error = self._resolve_safe_path(relative_path)
        if error:
            return FileResult(relative_path, "delete", False, error)

        if not target.exists():
            return FileResult(relative_path, "delete", False, "File does not exist")

        try:
            target.unlink()
            logger.info(f"Deleted file: {target}")
            return FileResult(str(relative_path), "delete", True, "Deleted")
        except Exception as e:
            logger.error(f"Failed to delete {relative_path}: {e}")
            return FileResult(relative_path, "delete", False, str(e))

    def list_files(self, relative_dir: str = ".") -> FileResult:
        """List files in a directory."""
        target, error = self._resolve_safe_path(relative_dir)
        if error:
            return FileResult(relative_dir, "list", False, error)

        if not target.is_dir():
            return FileResult(relative_dir, "list", False, "Not a directory")

        try:
            files = []
            for item in sorted(target.rglob("*")):
                if item.is_file():
                    rel = item.relative_to(target)
                    files.append(str(rel))
            content = "\n".join(files)
            return FileResult(
                str(relative_dir), "list", True,
                f"Found {len(files)} files",
                content=content,
            )
        except Exception as e:
            return FileResult(relative_dir, "list", False, str(e))


# ─── Quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from rich.console import Console
    console = Console()

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tool = FileTool(tmp)

        # Create
        r = tool.create("test/hello.py", "print('hello world')\n")
        console.print(r.summary())

        # Read
        r = tool.read("test/hello.py")
        console.print(r.summary())
        console.print(f"  Content: {r.content!r}")

        # Edit
        r = tool.edit("test/hello.py", "print('updated!')\n")
        console.print(r.summary())

        # List
        r = tool.list_files(".")
        console.print(r.summary())
        console.print(f"  Files: {r.content}")

        # Path traversal attempt
        r = tool.create("../../evil.txt", "hacked")
        console.print(r.summary())
