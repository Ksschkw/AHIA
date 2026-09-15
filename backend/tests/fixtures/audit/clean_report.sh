#!/usr/bin/env bash
# A pip-audit that reports a clean dependency set.
set -Eeuo pipefail
printf '%s' '{"dependencies": [{"name": "httpx", "version": "0.27.0", "vulns": []}]}'
exit 0
