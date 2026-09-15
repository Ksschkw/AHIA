#!/usr/bin/env bash
# A pip-audit that reports one planted finding.
#
# The gate's failure path is the one branch that must work when it matters, and waiting for a real
# advisory to appear in a pinned dependency is not a test. This stub reports a finding that has been
# public for years, exits non-zero the way pip-audit does, and lets the suite assert that the gate
# fails the build with the message an operator needs.
set -Eeuo pipefail
printf '%s' '{"dependencies": [{"name": "requests", "version": "2.0.0", "vulns": [{"id": "CVE-2018-18074", "fix_versions": ["2.31.0"]}]}]}'
exit 1
