#!/usr/bin/env bash
#
# Install the repository's pre-commit hooks into .git/hooks.
#
# Why a script rather than a documented command: PRE_COMMIT_HOME must be
# redirected into the workspace, because the default user cache directory is not
# writable here and pre-commit would fail on its first run with a confusing
# error. Redirecting it also keeps every downloaded hook environment inside the
# repository, which makes the cache removable and auditable.
#
# Idempotent: re-running reinstalls and reports the current state.
#
# Usage:
#   scripts/install_git_hooks.sh
#   scripts/install_git_hooks.sh --run-all     also run the hooks over the tree
#
# Exit codes: 0 success, 1 failure, 2 usage error.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly BACKEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly REPOSITORY_ROOT="$(cd -- "${BACKEND_DIR}/.." && pwd)"
readonly CONFIG_PATH="${BACKEND_DIR}/.pre-commit-config.yaml"
readonly PRE_COMMIT_BIN="${BACKEND_DIR}/.venv/bin/pre-commit"

export PRE_COMMIT_HOME="${REPOSITORY_ROOT}/.tools/pre-commit"

log() { printf '[INFO] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1" >&2; exit 1; }

run_all=false
for argument in "$@"; do
  case "${argument}" in
    --run-all) run_all=true ;;
    -h|--help)
      grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed -E 's/^# ?//'
      exit 0
      ;;
    *) fail "unknown argument: ${argument}" ;;
  esac
done

[[ -x "${PRE_COMMIT_BIN}" ]] || fail "pre-commit is not installed; run scripts/bootstrap_backend.sh first"
[[ -f "${CONFIG_PATH}" ]] || fail "missing configuration: ${CONFIG_PATH}"

mkdir -p "${PRE_COMMIT_HOME}"
log "hook environment cache: ${PRE_COMMIT_HOME}"

log "validating ${CONFIG_PATH}"
"${PRE_COMMIT_BIN}" validate-config "${CONFIG_PATH}"

log "installing hooks into ${REPOSITORY_ROOT}/.git/hooks"
"${PRE_COMMIT_BIN}" install \
  --config "${CONFIG_PATH}" \
  --install-hooks \
  --hook-type pre-commit

if [[ "${run_all}" == "true" ]]; then
  log "running every hook over the whole tree"
  "${PRE_COMMIT_BIN}" run \
    --config "${CONFIG_PATH}" \
    --all-files \
    --show-diff-on-failure
fi

printf '[OK] git hooks installed and verified\n'
