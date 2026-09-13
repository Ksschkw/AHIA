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
readonly REPOSITORY_ROOT="$(cd -- "${BACKEND_DIR}/.." && pwd)"
readonly VENV_DIR="${BACKEND_DIR}/.venv"
readonly LOCKFILE="${BACKEND_DIR}/requirements.lock"
readonly PRODUCTION_LOCKFILE="${BACKEND_DIR}/requirements.prod.lock"
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
  [[ -f "${PRODUCTION_LOCKFILE}" ]] || fail "missing lockfile: ${PRODUCTION_LOCKFILE}"
  log "lockfiles present: ${LOCKFILE}, ${PRODUCTION_LOCKFILE}"
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

if [[ "${mode}" == "relock" ]]; then
  log "re-resolving dependencies from ${PYPROJECT} and rewriting both lockfiles"

  # uv is the resolver. It is a development-only tool; it is installed here
  # unpinned on purpose because it is the thing that produces the pins, and it
  # is not part of the runtime or test dependency set.
  if [[ ! -x "${VENV_DIR}/bin/uv" ]]; then
    log "installing the resolver (uv)"
    python -m pip install --quiet uv
  fi

  # The resolver cache lives inside the repository because the default user
  # cache directory is not writable on this workstation.
  export UV_CACHE_DIR="${REPOSITORY_ROOT}/.tools/uv-cache"
  mkdir -p "${UV_CACHE_DIR}"

  # Two locks, because a production image must not ship the test toolchain:
  #   requirements.lock       full development closure (local, CI, audit)
  #   requirements.prod.lock  runtime closure only (container image, deploy)
  # Hashes are recorded so installation can run in --require-hashes mode.
  "${VENV_DIR}/bin/uv" pip compile "${PYPROJECT}" \
    --extra dev --python-version 3.12 --no-header --generate-hashes \
    --output-file "${LOCKFILE}"
  log "wrote ${LOCKFILE}"

  "${VENV_DIR}/bin/uv" pip compile "${PYPROJECT}" \
    --python-version 3.12 --no-header --generate-hashes \
    --output-file "${PRODUCTION_LOCKFILE}"
  log "wrote ${PRODUCTION_LOCKFILE}"
fi

[[ -f "${LOCKFILE}" ]] || fail "missing lockfile: ${LOCKFILE}; run with --relock"

log "installing pinned dependencies from ${LOCKFILE} (hashes enforced)"
python -m pip install --quiet --require-hashes --no-deps -r "${LOCKFILE}"
log "installing the project in editable mode without touching pins"
python -m pip install --quiet --no-deps --editable "${BACKEND_DIR}"

log "installed packages: $(python -m pip list --format=freeze --exclude-editable | wc -l)"
log "bootstrap complete"
