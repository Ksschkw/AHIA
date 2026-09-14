"""Structural checks on the audit wiring.

M14.1.3 says the trail is written by every mutating use case from M4 onward. That is a claim
about every service in the package, and a claim about every service is one that rots the moment
somebody adds a use case and forgets. These tests read the source rather than a list somebody
maintains:

*   a service module that commits a transaction must reference the recorder, or be a documented
    exception;
*   every exception must still exist, so an exemption cannot outlive the file it excused;
*   every exception must state in its own docstring why it is not in the trail, which is what
    makes the list reviewable rather than a dumping ground.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SERVICES_ROOT = Path(__file__).resolve().parents[2] / "src" / "ahia" / "services"

#: Services that mutate and are deliberately not in the tenant-scoped trail, each with the
#: reason. The reason is repeated in the module's own docstring, and a test below asserts that
#: it is there: an exemption a reader cannot find in the file is an exemption nobody reviews.
EXEMPT_SERVICES: dict[str, str] = {
    # The recorder itself: it writes the events, it does not record one for writing them.
    "audit_event_service.py": "the recorder",
    # Authentication happens before a business is chosen, and a person can belong to several.
    # These actions are written by the structured security log instead.
    "auth_service.py": "authentication precedes the tenant",
    "user_service.py": "account actions are not tenant-scoped",
    "iam_seed_service.py": "provisioning the registry is a deployment action",
    # Bookkeeping derived from the image use case, which writes its own event.
    "storage_quota_service.py": "quota accounting is derived from another use case",
}


def service_modules() -> list[Path]:
    return sorted(path for path in SERVICES_ROOT.glob("*_service.py") if path.name != "__init__.py")


def commits_a_transaction(source: str) -> bool:
    return "unit_of_work.commit()" in source


@pytest.mark.architecture
def test_every_service_that_mutates_records_an_audit_event() -> None:
    """The guard that makes M14.1.3 a property of the code rather than of a commit message."""
    missing: list[str] = []
    for path in service_modules():
        source = path.read_text(encoding="utf-8")
        if not commits_a_transaction(source):
            continue
        if path.name in EXEMPT_SERVICES:
            continue
        if "_audit.record_audit_event(" not in source:
            missing.append(path.name)

    assert not missing, (
        "these services commit a transaction but write no audit event:\n  "
        + "\n  ".join(missing)
        + "\nEither wire the recorder or add the service to EXEMPT_SERVICES with a reason "
        "repeated in its docstring."
    )


@pytest.mark.architecture
def test_the_exemptions_still_describe_real_files() -> None:
    for name in EXEMPT_SERVICES:
        assert (SERVICES_ROOT / name).is_file(), f"stale audit exemption: {name}"


@pytest.mark.architecture
def test_each_exemption_states_its_reason_in_the_file() -> None:
    """An exemption a reader cannot find in the file is an exemption nobody reviews.

    The convention is one comment line beginning `# Audit exemption:`, with a reason long
    enough to be a reason. A reader who opens the module sees why it is not in the trail
    before they wonder whether somebody forgot.
    """
    marker = "# Audit exemption:"
    offenders: list[str] = []
    for name in EXEMPT_SERVICES:
        if name == "audit_event_service.py":
            continue
        source = (SERVICES_ROOT / name).read_text(encoding="utf-8")
        reason = ""
        for line in source.splitlines():
            if line.strip().startswith(marker):
                reason = line.split(marker, 1)[1].strip()
                break
        if len(reason) < 40:
            offenders.append(name)

    assert not offenders, (
        "these exempt services carry no usable `# Audit exemption:` comment:\n  "
        + "\n  ".join(offenders)
    )
