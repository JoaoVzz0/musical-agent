"""Check that every `test` row of the Definition of Done has at least one marked test.

Usage:
    python scripts/dod_check.py 02 03.D        phases or track prefixes
    python scripts/dod_check.py --done         every track marked done in STATUS.md

Tests link to DoD rows with `@pytest.mark.dod("02.C3", ...)`. Exit codes: 0 all covered,
1 rows without tests, 2 a scope that matches no DoD row.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DOD_ROW = re.compile(r"^\|\s*(\d{2}\.[A-Z]\d+)\s*\|(.+)\|\s*([^|]+?)\s*\|\s*$")
STATUS_ROW = re.compile(r"^\|\s*W\d\s*\|\s*([\d.A-Z]+)\s[^|]*\|\s*done\s*\|")
TEST_SEARCH_DIRS = ("tests", "evals")


@dataclass(frozen=True)
class DodRow:
    id: str
    verified_by: str

    @property
    def needs_test(self) -> bool:
        return self.verified_by.lower().startswith("test")


def read_dod_rows(specs_dir: Path) -> list[DodRow]:
    rows = []
    for spec in sorted(specs_dir.glob("[0-9][0-9]-*.md")):
        for line in spec.read_text(encoding="utf-8").splitlines():
            match = DOD_ROW.match(line)
            if match:
                rows.append(DodRow(id=match.group(1), verified_by=match.group(3)))
    return rows


def done_scopes(status_file: Path) -> list[str]:
    if not status_file.is_file():
        return []
    lines = status_file.read_text(encoding="utf-8").splitlines()
    return [match.group(1) for line in lines if (match := STATUS_ROW.match(line))]


def in_scope(row_id: str, scope: str) -> bool:
    return row_id.startswith(scope)


def is_dod_marker(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "dod"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
    )


def marked_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    for folder in TEST_SEARCH_DIRS:
        for path in (root / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and is_dod_marker(node):
                    ids.update(
                        arg.value
                        for arg in node.args
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                    )
    return ids


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scopes", nargs="*", help="phase (02) or track prefix (02.A)")
    parser.add_argument("--done", action="store_true", help="check tracks marked done")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    specs_dir = args.root / "docs" / "specs"
    scopes = list(args.scopes)
    if args.done:
        scopes += done_scopes(specs_dir / "STATUS.md")

    rows = read_dod_rows(specs_dir)
    covered = marked_ids(args.root)
    unmatched = [scope for scope in scopes if not any(in_scope(r.id, scope) for r in rows)]
    if unmatched and not args.done:
        print(f"No DoD rows match: {', '.join(unmatched)}")
        return 2

    selected = [row for row in rows if any(in_scope(row.id, scope) for scope in scopes)]
    missing = [row.id for row in selected if row.needs_test and row.id not in covered]
    checked = sum(row.needs_test for row in selected)
    if missing:
        print(f"Missing tests for {len(missing)} of {checked} test rows: {', '.join(missing)}")
        return 1
    print(f"DoD traceability OK: {checked} test rows covered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
