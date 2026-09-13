"""Tests for the secret scanning configuration.

A scanner is only as good as its allowlist. An allowlist entry that is too
broad - a bare wildcard, or an entry with no stated reason - converts the
scanner into a formality while the team believes the repository is covered.

These tests keep the configuration honest:

1. the default detector set stays enabled
2. every allowlist entry has a name, a description and at least one path
3. no allowlist entry matches the whole repository
4. every path pattern is a valid regular expression

They do not attempt to re-implement the scanner. Detection behaviour is
verified by running gitleaks itself, which `make secrets` does.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

OVERLY_BROAD_PATTERNS = frozenset({".*", ".+", "*", "**", "/", "^.*$", ".*|.+", ""})


@pytest.fixture(scope="session")
def secret_scan_config(repository_root: Path) -> dict[str, object]:
    config_path = repository_root / ".gitleaks.toml"

    assert config_path.is_file(), "missing .gitleaks.toml"

    with config_path.open("rb") as config_file:
        return tomllib.load(config_file)


@pytest.mark.security
def test_default_detectors_remain_enabled(secret_scan_config: dict[str, object]) -> None:
    extend = secret_scan_config.get("extend")

    assert isinstance(extend, dict), "the configuration must extend the default rule set"
    assert extend.get("useDefault") is True, "default detectors must stay enabled"


@pytest.mark.security
def test_allowlist_entries_are_present(secret_scan_config: dict[str, object]) -> None:
    allowlists = secret_scan_config.get("allowlists")

    assert isinstance(allowlists, list) and allowlists, "expected at least one allowlist entry"


@pytest.mark.security
def test_every_allowlist_entry_is_justified(secret_scan_config: dict[str, object]) -> None:
    for entry in secret_scan_config["allowlists"]:
        assert isinstance(entry, dict)
        assert entry.get("name"), f"allowlist entry without a name: {entry}"
        assert entry.get("description"), f"allowlist entry without a reason: {entry.get('name')}"
        assert entry.get("paths"), f"allowlist entry without paths: {entry.get('name')}"


@pytest.mark.security
def test_no_allowlist_entry_matches_the_whole_repository(
    secret_scan_config: dict[str, object],
) -> None:
    for entry in secret_scan_config["allowlists"]:
        for pattern in entry.get("paths", []):
            assert pattern not in OVERLY_BROAD_PATTERNS, (
                f"allowlist entry {entry.get('name')} is too broad: {pattern}"
            )


@pytest.mark.security
def test_every_path_pattern_is_a_valid_regex(secret_scan_config: dict[str, object]) -> None:
    for entry in secret_scan_config["allowlists"]:
        for pattern in entry.get("paths", []):
            try:
                re.compile(pattern)
            except re.error as error:  # pragma: no cover - failure path
                pytest.fail(f"invalid pattern in {entry.get('name')}: {pattern} ({error})")
