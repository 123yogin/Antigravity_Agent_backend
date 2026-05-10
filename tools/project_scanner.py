"""
Project Scanner — Scans the workspace to provide context to the planner.

Gives the LLM awareness of:
- Current file tree structure
- Installed packages (pip, npm)
- Key project files (README, requirements.txt, package.json, etc.)
- Project type detection (Python, Node, Rust, etc.)
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("antigravity.scanner")

# File patterns that indicate project type
PROJECT_INDICATORS = {
    "python": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile", "setup.cfg"],
    "node": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "java": ["pom.xml", "build.gradle"],
    "dotnet": ["*.csproj", "*.sln"],
    "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
}

# Files to read for context (small config/metadata files)
CONTEXT_FILES = [
    "README.md", "readme.md", "README.txt",
    "requirements.txt",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    ".env.example",
    "Makefile",
    "Dockerfile",
]

# Skip these directories during scanning
SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "env", ".env", ".mypy_cache", ".pytest_cache", ".tox",
    "dist", "build", ".eggs", "*.egg-info", ".next",
    "target", ".cargo",
}

# Skip these file patterns
SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
    ".jpg", ".jpeg", ".png", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".lock",
}


class ProjectScanner:
    """
    Scan a project directory and produce a context summary for the planner.
    """

    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir).resolve()

    def scan_json(self) -> list:
        """
        Returns a structured JSON list of all files/dirs.
        """
        def _get_tree(path: Path):
            items = []
            try:
                for entry in sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                    if entry.name in SKIP_DIRS: continue
                    if entry.is_file() and entry.suffix in SKIP_EXTENSIONS: continue
                    
                    item = {
                        "name": entry.name,
                        "path": str(entry.relative_to(self.project_dir)).replace("\\", "/"),
                        "type": "directory" if entry.is_dir() else "file"
                    }
                    if entry.is_dir():
                        item["children"] = _get_tree(entry)
                    else:
                        item["size"] = self._format_size(entry.stat().st_size)
                    items.append(item)
            except Exception:
                pass
            return items
            
        return _get_tree(self.project_dir)

    def scan(self, max_depth: int = 4, max_files: int = 200) -> dict:
        """
        Perform a full project scan.
        
        Returns dict with:
            - file_tree: formatted string of the directory structure
            - project_types: detected project types
            - key_files: content of important config files
            - stats: file counts, total size, etc.
        """
        tree_lines = []
        file_count = 0
        dir_count = 0
        total_size = 0
        project_types = set()
        key_file_contents = {}

        def _scan_dir(dirpath: Path, prefix: str = "", depth: int = 0):
            nonlocal file_count, dir_count, total_size

            if depth > max_depth:
                tree_lines.append(f"{prefix}... (depth limit)")
                return
            if file_count > max_files:
                return

            try:
                entries = sorted(dirpath.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            except PermissionError:
                tree_lines.append(f"{prefix}[permission denied]")
                return

            dirs = [e for e in entries if e.is_dir() and e.name not in SKIP_DIRS]
            files = [e for e in entries if e.is_file() and e.suffix not in SKIP_EXTENSIONS]

            for i, entry in enumerate(dirs + files):
                is_last = (i == len(dirs) + len(files) - 1)
                connector = "└── " if is_last else "├── "
                extension = "    " if is_last else "│   "

                if entry.is_dir():
                    dir_count += 1
                    tree_lines.append(f"{prefix}{connector}{entry.name}/")
                    _scan_dir(entry, prefix + extension, depth + 1)
                else:
                    file_count += 1
                    size = entry.stat().st_size
                    total_size += size
                    size_str = self._format_size(size)
                    tree_lines.append(f"{prefix}{connector}{entry.name} ({size_str})")

                    # Detect project type
                    for ptype, indicators in PROJECT_INDICATORS.items():
                        if entry.name in indicators:
                            project_types.add(ptype)

                    # Read key files
                    if entry.name in CONTEXT_FILES and size < 10000:
                        try:
                            key_file_contents[entry.name] = entry.read_text(encoding="utf-8")[:3000]
                        except Exception:
                            pass

        _scan_dir(self.project_dir)

        return {
            "file_tree": "\n".join(tree_lines) if tree_lines else "(empty project)",
            "project_types": list(project_types),
            "key_files": key_file_contents,
            "stats": {
                "files": file_count,
                "directories": dir_count,
                "total_size": self._format_size(total_size),
                "total_bytes": total_size,
            },
        }

    def get_context_string(self, max_depth: int = 3) -> str:
        """
        Get a formatted context string suitable for LLM consumption.
        
        Returns a concise summary of the project state.
        """
        scan = self.scan(max_depth=max_depth)

        parts = [
            "=== PROJECT STATE ===",
            "Directory: /workspace",
            f"Types: {', '.join(scan['project_types']) or 'unknown'}",
            f"Stats: {scan['stats']['files']} files, {scan['stats']['directories']} dirs, {scan['stats']['total_size']}",
            "",
            "=== FILE TREE ===",
            scan["file_tree"],
        ]

        if scan["key_files"]:
            parts.append("\n=== KEY FILES ===")
            for name, content in list(scan["key_files"].items())[:3]:
                parts.append(f"\n--- {name} ---")
                # Truncate long files
                if len(content) > 1500:
                    content = content[:1500] + "\n... (truncated)"
                parts.append(content)

        return "\n".join(parts)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes to human-readable size."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.0f}{unit}" if unit == "B" else f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f}TB"


# ─── Quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel
    console = Console()

    scanner = ProjectScanner(".")
    context = scanner.get_context_string()
    console.print(Panel(context, title="Project Scan", border_style="cyan"))
