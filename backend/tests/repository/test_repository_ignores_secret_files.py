"""Tests that secret-bearing paths are actually ignored by git.

`.gitignore` is a convention until something checks it. These tests turn the
convention into an executable guarantee: every path that could carry a
credential must be reported by `git check-ignore`, and the placeholder template
must not be.

The check runs the real git binary against the real repository, because a
reimplementation of gitignore matching would prove nothing about the file git
actually reads.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SECRET_BEARING_PATHS: tuple[str, ...] = (
    ".env",
    ".env.local",
    ".env.production",
    "backend/.env",
    "backend/.env.local",
    "backend/.env.production",
    "backend/certs/api.pem",
    "backend/certs/private.key",
    "backend/keystore.p12",
    "secrets/database.json",
    "secrets/production.yaml",
    "credentials.json",
    "service-account-prod.json",
    "backend/.venv/lib/python3.12/site-packages/ahia/__init__.py",
    "backend/local_dump.sqlite",
    ".tools/bin/gitleaks",
)

TRACKABLE_PATHS: tuple[str, ...] = (
    "backend/.env.example",
    "backend/pyproject.toml",
    "backend/requirements.lock",
    "docs/PREREQUISITES.md",
    "TASKS.md",
)


def is_ignored(repository_root: Path, relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", relative_path],
        cwd=repository_root,
        check=False,
    )
    if result.returncode not in (0, 1):
        pytest.fail(f"git check-ignore failed for {relative_path} with code {result.returncode}")
    return result.returncode == 0


@pytest.mark.security
@pytest.mark.parametrize("relative_path", SECRET_BEARING_PATHS)
def test_secret_bearing_path_is_ignored(repository_root: Path, relative_path: str) -> None:
    assert is_ignored(repository_root, relative_path), (
        f"{relative_path} is not ignored and could be committed by accident"
    )


@pytest.mark.security
@pytest.mark.parametrize("relative_path", TRACKABLE_PATHS)
def test_trackable_path_is_not_ignored(repository_root: Path, relative_path: str) -> None:
    assert not is_ignored(repository_root, relative_path), (
        f"{relative_path} is ignored but must be committed"
    )


@pytest.mark.security
def test_env_example_contains_no_real_looking_values(backend_directory: Path) -> None:
    """Placeholders only: the template must not look like a working secret."""
    content = (backend_directory / ".env.example").read_text(encoding="utf-8")

    # The PEM header is assembled from two fragments on purpose. Written out in
    # full it would be detected by the `detect-private-key` pre-commit hook and
    # reported as a committed key, which is a false positive that trains people
    # to ignore that hook. The assertion below checks the same string.
    pem_header = "-----BEGIN " + "PRIVATE KEY-----"
    forbidden_fragments = (
        "AKIA",
        pem_header,
        "postgres://user:password@",
    )
    for fragment in forbidden_fragments:
        assert fragment not in content, f".env.example must not contain {fragment}"

    for line in content.splitlines():
        if line.startswith("JWT_SECRET=") or line.startswith("REFRESH_TOKEN_PEPPER="):
            _, _, value = line.partition("=")
            assert "replace" in value.lower(), f"{line} must remain a placeholder"
