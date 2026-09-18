#!/usr/bin/env bash
#
# Set every GitHub secret and variable the deployment workflows need, from one local file.
#
#   bash backend/scripts/configure_deployment.sh
#
# Why a script rather than a list of click-by-click instructions: a secret typed into a dashboard is a
# secret that gets typed differently the second time, and rotating one by hand is the step people skip.
# This is idempotent, so rotating is running it again.
#
# It reads backend/.env.deploy, which is gitignored and holds real values. It never prints a secret
# value - only the name of the thing it set - because a script that echoes secrets ends up in somebody's
# terminal scrollback and then in a screenshot.
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VALUES_FILE="${REPOSITORY_ROOT}/backend/.env.deploy"

say() { printf '[OK] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1" >&2; exit 1; }

command -v gh >/dev/null 2>&1 || fail "the GitHub CLI (gh) is not installed"

if ! gh auth status >/dev/null 2>&1; then
  fail "gh is not signed in. Run: gh auth login --scopes repo,write:packages"
fi

if [[ ! -f "${VALUES_FILE}" ]]; then
  warn "${VALUES_FILE} does not exist."
  cat <<'GUIDE'
Create it with these five values, then run this script again:

  DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST/DATABASE
  JWT_SECRET=<openssl rand -hex 32>
  CLOUDINARY_CLOUD_NAME=...
  CLOUDINARY_API_KEY=...
  CLOUDINARY_API_SECRET=...

The database URL must be the asyncpg one and must not carry ?sslmode=require.
GUIDE
  exit 1
fi

# Read the file without exporting it into this shell's environment, and without printing values.
# The values file is a copy of .env, which carries inline comments and sometimes quotes. Pushing
# "postgresql://... # local dev only" into a production secret is the kind of mistake that looks like a
# database outage, so the value is unwrapped here: everything after a " #" is a comment, and a value
# wrapped in quotes loses them.
value_of() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" "${VALUES_FILE}" | tail -1 || true)"
  local value="${line#*=}"
  value="${value%%[[:space:]]#*}"
  value="${value%"${value##*[![:space:]]}"}"
  if [[ "${value}" == \"*\" || "${value}" == \'*\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "${value}"
}

require_value() {
  local key="$1"
  local value
  value="$(value_of "${key}")"
  if [[ -z "${value}" ]]; then
    fail "${key} is missing from ${VALUES_FILE}"
  fi
  if [[ "${value}" == *"?"*"sslmode"* ]]; then
    fail "${key} carries ?sslmode=..., which this driver rejects. Use DATABASE_REQUIRE_SSL instead."
  fi
  printf '%s' "${value}"
}

# ---------------------------------------------------------------------------
# Secrets: values only this environment should see.
# ---------------------------------------------------------------------------
set_secret() {
  local name="$1"
  local value="$2"
  printf '%s' "${value}" | gh secret set "${name}" >/dev/null
  say "secret ${name}"
}

set_secret DATABASE_URL "$(require_value DATABASE_URL)"
set_secret JWT_SECRET "$(require_value JWT_SECRET)"
# The pepper signs refresh tokens. Required in every environment except development, and the one
# value that is easy to leave out because nothing needs it until somebody signs in twice.
set_secret REFRESH_TOKEN_PEPPER "$(require_value REFRESH_TOKEN_PEPPER)"
set_secret CLOUDINARY_CLOUD_NAME "$(require_value CLOUDINARY_CLOUD_NAME)"
set_secret CLOUDINARY_API_KEY "$(require_value CLOUDINARY_API_KEY)"
set_secret CLOUDINARY_API_SECRET "$(require_value CLOUDINARY_API_SECRET)"

# The API token is optional at this point: the pipeline prints what to do until it exists rather than
# failing a deployment that was never configured.
if [[ -n "$(value_of NORTHFLANK_API_TOKEN)" ]]; then
  set_secret NORTHFLANK_API_TOKEN "$(value_of NORTHFLANK_API_TOKEN)"
else
  warn "NORTHFLANK_API_TOKEN not set yet; the deploy workflow will print its instructions instead"
fi

# ---------------------------------------------------------------------------
# Variables: identifiers that are not secret and are handy to read in a log.
# ---------------------------------------------------------------------------
set_variable() {
  local name="$1"
  gh variable set "${name}" --body "$2" >/dev/null
  say "variable ${name}"
}

set_variable APP_ENV production
set_variable DATABASE_REQUIRE_SSL true
set_variable PHONE_COUNTRY_CODE +234
set_variable STORAGE_PROVIDER cloudinary
set_variable FEATURE_MEDIA_UPLOAD true
set_variable FEATURE_STOREFRONT_PUBLIC_PUBLISHING true

for optional in NORTHFLANK_PROJECT_ID NORTHFLANK_SERVICE_ID NORTHFLANK_JOB_ID; do
  if [[ -n "$(value_of "${optional}")" ]]; then
    set_variable "${optional}" "$(value_of "${optional}")"
  else
    warn "${optional} not set yet; automatic deployment pinning stays off"
  fi
done

say "done. Secrets live in GitHub now; nothing else needs typing into a dashboard."
printf '\nStill to paste into Northflank once, by hand, in the service environment:\n'
printf '  APP_ENV, DATABASE_URL, DATABASE_REQUIRE_SSL, JWT_SECRET, PHONE_COUNTRY_CODE,\n'
printf '  CORS_ALLOWED_ORIGINS, STORAGE_PROVIDER, CLOUDINARY_*, FEATURE_*\n'
printf '\nSee docs/DEPLOYMENT.md section 1.3.\n'
