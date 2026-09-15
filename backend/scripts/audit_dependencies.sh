#!/usr/bin/env bash
#
# Dependency vulnerability audit.
#
# Policy (scaffold specification and docs/PREREQUISITES.md):
#   * the audit runs as part of the ordinary check command, not only in CI
#   * a finding fails the build unless it is listed in the ignore file
#   * every ignore entry carries a date and a reason and expires automatically,
#     because a permanent ignore is just an unaudited dependency
#
# Ignore file format, one entry per line:
#     <VULNERABILITY-ID> <YYYY-MM-DD> <reason>
# Lines starting with # and blank lines are ignored.
#
# Usage:
#   scripts/audit_dependencies.sh
#   scripts/audit_dependencies.sh --help
#
# Exit codes: 0 clean, 1 findings or expired ignores, 2 usage error.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly BACKEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly VENV_PIP_AUDIT="${BACKEND_DIR}/.venv/bin/pip-audit"
readonly VENV_PYTHON="${BACKEND_DIR}/.venv/bin/python"
readonly LOCKFILE="${BACKEND_DIR}/requirements.lock"
readonly IGNORE_FILE="${BACKEND_DIR}/dependency_audit_ignores.txt"
readonly IGNORE_MAX_AGE_DAYS=90

log() { printf '[INFO] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1" >&2; exit 1; }

for argument in "$@"; do
  case "${argument}" in
    -h|--help)
      grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed -E 's/^# ?//'
      exit 0
      ;;
    *) fail "unknown argument: ${argument}" ;;
  esac
done

[[ -x "${VENV_PIP_AUDIT}" ]] || fail "pip-audit is not installed; run scripts/bootstrap_backend.sh first"
[[ -f "${LOCKFILE}" ]] || fail "missing lockfile: ${LOCKFILE}"

current_epoch="$(date -u +%s)"
ignore_arguments=()

if [[ -f "${IGNORE_FILE}" ]]; then
  while IFS= read -r line; do
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    read -r vulnerability_id ignore_date reason <<<"${line}"
    if [[ -z "${vulnerability_id:-}" || -z "${ignore_date:-}" || -z "${reason:-}" ]]; then
      fail "malformed ignore entry in ${IGNORE_FILE}: ${line}"
    fi
    if ! ignore_epoch="$(date -u -d "${ignore_date}" +%s 2>/dev/null)"; then
      fail "unparseable date in ${IGNORE_FILE}: ${ignore_date}"
    fi
    age_days=$(( (current_epoch - ignore_epoch) / 86400 ))
    if (( age_days > IGNORE_MAX_AGE_DAYS )); then
      fail "ignore entry ${vulnerability_id} added ${ignore_date} is ${age_days} days old (limit ${IGNORE_MAX_AGE_DAYS}); re-review or remediate"
    fi
    log "ignoring ${vulnerability_id} (added ${ignore_date}, justified: ${reason})"
    ignore_arguments+=(--ignore-vuln "${vulnerability_id}")
  done <"${IGNORE_FILE}"
fi

log "auditing $(wc -l <"${LOCKFILE}") pinned distributions from ${LOCKFILE}"

audit_exit_code=0
audit_output="$("${VENV_PIP_AUDIT}" \
  --requirement "${LOCKFILE}" \
  --progress-spinner off \
  --strict \
  --format json \
  "${ignore_arguments[@]}" 2>&1)" || audit_exit_code=$?

if (( audit_exit_code == 0 )); then
  printf '[OK] dependency audit: no unignored vulnerabilities\n'
  exit 0
fi

# A finding and a tooling failure are both red builds, and they are not the same thing. Reporting
# "vulnerabilities found" when pip-audit could not reach the index or build a temporary venv sends
# somebody hunting for a vulnerability that does not exist, which is how a real finding gets
# ignored the next time. The verdict is read from the report itself: a vulnerability is a
# dependency entry with a non-empty `vulns` list.
audit_verdict="$(printf '%s' "${audit_output}" | "${VENV_PYTHON}" -c '
import json
import sys

try:
    report = json.load(sys.stdin)
except ValueError:
    print("tooling")
else:
    dependencies = report.get("dependencies", [])
    print("findings" if any(entry.get("vulns") for entry in dependencies) else "tooling")
' 2>/dev/null || printf 'tooling')"

if [[ "${audit_verdict}" == "findings" ]]; then
  printf '[FAIL] dependency audit: vulnerabilities found\n' >&2
  printf '       fix by upgrading the package, or add a dated entry to\n' >&2
  printf '       %s with a reason and a remediation plan\n' "${IGNORE_FILE}" >&2
  printf '%s\n' "${audit_output}" | tail -40 >&2
  exit 1
fi

printf '[FAIL] dependency audit: the audit could not complete\n' >&2
printf '       pip-audit exited %s without reporting a dependency set, so nothing was verified.\n' \
  "${audit_exit_code}" >&2
printf '       This is an environment failure (network, index, or a temporary build), not a finding.\n' >&2
printf '       Re-run: bash %s/scripts/audit_dependencies.sh\n' "${BACKEND_DIR}" >&2
printf '%s\n' "${audit_output}" | tail -20 >&2
exit 1
