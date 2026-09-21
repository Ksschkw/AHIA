#!/usr/bin/env bash
#
# Remove the businesses the scaffold and its checks created.
#
# Every browser check signs up a business, because that is the only way to exercise sign-up, publishing and a
# sale. Run a few dozen times and the development database is mostly test shops - which makes it hard to see
# what is real and slow to look through.
#
# **What it deliberately keeps.** Anything whose name does not look like a generated one: `kosi-s-pot` is the
# product owner's own shop, and names like `saint-electronics` and `local-store` do not follow the pattern the
# checks produce, so they are left alone. Deleting a real business to tidy up a test database would be a very
# expensive mistake, and "it looked like a test" is not a good enough reason to make it.
#
# **A test business cannot be deleted, and that is the product working as designed.** Every business has events
# in `audit_events`, that table is append-only, and its trigger refuses:
#
#     ERROR: audit_events is append-only: record a compensating event instead
#
# So the foreign key from the trail will not let a tenant go, and this script does not pretend otherwise: it
# removes the **test lists** it can remove and reports the businesses it cannot. Disabling that trigger to tidy
# up would be destroying the one thing the product promises never to lose.
#
# To genuinely clear a **development** database, rebuild it - that is the sanctioned way, and it is destructive,
# so it is not done here:
#
#     dropdb ahia_dev && createdb ahia_dev && (cd backend && .venv/bin/alembic upgrade head)
#
# Usage:
#   bash scripts/clean_scaffold_test_data.sh            # show what would go
#   bash scripts/clean_scaffold_test_data.sh --apply    # remove the test lists
set -euo pipefail

DATABASE_URL="${AHIA_TEST_DATABASE_URL:-postgresql://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_dev}"

# The shapes the checks produce: a word, a dash, and a number. Names that do not match are kept.
TEST_NAME_PATTERN='^(alaba|mobile|obi|profile|photo|main|second|first|debug|nest|dispatch|link|work|probe|rate|publish-test|shelf|cart|page|team|pin|groups|paint|send|bench)-'

echo "Database: ${DATABASE_URL##*/}"
echo
echo "Keeping:"
psql "$DATABASE_URL" -tAc "select '  ' || slug || '  (' || name || ')' from tenants where slug !~ '${TEST_NAME_PATTERN}' order by slug"
echo
echo "To be removed:"
psql "$DATABASE_URL" -tAc "select '  ' || slug from tenants where slug ~ '${TEST_NAME_PATTERN}' order by slug" | head -40
echo "  ... and $(psql "$DATABASE_URL" -tAc "select count(*) from tenants where slug ~ '${TEST_NAME_PATTERN}'") in total."
echo
# The lists my probes sent to the product owner's own shop, recognised by the numbers invented for testing -
# the same number the codebase's own docstrings use as their example.
echo "Test lists on a real shop (by the numbers used only in tests):"
psql "$DATABASE_URL" -tAc "select '  ' || customer_phone || '  ' || status || '  ' || created_at::date from requests where customer_phone in ('+2348031234567', '+2348029876543', '+2348039998877') order by created_at desc limit 20"

if [[ "${1:-}" != "--apply" ]]; then
  echo
  echo "Nothing was changed. Run again with --apply."
  exit 0
fi

psql "$DATABASE_URL" <<SQL
begin;
delete from requests where customer_phone in ('+2348031234567', '+2348029876543', '+2348039998877');
delete from tenants where slug ~ '${TEST_NAME_PATTERN}';
commit;
SQL

echo
echo "Left: $(psql "$DATABASE_URL" -tAc "select count(*) from tenants") business(es)."
