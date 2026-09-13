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
"${VENV_PIP_AUDIT}" \
  --requirement "${LOCKFILE}" \
  --progress-spinner off \
  --strict \
  "${ignore_arguments[@]}" || audit_exit_code=$?

if (( audit_exit_code == 0 )); then
  printf '[OK] dependency audit: no unignored vulnerabilities\n'
  exit 0
fi

printf '[FAIL] dependency audit: vulnerabilities found\n' >&2
printf '       fix by upgrading the package, or add a dated entry to\n' >&2
printf '       %s with a reason and a remediation plan\n' "${IGNORE_FILE}" >&2
exit 1
