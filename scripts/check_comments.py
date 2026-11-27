"""Fail on `#` comments in Python code (project rule: code must explain itself).

Allowed: docstrings, tool directives (`# noqa`, `# type: ignore`, `# pragma: no cover`)
and a shebang on the first line.

Usage:
    python scripts/check_comments.py [--root PATH]
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tokenize
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
SCANNED_DIRS = ("src", "tests", "evals", "scripts")
TOOL_DIRECTIVE = re.compile(r"^#\s*(noqa\b|type:\s*ignore\b|pragma:\s*no cover\b)")
IGNORED_PARTS = {".venv", "__pycache__", ".cache"}


def is_allowed(comment: str, line_number: int) -> bool:
    if line_number == 1 and comment.startswith("#!"):
        return True
    return bool(TOOL_DIRECTIVE.match(comment))


def comment_violations(path: Path) -> list[int]:
    source = path.read_text(encoding="utf-8")
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    return [
        token.start[0]
        for token in tokens
        if token.type == tokenize.COMMENT and not is_allowed(token.string, token.start[0])
    ]


def python_files(root: Path) -> list[Path]:
    files = []
    for folder in SCANNED_DIRS:
        for path in sorted((root / folder).rglob("*.py")):
            if not IGNORED_PARTS.intersection(path.parts):
                files.append(path)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    violations = [
        f"{path.relative_to(args.root)}:{line}"
        for path in python_files(args.root)
        for line in comment_violations(path)
    ]
    if violations:
        print("Comments are not allowed (see .claude/rules/python.md):")
        print("\n".join(violations))
        return 1
    print("No comments found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
