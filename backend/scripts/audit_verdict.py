"""Read a pip-audit JSON report and say what it means.

The dependency gate has three outcomes and they must not be confused: the pinned set is clean, the
pinned set has a finding, or the audit could not run. The third is an environment failure - no
network, no index, a temporary build that failed - and reporting it as a finding sends somebody
hunting for a vulnerability that does not exist, which is how a real finding gets ignored the next
time.

This is a script rather than a module in `src/`: it runs next to the gate, it is invoked by the
shell script that owns the process, and nothing in the application imports it. Keeping the decision
in Python rather than in `grep` is what makes it testable - the gate most important branch is
covered by a test with fixtures instead of by reading the shell.

Usage: `audit_verdict.py` reads a JSON report on stdin and prints one of `clean`, `findings` or
`tooling` on stdout. Exit status is 0 for the first two and 1 for `tooling`, so a caller that
ignores stdout still cannot mistake an unrun audit for a clean one.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Final

CLEAN: Final[str] = "clean"
FINDINGS: Final[str] = "findings"
TOOLING: Final[str] = "tooling"

#: Exit codes, so a shell that only looks at `$?` still distinguishes an unrun audit from a
#: clean one.
_EXIT_CODES: Final[dict[str, int]] = {CLEAN: 0, FINDINGS: 0, TOOLING: 1}


def verdict_for(report: Any) -> str:
    """Return `clean`, `findings` or `tooling` for a decoded pip-audit report.

    A vulnerability is a dependency entry with a non-empty `vulns` list. Anything else - a report
    that is not a mapping, a missing `dependencies` key, entries that are not mappings - is
    `tooling`, because the honest answer to "was anything verified" is no. Guessing `clean` from a
    malformed report would turn a broken audit into a green build.
    """
    if not isinstance(report, dict):
        return TOOLING
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list):
        return TOOLING
    for entry in dependencies:
        if not isinstance(entry, dict):
            return TOOLING
        vulnerabilities = entry.get("vulns")
        if isinstance(vulnerabilities, list) and vulnerabilities:
            return FINDINGS
    return CLEAN


def main() -> int:
    """Read a report from stdin, print the verdict, and exit accordingly."""
    raw = sys.stdin.read()
    try:
        report = json.loads(raw)
    except ValueError:
        print(TOOLING)
        return _EXIT_CODES[TOOLING]
    decision = verdict_for(report)
    print(decision)
    return _EXIT_CODES[decision]


if __name__ == "__main__":
    raise SystemExit(main())
