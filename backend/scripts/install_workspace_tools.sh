#!/usr/bin/env bash
#
# Install the workspace-scoped developer binaries used by the build gate.
#
# Why not a system package: this workstation's system paths (/usr/local/bin,
# ~/.local/bin) are read-only for the project, and container parity matters.
# Tools therefore live in <repository>/.tools/bin, which is gitignored.
#
# Supply-chain rules:
#   * every tool version is pinned here, never "latest"
#   * every artifact is verified against a pinned SHA-256 before it is used
#   * a platform whose checksum is not pinned fails loudly instead of
#     installing something unverified
#
# Usage:
#   scripts/install_workspace_tools.sh            install everything
#   scripts/install_workspace_tools.sh gitleaks   install one tool
#
# Exit codes: 0 success, 1 failure, 2 usage error.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly BACKEND_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly REPOSITORY_ROOT="$(cd -- "${BACKEND_DIR}/.." && pwd)"
readonly TOOLS_DIR="${REPOSITORY_ROOT}/.tools"
readonly TOOLS_BIN_DIR="${TOOLS_DIR}/bin"
readonly DOWNLOAD_DIR="${TOOLS_DIR}/tmp"

readonly GITLEAKS_VERSION="8.30.1"

log() { printf '[INFO] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1" >&2; exit 1; }

platform_key() {
  local machine
  machine="$(uname -m)"
  local system
  system="$(uname -s)"
  case "${system}-${machine}" in
    Linux-x86_64) printf 'linux_x64' ;;
    Linux-aarch64|Linux-arm64) printf 'linux_arm64' ;;
    Darwin-x86_64) printf 'darwin_x64' ;;
    Darwin-arm64) printf 'darwin_arm64' ;;
    *) printf 'unsupported' ;;
  esac
}

pinned_checksum_for() {
  local tool="$1"
  local platform="$2"
  case "${tool}:${platform}" in
    gitleaks:linux_x64) printf '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb' ;;
    *)
      fail "no pinned checksum for ${tool} on ${platform}; add one before installing"
      ;;
  esac
}

download() {
  local url="$1"
  local destination="$2"
  if ! curl --fail --silent --show-error --location --retry 3 --output "${destination}" "${url}"; then
    fail "download failed: ${url}"
  fi
}

verify_checksum() {
  local file="$1"
  local expected="$2"
  local actual
  actual="$(sha256sum "${file}" | awk '{print $1}')"
  if [[ "${actual}" != "${expected}" ]]; then
    fail "checksum mismatch for $(basename "${file}"): expected ${expected}, got ${actual}"
  fi
  log "checksum verified: $(basename "${file}")"
}

install_gitleaks() {
  local platform
  platform="$(platform_key)"
  [[ "${platform}" != "unsupported" ]] || fail "unsupported platform for gitleaks"

  if [[ -x "${TOOLS_BIN_DIR}/gitleaks" ]]; then
    local installed_version
    installed_version="$("${TOOLS_BIN_DIR}/gitleaks" version 2>/dev/null || true)"
    if [[ "${installed_version}" == "${GITLEAKS_VERSION}" ]]; then
      log "gitleaks ${GITLEAKS_VERSION} already installed"
      return 0
    fi
  fi

  mkdir -p "${TOOLS_BIN_DIR}" "${DOWNLOAD_DIR}"

  local archive_name="gitleaks_${GITLEAKS_VERSION}_${platform}.tar.gz"
  local url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${archive_name}"
  local checksum
  checksum="$(pinned_checksum_for gitleaks "${platform}")"

  log "downloading ${archive_name}"
  download "${url}" "${DOWNLOAD_DIR}/${archive_name}"
  verify_checksum "${DOWNLOAD_DIR}/${archive_name}" "${checksum}"

  tar --extract --gzip --file "${DOWNLOAD_DIR}/${archive_name}" --directory "${DOWNLOAD_DIR}"
  install --mode 0755 "${DOWNLOAD_DIR}/gitleaks" "${TOOLS_BIN_DIR}/gitleaks"
  rm -f "${DOWNLOAD_DIR}/${archive_name}" "${DOWNLOAD_DIR}/gitleaks" "${DOWNLOAD_DIR}/LICENSE" \
    "${DOWNLOAD_DIR}/README.md" 2>/dev/null || true

  log "installed gitleaks $("${TOOLS_BIN_DIR}/gitleaks" version) at ${TOOLS_BIN_DIR}/gitleaks"
}

main() {
  local requested_tools=("$@")
  if [[ ${#requested_tools[@]} -eq 0 ]]; then
    requested_tools=(gitleaks)
  fi
  for tool in "${requested_tools[@]}"; do
    case "${tool}" in
      gitleaks) install_gitleaks ;;
      *) fail "unknown tool: ${tool}" ;;
    esac
  done
  log "workspace tools ready in ${TOOLS_BIN_DIR}"
}

main "$@"
