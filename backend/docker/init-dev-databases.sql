-- Development database bootstrap for the compose PostgreSQL service.
--
-- The service creates ahia_dev from POSTGRES_DB. Tests must never be able to
-- truncate development data, so the test database is created separately here.
--
-- This file runs once, on first initialisation of an empty data directory. It
-- is not a migration and is never used outside local development.

CREATE DATABASE ahia_test OWNER ahia;
