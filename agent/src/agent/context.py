"""Workspace context gathering and reconnaissance for the RLM agent."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

IGNORED_DIRECTORIES = {
    ".git",
    "__pycache__",
    ".venv",
    "jobs",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
}


def scan_workspace(root: Path = Path(".")) -> dict[str, list[str]]:
    """Scan the workspace directory and categorize discovered files."""
    categories: dict[str, list[str]] = {
        "scripts": [],
        "configs": [],
        "docs": [],
        "data": [],
        "models_and_code": [],
        "other": [],
    }

    if not root.exists():
        return categories

    for current_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRECTORIES]
        rel_dir = Path(current_dir).relative_to(root)

        for filename in sorted(files):
            rel_path = rel_dir / filename
            full_path = root / rel_path

            try:
                size_bytes = full_path.stat().st_size
                size_str = f"{size_bytes}B" if size_bytes < 1024 else f"{size_bytes / 1024:.1f}KB"
            except Exception:
                size_str = "unknown"

            entry = f"{rel_path} ({size_str})"
            suffix = full_path.suffix.lower()
            name_lower = filename.lower()

            if suffix in {".sh", ".bash"} or full_path.parent == Path(".") and suffix == ".py":
                categories["scripts"].append(entry)
            elif suffix in {".yml", ".yaml", ".toml", ".json", ".ini", ".cfg", ".env"} or "config" in name_lower:
                categories["configs"].append(entry)
            elif suffix in {".md", ".txt", ".rst"} or "docs" in rel_path.parts:
                categories["docs"].append(entry)
            elif suffix in {".csv", ".parquet", ".duckdb", ".db", ".sqlite", ".tsv", ".avro"}:
                categories["data"].append(entry)
            elif suffix in {".sql", ".py", ".tf", ".hcl"}:
                categories["models_and_code"].append(entry)
            else:
                categories["other"].append(entry)

    return categories


def load_skills(skills_dir_env: str | None = None) -> str:
    """Load and format skill instruction files if available."""
    target_dir = skills_dir_env or os.environ.get("SKILLS_DIR")
    if not target_dir:
        return ""

    path = Path(target_dir)
    if not path.exists() or not path.is_dir():
        return ""

    skill_blocks: list[str] = []
    for skill_file in sorted(path.glob("**/*")):
        if skill_file.is_file() and skill_file.suffix.lower() in {".md", ".txt", ".yaml", ".yml"}:
            try:
                rel_name = skill_file.relative_to(path)
                content = skill_file.read_text(encoding="utf-8", errors="replace").strip()
                if content:
                    skill_blocks.append(f"### Skill: {rel_name}\n```markdown\n{content}\n```")
            except Exception:
                continue

    if not skill_blocks:
        return ""

    return "## Attached Skills & Best Practices:\n" + "\n\n".join(skill_blocks)


def check_available_tools() -> list[str]:
    """Detect available CLI tools installed in the container."""
    candidates = ["duckdb", "dbt", "pytest", "terraform", "git", "python3", "uv", "curl", "jq"]
    return [name for name in candidates if shutil.which(name)]


def load_documentation(root: Path = Path(".")) -> str:
    """Read all markdown and text documentation files in docs/ or workspace root.

    In data engineering tasks, critical business rules, methodology filters,
    straight-liner/speeder exclusions, and data dictionaries are located in docs/.
    Loading them up front prevents missed requirements.
    """
    doc_blocks: list[str] = []
    doc_paths: list[Path] = []

    for candidate_dir in [root / "docs", root / "app" / "docs", root / "specs"]:
        if candidate_dir.exists() and candidate_dir.is_dir():
            for p in sorted(candidate_dir.glob("**/*")):
                if p.is_file() and p.suffix.lower() in {".md", ".txt", ".rst"}:
                    if p not in doc_paths:
                        doc_paths.append(p)

    total_chars = 0
    for p in doc_paths:
        try:
            rel_name = p.relative_to(root)
            content = p.read_text(encoding="utf-8", errors="replace").strip()
            if content and total_chars + len(content) < 40_000:
                doc_blocks.append(f"### Document: `{rel_name}`\n```markdown\n{content}\n```")
                total_chars += len(content)
        except Exception:
            continue

    if not doc_blocks:
        return ""

    return "## Project Documentation & Business Specifications (CRITICAL - READ ALL RULES):\n" + "\n\n".join(doc_blocks)


def build_workspace_context(root: Path = Path(".")) -> str:
    """Build a comprehensive, structured workspace context overview."""
    sections: list[str] = []

    # 1. Environment and Available CLI tools
    available_clis = check_available_tools()
    sections.append(f"## Environment Info\n- Working directory: `/app`\n- Available tools: {', '.join(available_clis)}")

    # 2. Project Documentation (Specs, Methodology, Rules)
    docs_context = load_documentation(root)
    if docs_context:
        sections.append(docs_context)

    # 3. File layout
    categories = scan_workspace(root)
    file_overview: list[str] = ["## Workspace Files"]

    for cat_name, entries in categories.items():
        if entries:
            header_title = cat_name.replace("_", " ").title()
            items = "\n".join(f"  - {e}" for e in entries[:25])
            if len(entries) > 25:
                items += f"\n  - ... and {len(entries) - 25} more"
            file_overview.append(f"### {header_title}\n{items}")

    sections.append("\n\n".join(file_overview))

    # 4. Skills if attached
    skills_context = load_skills()
    if skills_context:
        sections.append(skills_context)

    return "\n\n".join(sections)
