"""
Diff parser: extracts function/method-level changes from PR diff content.

The Harness PR files API returns a `patch` field per file containing
the unified diff text. This module parses those patches to identify
which named functions/methods were added, modified, or deleted.

Supports: Python, JavaScript, TypeScript, Go, Java, Kotlin, Rust, C/C++
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FunctionChange:
    name: str
    change_type: str           # "added" | "deleted" | "modified"
    line_number: int | None    # approximate line in the original file
    language: str              # detected language / extension


@dataclass
class FileDiffSummary:
    path: str
    language: str
    additions: int
    deletions: int
    functions: list[FunctionChange] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Language → function signature regex patterns
# Each pattern must have exactly one capture group: the function name.
# Patterns are tried in order; first match wins.
# ---------------------------------------------------------------------------

_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    ".py": [
        re.compile(r"^[ \t]*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("),
        re.compile(r"^[ \t]*class\s+([A-Za-z_]\w*)\s*[:\(]"),
    ],
    ".js": [
        re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$]\w*)\s*\("),
        re.compile(r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$]\w*)\s*=\s*(?:async\s+)?(?:function|\()"),
        re.compile(r"^[ \t]*(?:async\s+)?([A-Za-z_$]\w*)\s*\([^)]*\)\s*\{"),
        re.compile(r"^[ \t]*(?:export\s+)?class\s+([A-Za-z_$]\w*)"),
    ],
    ".ts": [
        re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$]\w*)\s*[<\(]"),
        re.compile(r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$]\w*)\s*=\s*(?:async\s+)?(?:function|\()"),
        re.compile(r"^[ \t]*(?:public|private|protected|static|async|override|\s)+([A-Za-z_$]\w*)\s*\([^)]*\)\s*(?::\s*\S+\s*)?\{"),
        re.compile(r"^[ \t]*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_$]\w*)"),
    ],
    ".tsx": [],  # reuses .ts
    ".jsx": [],  # reuses .js
    ".go": [
        re.compile(r"^func\s+(?:\(\s*\w+\s+\*?[\w.]+\s*\)\s+)?([A-Za-z_]\w*)\s*\("),
    ],
    ".java": [
        re.compile(r"^[ \t]*(?:(?:public|private|protected|static|final|abstract|synchronized|native|strictfp)\s+)*[\w<>\[\]]+\s+([A-Za-z_$]\w*)\s*\([^;{]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{"),
        re.compile(r"^[ \t]*(?:public|private|protected|abstract|\s)*\s+class\s+([A-Za-z_$]\w*)"),
    ],
    ".kt": [
        re.compile(r"^[ \t]*(?:suspend\s+)?(?:fun)\s+([A-Za-z_]\w*)\s*[<\(]"),
        re.compile(r"^[ \t]*(?:data\s+|sealed\s+|abstract\s+|open\s+)?class\s+([A-Za-z_]\w*)"),
    ],
    ".rs": [
        re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)\s*[<\(]"),
        re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|impl)\s+([A-Za-z_]\w*)"),
    ],
    ".c": [
        re.compile(r"^[\w\s\*]+\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{"),
    ],
    ".cpp": [
        re.compile(r"^[\w\s\*:<>]+\s+(?:[\w:]+::)?([A-Za-z_]\w*)\s*\([^;]*\)\s*(?:const\s*)?\{"),
    ],
    ".cs": [
        re.compile(r"^[ \t]*(?:(?:public|private|protected|internal|static|virtual|override|abstract|async|sealed)\s+)*[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{"),
        re.compile(r"^[ \t]*(?:public|private|internal|protected|abstract|sealed|\s)*\s+class\s+([A-Za-z_]\w*)"),
    ],
    ".rb": [
        re.compile(r"^[ \t]*def\s+(?:self\.)?([A-Za-z_]\w*)"),
        re.compile(r"^[ \t]*class\s+([A-Za-z_]\w*)"),
    ],
    ".php": [
        re.compile(r"^[ \t]*(?:public|private|protected|static|abstract|\s)*\s*function\s+([A-Za-z_]\w*)\s*\("),
        re.compile(r"^[ \t]*(?:abstract\s+)?class\s+([A-Za-z_]\w*)"),
    ],
    ".swift": [
        re.compile(r"^[ \t]*(?:(?:public|private|internal|fileprivate|open|static|class|override|final|mutating|nonmutating)\s+)*func\s+([A-Za-z_]\w*)\s*[<\(]"),
        re.compile(r"^[ \t]*(?:public|private|internal|open|\s)*(?:class|struct|enum|protocol)\s+([A-Za-z_]\w*)"),
    ],
}

# Alias extensions to existing patterns
_PATTERNS[".tsx"] = _PATTERNS[".ts"]
_PATTERNS[".jsx"] = _PATTERNS[".js"]
_PATTERNS[".h"] = _PATTERNS[".c"]
_PATTERNS[".hpp"] = _PATTERNS[".cpp"]
_PATTERNS[".cc"] = _PATTERNS[".cpp"]

_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rs": "Rust",
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".h": "C",
    ".hpp": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
}


def _get_extension(path: str) -> str:
    """Return the lowercase file extension, e.g. '.py'."""
    if "." in path:
        return "." + path.rsplit(".", 1)[-1].lower()
    return ""


def _detect_language(ext: str) -> str:
    return _EXTENSION_TO_LANGUAGE.get(ext, "Unknown")


def _get_patterns(ext: str) -> list[re.Pattern[str]]:
    return _PATTERNS.get(ext, [])


# ---------------------------------------------------------------------------
# Unified diff hunk parser
# ---------------------------------------------------------------------------

def _parse_hunk_header(line: str) -> tuple[int, int] | None:
    """
    Parse a unified diff hunk header like:  @@ -10,7 +10,14 @@
    Returns (new_start_line, new_line_count) or None if not a hunk header.
    """
    m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
    if not m:
        return None
    start = int(m.group(1))
    count = int(m.group(2)) if m.group(2) else 1
    return start, count


def _extract_function_name(line: str, patterns: list[re.Pattern[str]]) -> str | None:
    """Try each pattern against a raw diff line (strip the leading +/-/ char)."""
    # Strip the leading diff character (space, +, -)
    content = line[1:] if line and line[0] in ("+", "-", " ") else line
    for pattern in patterns:
        m = pattern.match(content)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_file_diff(file_data: dict[str, Any]) -> FileDiffSummary:
    """
    Parse a single file entry from the Harness PR files API.

    Expected fields in file_data:
      - path (or name): str
      - additions: int
      - deletions: int
      - patch (or diff): str  — unified diff text

    Returns a FileDiffSummary with identified function changes.
    """
    path: str = file_data.get("path") or file_data.get("name") or "unknown"
    additions: int = int(file_data.get("additions", 0))
    deletions: int = int(file_data.get("deletions", 0))
    patch: str = file_data.get("patch") or file_data.get("diff") or ""

    ext = _get_extension(path)
    language = _detect_language(ext)
    patterns = _get_patterns(ext)

    functions: list[FunctionChange] = []

    if patch and patterns:
        functions = _parse_patch_for_functions(patch, patterns, language)

    return FileDiffSummary(
        path=path,
        language=language,
        additions=additions,
        deletions=deletions,
        functions=functions,
    )


def _parse_patch_for_functions(
    patch: str,
    patterns: list[re.Pattern[str]],
    language: str,
) -> list[FunctionChange]:
    """
    Walk through a unified diff patch and identify changed function names.

    Strategy:
    1. Track current line number via hunk headers.
    2. For each changed line (+/-), check if it matches a function signature.
    3. Also check context lines immediately before/after changed blocks
       (context lines start with a space) to catch cases where only the body
       changed but the signature is in context.
    4. Deduplicate: if the same function appears in both +/- lines, classify
       it as "modified". If only in + lines, "added". If only in -, "deleted".
    """
    added_funcs: dict[str, int] = {}    # name → approximate line
    deleted_funcs: dict[str, int] = {}  # name → approximate line

    current_new_line = 0
    current_old_line = 0

    # Track functions visible in context (unchanged lines) near a changed block
    # to handle the case where a function body changes but not its signature
    context_window: list[str] = []   # last N unchanged lines seen
    in_changed_block = False
    changed_block_lines: list[tuple[str, int]] = []  # (line, new_line_no)

    lines = patch.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        # Hunk header
        hdr = _parse_hunk_header(line)
        if hdr:
            # Flush previous changed block
            _flush_changed_block(
                changed_block_lines, context_window, patterns, added_funcs, deleted_funcs
            )
            changed_block_lines = []
            context_window = []
            in_changed_block = False
            current_new_line = hdr[0]
            current_old_line = current_new_line  # approximate
            i += 1
            continue

        if line.startswith("+") and not line.startswith("+++"):
            # Added line
            func_name = _extract_function_name(line, patterns)
            if func_name:
                added_funcs.setdefault(func_name, current_new_line)
            changed_block_lines.append((line, current_new_line))
            in_changed_block = True
            current_new_line += 1

        elif line.startswith("-") and not line.startswith("---"):
            # Deleted line
            func_name = _extract_function_name(line, patterns)
            if func_name:
                deleted_funcs.setdefault(func_name, current_old_line)
            changed_block_lines.append((line, current_old_line))
            in_changed_block = True
            # Old line counter advances, new does not

        else:
            # Context line (space prefix or other)
            if in_changed_block and changed_block_lines:
                # Scan context lines for enclosing function signature
                func_name = _extract_function_name(line, patterns)
                if func_name and func_name not in added_funcs and func_name not in deleted_funcs:
                    # Function body was changed (signature is context)
                    added_funcs.setdefault(func_name, current_new_line)
                    deleted_funcs.setdefault(func_name, current_new_line)
            context_window.append(line)
            if len(context_window) > 5:
                context_window.pop(0)
            if in_changed_block and not line.startswith(" "):
                # End of changed block
                _flush_changed_block(
                    changed_block_lines, context_window, patterns, added_funcs, deleted_funcs
                )
                changed_block_lines = []
                in_changed_block = False
            current_new_line += 1

        i += 1

    # Final flush
    _flush_changed_block(
        changed_block_lines, context_window, patterns, added_funcs, deleted_funcs
    )

    # Classify
    results: list[FunctionChange] = []
    all_names = set(added_funcs) | set(deleted_funcs)
    for name in sorted(all_names):
        if name in added_funcs and name in deleted_funcs:
            change_type = "modified"
            line_no = added_funcs[name]
        elif name in added_funcs:
            change_type = "added"
            line_no = added_funcs[name]
        else:
            change_type = "deleted"
            line_no = deleted_funcs[name]

        results.append(
            FunctionChange(
                name=name,
                change_type=change_type,
                line_number=line_no,
                language=language,
            )
        )

    return results


def _flush_changed_block(
    changed_block_lines: list[tuple[str, int]],
    context_window: list[str],
    patterns: list[re.Pattern[str]],
    added_funcs: dict[str, int],
    deleted_funcs: dict[str, int],
) -> None:
    """
    When a changed block ends, scan the preceding context lines for a
    function signature that encloses the changed block. This handles the
    common case where only the function *body* was changed.
    """
    if not changed_block_lines:
        return
    # Look backwards through context for a signature
    for ctx_line in reversed(context_window):
        name = _extract_function_name(ctx_line, patterns)
        if name:
            # Classify as modified (both sides see the same function)
            first_line = changed_block_lines[0][1]
            added_funcs.setdefault(name, first_line)
            deleted_funcs.setdefault(name, first_line)
            break


def parse_pr_files(files: list[dict[str, Any]]) -> list[FileDiffSummary]:
    """
    Parse all files from a PR's file list and return per-file summaries
    with detected function changes.
    """
    summaries: list[FileDiffSummary] = []
    for f in files:
        try:
            summary = parse_file_diff(f)
            summaries.append(summary)
        except Exception as exc:
            path = f.get("path", "unknown")
            logger.warning(
                "Failed to parse diff for file",
                extra={"path": path, "error": str(exc)},
            )
    return summaries
