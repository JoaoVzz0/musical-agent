from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from musical_agent.config import PROJECT_ROOT

SCRIPTS = PROJECT_ROOT / "scripts"

SPEC_02 = """# Spec 02

## DoD
| ID | Criterion | Verified by |
|---|---|---|
| 02.A1 | Loads products | test |
| 02.A2 | Normalizes phones | test |
| 02.B1 | Chunks sections | test (offline) |
| 02.X1 | Assumptions recorded | manual: review |
| 02.X2 | Suite green | command |

## Commits
"""

STATUS = """# Status
| Wave | Track | Status | Commits |
|---|---|---|---|
| W1 | 02.A CSV loader | done | abc123 |
| W1 | 02.B Manual index | pending | |
"""


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def write_repo(root: Path, test_source: str) -> Path:
    (root / "docs" / "specs").mkdir(parents=True)
    (root / "docs" / "specs" / "02-data-and-rules.md").write_text(SPEC_02)
    (root / "docs" / "specs" / "STATUS.md").write_text(STATUS)
    (root / "tests").mkdir()
    (root / "tests" / "test_sample.py").write_text(test_source)
    (root / "evals").mkdir()
    return root


@pytest.mark.dod("01.X6")
def test_dod_check_reports_test_rows_without_tests(tmp_path):
    root = write_repo(tmp_path, '@pytest.mark.dod("02.A1")\ndef test_a():\n    pass\n')

    result = run_script("dod_check.py", "02", "--root", str(root))

    assert result.returncode == 1
    assert "02.A2" in result.stdout
    assert "02.B1" in result.stdout
    assert "02.A1" not in result.stdout.split("Missing")[-1]
    assert "02.X1" not in result.stdout
    assert "02.X2" not in result.stdout


@pytest.mark.dod("01.X6")
def test_dod_check_passes_when_every_test_row_is_covered(tmp_path):
    source = (
        '@pytest.mark.dod("02.A1", "02.A2")\ndef test_a():\n    pass\n\n'
        '@pytest.mark.dod("02.B1")\ndef test_b():\n    pass\n'
    )
    root = write_repo(tmp_path, source)

    result = run_script("dod_check.py", "02", "--root", str(root))

    assert result.returncode == 0, result.stdout


@pytest.mark.dod("01.X6")
def test_dod_check_scopes_by_track_prefix(tmp_path):
    root = write_repo(tmp_path, '@pytest.mark.dod("02.A1", "02.A2")\ndef test_a():\n    pass\n')

    result = run_script("dod_check.py", "02.A", "--root", str(root))

    assert result.returncode == 0, result.stdout


@pytest.mark.dod("01.X6")
def test_dod_check_done_mode_only_checks_tracks_marked_done(tmp_path):
    root = write_repo(tmp_path, '@pytest.mark.dod("02.A1", "02.A2")\ndef test_a():\n    pass\n')

    result = run_script("dod_check.py", "--done", "--root", str(root))

    assert result.returncode == 0, result.stdout


@pytest.mark.dod("01.X6")
def test_dod_check_rejects_scope_without_rows(tmp_path):
    root = write_repo(tmp_path, "")

    result = run_script("dod_check.py", "09", "--root", str(root))

    assert result.returncode == 2


def write_source(root: Path, source: str) -> Path:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "module.py").write_text(source)
    return root


@pytest.mark.dod("01.X9")
@pytest.mark.parametrize(
    "source",
    [
        "x = 1  # explain x\n",
        "# explain the next line\nx = 1\n",
        "def f():\n    # step one\n    return 1\n",
        "# x = old_code()\n",
    ],
)
def test_check_comments_flags_comments(tmp_path, source):
    root = write_source(tmp_path, source)

    result = run_script("check_comments.py", "--root", str(root))

    assert result.returncode == 1
    assert "module.py:" in result.stdout


@pytest.mark.dod("01.X9")
@pytest.mark.parametrize(
    "source",
    [
        '"""Module docstring."""\n\n\ndef f():\n    """Explain f."""\n    return 1\n',
        "import os  # noqa: F401\n",
        "x: int = 'a'  # type: ignore[assignment]\n",
        "if False:  # pragma: no cover\n    pass\n",
        "#!/usr/bin/env python3\nx = 1\n",
        "url = 'https://example.com/#anchor'\n",
    ],
)
def test_check_comments_accepts_docstrings_and_tool_directives(tmp_path, source):
    root = write_source(tmp_path, source)

    result = run_script("check_comments.py", "--root", str(root))

    assert result.returncode == 0, result.stdout
