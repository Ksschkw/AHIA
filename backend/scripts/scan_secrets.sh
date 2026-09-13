#!/usr/bin/env bash
#
# Secret scanning for the working tree and, on request, the full git history.
#
# The scanner is a required gate: if it is missing, this script fails rather
# than reporting success. "The tool was not installed" must never be
# distinguishable from "the tree is clean".
#
# Usage:
#   scripts/scan_secrets.sh                 scan the working tree
#   scripts/scan_secrets.sh --history       scan all commits in the repository
#   scripts/scan_secrets.sh --staged        scan staged content only
#
# Exit codes: 0 clean, 1 findings or missing scanner, 2 usage error.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly BACKEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly REPOSITORY_ROOT="$(cd -- "${BACKEND_DIR}/.." && pwd)"
readonly CONFIG_PATH="${REPOSITORY_ROOT}/.gitleaks.toml"
readonly WORKSPACE_GITLEAKS="${REPOSITORY_ROOT}/.tools/bin/gitleaks"

log() { printf '[INFO] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1" >&2; exit 1; }

scan_mode="working-tree"
for argument in "$@"; do
  case "${argument}" in
    --history) scan_mode="history" ;;
    --staged) scan_mode="staged" ;;
    -h|--help)
      grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed -E 's/^# ?//'
      exit 0
      ;;
    *) fail "unknown argument: ${argument}" ;;
  esac
done

resolve_scanner() {
  if [[ -x "${WORKSPACE_GITLEAKS}" ]]; then
    printf '%s' "${WORKSPACE_GITLEAKS}"
    return 0
  fi
  if command -v gitleaks >/dev/null 2>&1; then
    command -v gitleaks
    return 0
  fi
  fail "gitleaks is not installed; run scripts/install_workspace_tools.sh first"
}

[[ -f "${CONFIG_PATH}" ]] || fail "missing configuration: ${CONFIG_PATH}"

readonly GITLEAKS_BIN="$(resolve_scanner)"

log "scanner: ${GITLEAKS_BIN} ($("${GITLEAKS_BIN}" version))"
log "config: ${CONFIG_PATH}"

run_scan() {
  local mode="$1"
  shift
  local exit_code=0
  if [[ "${mode}" == "history" ]]; then
    log "scanning full git history in ${REPOSITORY_ROOT}"
    "${GITLEAKS_BIN}" git "${REPOSITORY_ROOT}" \
      --config "${CONFIG_PATH}" \
      --redact \
      --no-banner \
      --log-opts="--all" || exit_code=$?
  else
    log "scanning working tree in ${REPOSITORY_ROOT}"
    "${GITLEAKS_BIN}" dir "${REPOSITORY_ROOT}" \
      --config "${CONFIG_PATH}" \
      --redact \
      --no-banner || exit_code=$?
  fi
  return "${exit_code}"
}

case "${scan_mode}" in
  working-tree)
    if run_scan "working-tree"; then
      printf '[OK] secret scan: no findings in the working tree\n'
    else
      printf '[FAIL] secret scan: findings in the working tree\n' >&2
      printf '       rotate the credential first, then remove it from the tree\n' >&2
      printf '       and from history; a rewritten file does not un-leak a key\n' >&2
      exit 1
    fi
    ;;
  history)
    if run_scan "history"; then
      printf '[OK] secret scan: no findings in the repository history\n'
    else
      printf '[FAIL] secret scan: findings in the repository history\n' >&2
      exit 1
    fi
    ;;
  staged)
    # A pre-commit run only sees the staged snapshot; scanning the tree in that
    # context would report on files the developer has not staged yet.
    log "scanning staged changes"
    if "${GITLEAKS_BIN}" git "${REPOSITORY_ROOT}" \
      --config "${CONFIG_PATH}" \
      --redact \
      --no-banner \
      --staged; then
      printf '[OK] secret scan: no findings in staged changes\n'
    else
      printf '[FAIL] secret scan: findings in staged changes\n' >&2
      exit 1
    fi
    ;;
  *)
    fail "unreachable scan mode: ${scan_mode}"
    ;;
esac
