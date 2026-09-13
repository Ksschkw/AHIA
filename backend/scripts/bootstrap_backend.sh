#!/usr/bin/env bash
#
# Create (or refresh) the backend virtual environment and install the pinned
# dependency set.
#
# Design rules:
#   * idempotent - safe to re-run at any time
#   * no network access beyond the package index, no system-level install
#   * the lockfile is the pin; the lockfile is only regenerated on request
#   * failure is loud: any failed step exits non-zero and stops
#
# Usage:
#   scripts/bootstrap_backend.sh            install from requirements.lock
#   scripts/bootstrap_backend.sh --relock   re-resolve from pyproject and
#                                           rewrite requirements.lock
#   scripts/bootstrap_backend.sh --verify   fail if the lockfile is missing

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly BACKEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly VENV_DIR="${BACKEND_DIR}/.venv"
readonly LOCKFILE="${BACKEND_DIR}/requirements.lock"
readonly PYPROJECT="${BACKEND_DIR}/pyproject.toml"

mode="install"

for argument in "$@"; do
  case "${argument}" in
    --relock) mode="relock" ;;
    --verify) mode="verify" ;;
    -h|--help)
      grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed -E 's/^# ?//'
      exit 0
      ;;
    *)
      echo "[FAIL] unknown argument: ${argument}" >&2
      exit 2
      ;;
  esac
done

log() {
  printf '[INFO] %s\n' "$1"
}

fail() {
  printf '[FAIL] %s\n' "$1" >&2
  exit 1
}

require_python() {
  local candidate
  for candidate in python3.12 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      local version
      version="$("${candidate}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
      if [[ "${version}" == "3.12" ]]; then
        printf '%s\n' "${candidate}"
        return 0
      fi
    fi
  done
  fail "Python 3.12 is required and was not found on PATH"
}

readonly PYTHON_BIN="$(require_python)"

if [[ "${mode}" == "verify" ]]; then
  [[ -f "${LOCKFILE}" ]] || fail "missing lockfile: ${LOCKFILE}"
  log "lockfile present: ${LOCKFILE}"
  exit 0
fi

log "interpreter: ${PYTHON_BIN} ($("${PYTHON_BIN}" --version 2>&1))"
log "backend directory: ${BACKEND_DIR}"

if [[ ! -d "${VENV_DIR}" ]]; then
  log "creating virtual environment at ${VENV_DIR}"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
else
  log "reusing existing virtual environment at ${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

log "upgrading pip, setuptools and wheel"
python -m pip install --quiet --upgrade pip setuptools wheel

if [[ -f "${LOCKFILE}" && "${mode}" != "relock" ]]; then
  log "installing pinned dependencies from ${LOCKFILE}"
  python -m pip install --quiet --require-hashes=false --no-deps -r "${LOCKFILE}"
  log "installing the project in editable mode without touching pins"
  python -m pip install --quiet --no-deps --editable "${BACKEND_DIR}"
else
  if [[ "${mode}" == "relock" ]]; then
    log "re-resolving dependencies from ${PYPROJECT} (this rewrites the lockfile)"
  else
    log "no lockfile found; resolving from ${PYPROJECT} and writing one"
  fi
  python -m pip install --quiet --editable "${BACKEND_DIR}[dev]"
  python -m pip freeze --exclude-editable > "${LOCKFILE}"
  log "wrote ${LOCKFILE}"
fi

log "installed packages: $(python -m pip list --format=freeze --exclude-editable | wc -l)"
log "bootstrap complete"
