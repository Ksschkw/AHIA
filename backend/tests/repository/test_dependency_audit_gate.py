"""Tests for the dependency audit gate.

The gate has three answers and one of them is dangerous: an audit that could not run must never
look like a clean one, and a finding must never look like an environment problem. Both mistakes end
the same way - somebody stops believing the gate - so all three answers are asserted, and the
finding is planted rather than waited for.

**The planted finding is the point.** A real advisory appearing in a pinned dependency is not a
test schedule, so the suite hands the gate a stub that reports a finding that has been public for
years and asserts the build goes red with the message an operator needs. That is the
micro-milestone's "deliberately planted test finding", met offline and deterministically.

**The tooling answer is not the finding answer.** A stub that exits non-zero without producing a
report is asserted to produce "the audit could not complete", because reporting it as a finding
sends somebody hunting for a vulnerability that does not exist.

**The parser is tested apart from the shell.** `audit_verdict.py` is what decides, so a malformed
report is asserted to be `tooling` rather than `clean`: guessing clean from something unreadable is
how a broken audit becomes a green build.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = BACKEND_ROOT / "scripts" / "audit_dependencies.sh"
VERDICT_SCRIPT = BACKEND_ROOT / "scripts" / "audit_verdict.py"
STUB_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "audit"

sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

from audit_verdict import CLEAN, FINDINGS, TOOLING, verdict_for  # noqa: E402


def run_gate(stub: str) -> subprocess.CompletedProcess[str]:
    """Run the gate with a stub standing in for pip-audit."""
    return subprocess.run(
        ["bash", str(AUDIT_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "PIP_AUDIT_BIN": str(STUB_DIRECTORY / stub),
            "HOME": str(Path.home()),
        },
        cwd=BACKEND_ROOT,
    )


# ---------------------------------------------------------------------------
# The gate, end to end, with a planted finding
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_planted_finding_fails_the_build() -> None:
    """The branch that has to work when it matters, exercised with a finding that cannot go away."""
    result = run_gate("planted_finding.sh")

    assert result.returncode == 1
    assert "vulnerabilities found" in result.stderr
    assert "CVE-2018-18074" in result.stderr, "the report is shown, so an operator can act"
    assert "dependency_audit_ignores.txt" in result.stderr, "the way to suppress it is named"


@pytest.mark.unit
def test_a_clean_report_passes_the_gate() -> None:
    result = run_gate("clean_report.sh")

    assert result.returncode == 0
    assert "[OK] dependency audit: no unignored vulnerabilities" in result.stdout


@pytest.mark.unit
def test_an_audit_that_could_not_run_is_not_reported_as_a_finding() -> None:
    """The mistake that teaches people to ignore the gate, asserted against."""
    result = run_gate("broken_report.sh")

    assert result.returncode == 1
    assert "could not complete" in result.stderr
    assert "vulnerabilities found" not in result.stderr
    assert "not a finding" in result.stderr


@pytest.mark.unit
def test_the_gate_refuses_a_binary_that_is_not_there() -> None:
    result = subprocess.run(
        ["bash", str(AUDIT_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PIP_AUDIT_BIN": "/nonexistent/pip-audit"},
        cwd=BACKEND_ROOT,
    )

    assert result.returncode == 1
    assert "pip-audit is not installed" in result.stderr


# ---------------------------------------------------------------------------
# The decision, apart from the shell
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_report_with_a_vulnerability_is_a_finding() -> None:
    report = {
        "dependencies": [
            {"name": "requests", "version": "2.0.0", "vulns": [{"id": "CVE-2018-18074"}]}
        ]
    }

    assert verdict_for(report) == FINDINGS


@pytest.mark.unit
def test_a_report_with_empty_vulnerability_lists_is_clean() -> None:
    report = {"dependencies": [{"name": "httpx", "version": "0.27.0", "vulns": []}]}

    assert verdict_for(report) == CLEAN


@pytest.mark.unit
@pytest.mark.parametrize(
    "report",
    [
        None,
        [],
        "a string",
        {},
        {"dependencies": None},
        {"dependencies": "not a list"},
        {"dependencies": ["not a mapping"]},
    ],
)
def test_a_report_that_cannot_be_read_is_a_tooling_failure(report: object) -> None:
    """Guessing `clean` from something unreadable is how a broken audit becomes a green build."""
    assert verdict_for(report) == TOOLING


@pytest.mark.unit
def test_the_verdict_script_reads_stdin_and_exits_for_tooling() -> None:
    """A shell that only looks at `$?` still cannot mistake an unrun audit for a clean one."""
    clean = subprocess.run(
        [sys.executable, str(VERDICT_SCRIPT)],
        input=json.dumps({"dependencies": []}),
        capture_output=True,
        text=True,
        check=False,
    )
    broken = subprocess.run(
        [sys.executable, str(VERDICT_SCRIPT)],
        input="not json at all",
        capture_output=True,
        text=True,
        check=False,
    )

    assert clean.stdout.strip() == CLEAN
    assert clean.returncode == 0
    assert broken.stdout.strip() == TOOLING
    assert broken.returncode == 1


@pytest.mark.unit
def test_the_ignore_entries_are_dated_and_justified() -> None:
    """A permanent ignore is an unaudited dependency, so the file's own policy is asserted.

    The file is empty today, and the assertion is about its shape rather than its content: an
    entry that arrives without a date or a reason would be rejected by the gate itself, and this
    test says so where a reader looks first.
    """
    ignore_file = BACKEND_ROOT / "dependency_audit_ignores.txt"
    entries = [
        line
        for line in ignore_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    for entry in entries:
        vulnerability_id, _, rest = entry.partition(" ")
        date, _, reason = rest.partition(" ")
        assert vulnerability_id and date and reason, f"malformed ignore entry: {entry}"
