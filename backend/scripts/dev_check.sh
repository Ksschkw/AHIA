#!/usr/bin/env bash
#
# The single build gate.
#
# Runs every check in a fixed order, prints a plain-ASCII summary and returns a
# non-zero exit code if anything failed. CI runs this exact script, so a green
# local run and a green pipeline mean the same thing.
#
# Order matters: cheap and structural checks run before the slow ones, so the
# common failure is reported in seconds rather than after the test suite.
#
# Usage:
#   scripts/dev_check.sh                 run every gate
#   scripts/dev_check.sh --skip-audit    skip the dependency audit (needs network)
#   scripts/dev_check.sh --help
#
# Exit codes: 0 all gates passed, 1 at least one gate failed, 2 usage error.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly BACKEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly REPOSITORY_ROOT="$(cd -- "${BACKEND_DIR}/.." && pwd)"
readonly VENV_BIN_DIR="${BACKEND_DIR}/.venv/bin"

skip_audit=false
for argument in "$@"; do
  case "${argument}" in
    --skip-audit) skip_audit=true ;;
    -h|--help)
      grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed -E 's/^# ?//'
      exit 0
      ;;
    *) printf '[FAIL] unknown argument: %s\n' "${argument}" >&2; exit 2 ;;
  esac
done

if [[ ! -x "${VENV_BIN_DIR}/python" ]]; then
  printf '[FAIL] backend virtual environment is missing; run: make setup\n' >&2
  exit 1
fi

gate_names=()
gate_results=()
gate_seconds=()
failed_gates=0
skipped_gates=0

record() {
  local name="$1"
  local result="$2"
  local seconds="$3"
  gate_names+=("${name}")
  gate_results+=("${result}")
  gate_seconds+=("${seconds}")
  # Only a failure makes the build red. A SKIP is a gate the caller deliberately
  # did not run: check-fast skips the dependency audit because it needs network
  # access. Counting a skip as a failure made the documented offline command end
  # in a red summary on a healthy tree, which teaches people to ignore the
  # summary - the opposite of what a gate is for.
  case "${result}" in
    OK) ;;
    SKIP) skipped_gates=$((skipped_gates + 1)) ;;
    *) failed_gates=$((failed_gates + 1)) ;;
  esac
}

run_gate() {
  local name="$1"
  shift
  printf '\n[GATE] %s\n' "${name}"
  printf '%s\n' '------------------------------------------------------------------------'
  local started_at
  started_at="$(date +%s)"
  local result="OK"
  if ! "$@"; then
    result="FAIL"
  fi
  local finished_at
  finished_at="$(date +%s)"
  record "${name}" "${result}" "$((finished_at - started_at))"
  printf '[%s] %s (%ss)\n' "${result}" "${name}" "$((finished_at - started_at))"
}

run_gate "format-check" bash -c "cd '${BACKEND_DIR}' && '${VENV_BIN_DIR}/ruff' format --check ."
run_gate "lint" bash -c "cd '${BACKEND_DIR}' && '${VENV_BIN_DIR}/ruff' check ."
run_gate "type-check" bash -c "cd '${BACKEND_DIR}' && '${VENV_BIN_DIR}/mypy'"
run_gate "ascii-guard" "${VENV_BIN_DIR}/python" "${BACKEND_DIR}/scripts/check_ascii.py"
run_gate "banned-names" "${VENV_BIN_DIR}/python" "${BACKEND_DIR}/scripts/check_banned_names.py"
run_gate "tests" bash -c "cd '${BACKEND_DIR}' && '${VENV_BIN_DIR}/pytest'"
run_gate "architecture" bash -c "cd '${BACKEND_DIR}' && '${VENV_BIN_DIR}/lint-imports' --config import-linter.ini --no-cache"
run_gate "secret-scan" bash "${BACKEND_DIR}/scripts/scan_secrets.sh"

if [[ "${skip_audit}" == "true" ]]; then
  record "dependency-audit" "SKIP" "0"
else
  run_gate "dependency-audit" bash "${BACKEND_DIR}/scripts/audit_dependencies.sh"
fi

printf '\n========================================================================\n'
printf 'BUILD GATE SUMMARY\n'
printf '========================================================================\n'
for index in "${!gate_names[@]}"; do
  printf '[%-4s] %-18s %ss\n' "${gate_results[${index}]}" "${gate_names[${index}]}" "${gate_seconds[${index}]}"
done
printf '%s\n' '------------------------------------------------------------------------'

if (( failed_gates > 0 )); then
  printf '[FAIL] %d gate(s) failed. The build is red.\n' "${failed_gates}"
  exit 1
fi

if (( skipped_gates > 0 )); then
  # Naming what did not run matters: a green summary that quietly omits a gate
  # would read as "everything was checked".
  printf '[OK] all gates passed (%d skipped)\n' "${skipped_gates}"
  exit 0
fi

printf '[OK] all gates passed\n'
