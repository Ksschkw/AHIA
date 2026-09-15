#!/usr/bin/env bash
# A pip-audit that could not do its work: the shape of a network or index failure.
#
# The gate must call this what it is. Reporting "vulnerabilities found" for a run that never produced
# a report is how a real finding gets ignored the next time.
set -Eeuo pipefail
printf 'ERROR:pip_audit._cli:Failed to reach the index\n'
exit 2
