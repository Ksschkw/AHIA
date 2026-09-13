# AHIA - Prerequisites, Accounts and Environment Variable Contract

Status: living document
Owners: engineering
Applies to: backend (Python/FastAPI), web (Next.js), mobile (React Native/Expo)
Last environment audit: this repository, local Linux Mint 22.3 workstation

This document answers one question: what must exist before implementation work
can start, and what exactly must be in the environment for the system to run.

Two rules govern everything below.

1. Secrets are supplied through environment variables or a secrets manager.
   They are never committed, never placed in `.env.example`, never logged, and
   never returned in an error response.
2. `.env` files are gitignored. `.env.example` contains placeholder names only.

Naming convention: engineering artifacts in this repository are ASCII-only, so
the product name is written `AHIA` in source, comments, logs, identifiers and
commit messages. The display form `AHIA` (with the dotted capital I) is a
user-facing string and is allowed in runtime business data, seed content and
product copy. See `TASKS.md` milestone M0.4 for the lint rule that enforces the
ASCII rule for engineering artifacts only.

---

## 1. Local workstation toolchain

### 1.1 Required for any backend work

| Tool | Version floor | Why | Verified locally |
|---|---|---|---|
| Git | 2.34 | version control, pre-commit hooks | yes |
| Python | 3.12 | backend runtime, matches container image | 3.12.3 |
| Python venv module | bundled with CPython | isolated dependency install | yes |
| pip | 24.x | dependency installation | yes |
| PostgreSQL server | 16 | authoritative transactional store; development must not use SQLite | 16.14 running on 127.0.0.1:5432 |
| PostgreSQL client (`psql`) | 16 | database inspection, migration verification | yes |
| Docker Engine | 24+ | container image build and parity checks | 29.1.3 |
| Make | 4.x | the single reproducible developer command | yes |

No Redis is required. No local AI model is required. No paid external service is
required to run the core backend, its migrations or its test suite.

### 1.2 Required later, per milestone

| Tool | Version floor | Needed from | Why |
|---|---|---|---|
| Node.js | 20 LTS or 22 LTS | M18 (web), M19 (mobile) | Next.js and Expo toolchains |
| pnpm | 9 | M18, M19 | web/mobile package manager with a committed lockfile |
| Expo CLI (via `npx expo`) | SDK 51+ | M19 | React Native development and device builds |
| EAS CLI | latest | M19 | store builds and OTA updates |
| AWS CLI (optional) | v2 | M7 | manual R2 bucket inspection using the S3-compatible API |
| `gitleaks` | 8.x | M0 | secret scanning; installed into the workspace, see 2.4 |
| `pip-audit` | 2.x | M0 | dependency vulnerability scanning |
| `import-linter` | 2.x | M0 | layered dependency enforcement |

### 1.3 Python dependency strategy

The backend uses `src/` layout with the package installed in editable mode so
tests import the installed package rather than accidentally importing files from
the working directory.

Lockfile policy: exact pins for every runtime and development dependency are
committed, with SHA-256 hashes recorded so installation runs in
`--require-hashes` mode and a tampered artifact fails the install rather than
being silently accepted. The pin sets are produced by a resolver (`uv`, a
development-only tool), never by hand, and are refreshed only by the explicit
`bootstrap_backend.sh --relock` command, never silently by an unpinned install
in CI.

Two lockfiles exist because the container image must not ship the test
toolchain:

| File | Closure | Consumed by |
|---|---|---|
| `backend/requirements.lock` | runtime plus development tools | local development, CI, the vulnerability audit |
| `backend/requirements.prod.lock` | runtime only, no pytest/ruff/mypy/uv | the container image and deployed environments |

Both are generated from `backend/pyproject.toml` in the same command, so they
cannot drift from each other.

Local runtime is a project-local virtual environment at `backend/.venv`.
Nothing is installed into the system interpreter and nothing is installed
outside the repository, because the workstation's system paths are not writable
for this project and container/CI parity matters more than convenience.

---

## 2. Accounts and external services

Each item states what it is needed for, which milestone first needs it, and what
credential material it produces. Items marked "required" block their milestone.

### 2.1 GitHub - required from M0

- Repository: `https://github.com/Ksschkw/AHIA.git`
- Why: source of truth, CI for lint/architecture/secret scan/tests.
- Credential: already-configured push access for the working copy, or a
  fine-grained personal access token with `contents: write` for automated
  pushes.
- Produces: no environment variables for the application itself.

### 2.2 Neon PostgreSQL - required from M0 for staging/production, optional for local work

- Why: managed PostgreSQL for the deployed API. Local development and tests use
  a local PostgreSQL 16 server instead.
- Provision: create a Neon project, one database per environment
  (`ahia_staging`, `ahia_production`), and a role that is not the project owner
  where provider permissions allow.
- Credential: a pooled connection string and a direct connection string.
  The application uses a single `DATABASE_URL`; migrations should use a direct
  (non-pooled) connection.
- Produces: `DATABASE_URL`, `DATABASE_REQUIRE_SSL=true` in deployed
  environments.
- Least privilege note: the application role must not be able to drop tables or
  alter schema in production. Alembic runs with a separate migration role.

### 2.3 Object storage: Cloudflare R2 (default) and Cloudinary (supported) - required from M1/M9

- Why: product images, store logos and banners, receipt images, generated
  invoices, reports and shipment documents. PostgreSQL stores metadata and
  storage keys only; it never stores binaries.
- Both providers are implemented behind one provider-neutral port and are
  selected with `STORAGE_PROVIDER`. The inactive provider's credentials are not
  required.
- R2 provisioning: create a bucket per environment (`ahia-dev`, `ahia-staging`,
  `ahia-production`), create an R2 API token scoped to that bucket with object
  read/write, and decide whether the bucket is served through a custom domain.
- R2 credential: account ID, S3-compatible endpoint
  `https://<account_id>.r2.cloudflarestorage.com`, access key ID, secret access
  key, bucket name.
- Cloudinary provisioning: one cloud per environment, an API key and secret
  from the console, and a decision on whether delivery is restricted.
- Cloudinary credential: cloud name, API key, API secret.
- Rotation: R2 tokens rotate by creating a second token, deploying it, then
  revoking the first. Cloudinary keys rotate the same way. Both are documented
  rotation paths with no downtime.
- Cost note: neither free tier is a hard billing cap. AHIA enforces its own
  upload limits and per-tenant quota; see section 3.5.

### 2.4 Northflank - required from M17

- Why: initial container hosting for the FastAPI service.
- Provision: a project, one service per environment, the container registry
  credentials if using a private image, and a health check pointed at `/health`.
- Credential: platform API token only if deployment is automated from CI.
- Produces: no application environment variables beyond those already listed;
  the platform injects `PORT`.

### 2.5 Vercel or equivalent - required from M18

- Why: managed hosting for the Next.js web application and public storefronts.
- Credential: platform token for automated deploys.
- Produces: web-side variables, see section 4.

### 2.6 Expo / EAS - required from M19

- Why: React Native trader application builds and distribution.
- Credential: Expo account, EAS project ID, Apple and Google store credentials
  at release time.
- Produces: mobile-side variables, see section 4.

### 2.7 Optional, later milestones only

| Service | Needed for | Milestone |
|---|---|---|
| Sentry or equivalent | error tracking beyond structured logs | M17 |
| OpenRouter or another LLM provider | AI insights, demand forecasting | after M15, flag-gated off |
| Paystack / Flutterwave | optional payment adapters | after M10, adapters only |
| Termii / Africa's Talking | SMS notifications | after M15 |
| SMTP provider | email notifications and password reset mail | after M3 |
| Domain registrar | `ahia.app` and the storefront public URLs | M14 |

None of these are on the critical path. Core sales, inventory, storefront and
authorization must keep working when every one of them is unavailable.

---

## 3. Backend environment variable contract

Every variable the backend reads is declared here and read in exactly one place,
`backend/src/ahia/core/config.py`. No other module may call `os.getenv`.

Legend: R = required in all environments, D = has a safe default,
S = secret (never logged, never committed).

### 3.1 Application

| Variable | Req | Default | Notes |
|---|---|---|---|
| `APP_ENV` | R | `development` | one of `development`, `test`, `production` |
| `APP_NAME` | D | `AHIA` | used in logs, docs and health payloads |
| `APP_VERSION` | D | `0.1.0` | reported by `/health` |
| `API_V1_PREFIX` | D | `/api/v1` | route namespace |
| `LOG_LEVEL` | D | `INFO` | `DEBUG` only in development |
| `LOG_FORMAT` | D | `json` | `console` is allowed in development only |
| `CORRELATION_ID_HEADER` | D | `X-Correlation-ID` | inbound and outbound header name |
| `TRUSTED_PROXY_COUNT` | D | `0` | how many proxies may set client IP headers |

### 3.2 Database

| Variable | Req | Default | Notes |
|---|---|---|---|
| `DATABASE_URL` | R | none (local dev value in `.env`) | must use the `postgresql+asyncpg://` driver |
| `DATABASE_MIGRATION_URL` | D | falls back to `DATABASE_URL` | direct, non-pooled connection for Alembic |
| `DATABASE_REQUIRE_SSL` | D | `false` locally, `true` when deployed | TLS is never disabled in production |
| `DATABASE_POOL_SIZE` | D | `5` | bulkhead per process |
| `DATABASE_MAX_OVERFLOW` | D | `5` | burst allowance |
| `DATABASE_POOL_TIMEOUT_SECONDS` | D | `10` | bounded wait for a connection |
| `DATABASE_STATEMENT_TIMEOUT_MS` | D | `15000` | server-side statement timeout |

### 3.3 Authentication and sessions

| Variable | Req | Default | Notes |
|---|---|---|---|
| `JWT_SECRET` | R | none | S; at least 32 bytes of entropy |
| `JWT_ALGORITHM` | D | `HS256` | never `none` |
| `JWT_ISSUER` | R | none | validated on every token |
| `JWT_AUDIENCE` | R | none | validated on every token |
| `ACCESS_TOKEN_TTL_MINUTES` | D | `15` | short-lived access tokens |
| `REFRESH_TOKEN_TTL_DAYS` | D | `30` | refresh token rotation window |
| `REFRESH_TOKEN_PEPPER` | R | none | S; hashed refresh tokens only |
| `ARGON2_TIME_COST` | D | `3` | password hashing cost |
| `ARGON2_MEMORY_COST_KIB` | D | `65536` | password hashing memory |
| `ARGON2_PARALLELISM` | D | `2` | password hashing parallelism |
| `PASSWORD_MIN_LENGTH` | D | `8` | validated at the schema layer |

### 3.4 Transport security

| Variable | Req | Default | Notes |
|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | R | empty | comma-separated explicit allowlist; never `*` with credentials |
| `CORS_ALLOW_CREDENTIALS` | D | `true` | |
| `HSTS_MAX_AGE_SECONDS` | D | `31536000` | |
| `CONTENT_SECURITY_POLICY` | D | conservative policy | relax deliberately, per environment |
| `SECURITY_HEADERS_ENABLED` | D | `true` | not a feature flag; listed here for completeness |

Rate limiting is always on. Limits are configuration, not flags.

| Variable | Req | Default | Notes |
|---|---|---|---|
| `RATE_LIMIT_AUTH_PER_MINUTE` | D | `10` | login, register, refresh |
| `RATE_LIMIT_PASSWORD_RESET_PER_HOUR` | D | `5` | |
| `RATE_LIMIT_WRITE_PER_MINUTE` | D | `120` | authenticated writes |
| `RATE_LIMIT_GLOBAL_PER_MINUTE` | D | `600` | per client identity |

### 3.5 Storage and media (from milestone M1, used by M9)

Storage is a provider-neutral capability. `STORAGE_PROVIDER` selects the active
adapter; credentials for the inactive provider are not required and are not
validated.

Selection and shared limits:

| Variable | Req | Default | Notes |
|---|---|---|---|
| `STORAGE_PROVIDER` | D | `r2` | `r2` or `cloudinary`; the only switch between providers |
| `STORAGE_SIGNED_URL_TTL_SECONDS` | D | `900` | lifetime of a signed private-asset URL |
| `MAX_UPLOAD_SIZE_MB` | D | `5` | absolute ceiling for any upload |
| `MAX_PRODUCT_IMAGE_SIZE_MB` | D | `5` | product image ceiling, never above the absolute ceiling |
| `MAX_PRODUCT_IMAGE_WIDTH` | D | `2000` | larger images are resized down; never upscaled |
| `MAX_PRODUCT_IMAGE_HEIGHT` | D | `2000` | as above |
| `MAX_PRODUCT_IMAGES_PER_PRODUCT` | D | `10` | count limit per product |
| `MAX_TENANT_STORAGE_MB` | D | `500` | per-tenant quota enforced by AHIA itself |
| `MEDIA_TARGET_FORMAT` | D | `webp` | `webp`, `jpeg`, `png` or `avif`; validated at startup |
| `MEDIA_IMAGE_QUALITY` | D | `82` | encoder quality for lossy targets |
| `MEDIA_STRIP_METADATA` | D | `true` | removes EXIF, GPS and device metadata |
| `MEDIA_ALLOWED_CONTENT_TYPES` | D | `image/jpeg,image/png,image/webp,image/avif` | allowlist, never a denylist |

Cloudflare R2 (active when `STORAGE_PROVIDER=r2`):

| Variable | Req | Default | Notes |
|---|---|---|---|
| `R2_ENDPOINT` | when active | none | S3-compatible endpoint |
| `R2_ACCESS_KEY_ID` | when active | none | S |
| `R2_SECRET_ACCESS_KEY` | when active | none | S |
| `R2_BUCKET` | when active | none | |
| `R2_REGION` | D | `auto` | R2 convention |
| `R2_PUBLIC_BASE_URL` | D | empty | only for intentionally public assets |
| `R2_REQUEST_TIMEOUT_SECONDS` | D | `10` | outbound call timeout |
| `R2_CIRCUIT_FAILURE_THRESHOLD` | D | `5` | breaker trips after N consecutive failures |
| `R2_CIRCUIT_RESET_SECONDS` | D | `60` | open-state duration before a probe |

Cloudinary (active when `STORAGE_PROVIDER=cloudinary`):

| Variable | Req | Default | Notes |
|---|---|---|---|
| `CLOUDINARY_CLOUD_NAME` | when active | none | |
| `CLOUDINARY_API_KEY` | when active | none | S |
| `CLOUDINARY_API_SECRET` | when active | none | S |
| `CLOUDINARY_UPLOAD_FOLDER` | D | `ahia` | prefix applied to every public ID |
| `CLOUDINARY_SECURE_DELIVERY` | D | `true` | HTTPS delivery URLs only |
| `CLOUDINARY_REQUEST_TIMEOUT_SECONDS` | D | `15` | outbound call timeout |

Operational note: the R2 free allowance is not a billing cap. AHIA enforces its
own upload limits and per-tenant quota, because a provider will happily serve
requests that cost money. The same reasoning applies to Cloudinary's free tier.

### 3.6 Public sharing and messaging (milestone M14)

| Variable | Req | Default | Notes |
|---|---|---|---|
| `PUBLIC_WEB_BASE_URL` | R from M14 | `http://localhost:3000` | used to build share links and QR payloads |
| `WHATSAPP_CLICK_TO_CHAT_BASE_URL` | D | `https://wa.me` | provider base, overridable |
| `WHATSAPP_DEFAULT_COUNTRY_CODE` | D | `234` | normalizes local numbers before link building |
| `PUBLIC_TOKEN_BYTES` | D | `24` | entropy of share tokens for invoices, shipments, reports |

### 3.7 Web application (milestone M18)

| Variable | Req | Default | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | R | none | browser-visible API origin |
| `NEXT_PUBLIC_STOREFRONT_BASE_URL` | R | none | public storefront origin |
| `API_INTERNAL_BASE_URL` | D | none | server-side rendering calls |

### 3.8 Mobile application (milestone M19)

| Variable | Req | Default | Notes |
|---|---|---|---|
| `EXPO_PUBLIC_API_BASE_URL` | R | none | device-visible API origin |
| `EXPO_PUBLIC_STOREFRONT_BASE_URL` | D | none | share link previews |
| `EAS_PROJECT_ID` | R at build time | none | EAS build identity |

---

## 4. Feature flags

Flags are declared once, in `backend/src/ahia/core/config.py`, each with a name,
a type, a default, a one-line description, the date it was added, and the
condition under which it will be removed. Flags are booleans or enums, never
free-form strings or numeric thresholds. Flag state is logged once per flag at
startup, at INFO level.

| Flag | Type | Default | Controls | Added | Removal condition |
|---|---|---|---|---|---|
| `FEATURE_OFFLINE_SYNC` | bool | `false` | server-side sync push/pull endpoints | M0 | remove when the mobile client sync engine ships to all tenants |
| `FEATURE_STOREFRONT_PUBLIC_PUBLISHING` | bool | `false` | whether a tenant may publish a public storefront | M0 | remove when public storefronts are generally available |
| `FEATURE_R2_STORAGE` | bool | `false` | whether uploads are written to R2 at all | M0 | remove when image upload is enabled for every tenant |
| `FEATURE_WHATSAPP_CLICK_TO_CHAT` | bool | `false` | WhatsApp inquiry link generation | M14 | remove once verified in production on both clients |
| `FEATURE_AI_INSIGHTS` | bool | `false` | AI-generated insights and forecasts | M0 | remove when AI insights are either adopted or dropped |
| `FEATURE_SUPPLIER_MODULE` | bool | `false` | supplier and procurement endpoints | M0 | remove when procurement reaches general availability |
| `FEATURE_TRACKING_MODULE` | bool | `false` | shipment and tracking endpoints | M0 | remove when logistics reaches general availability |
| `FEATURE_NETWORK_MODULE` | bool | `false` | community and classifieds endpoints | M0 | remove when the network module is adopted or dropped |

Hard rules, enforced by review and by tests:

1. No flag may gate authentication, authorization, input validation, rate
   limiting or error handling. There is no `FEATURE_AUTH_ENABLED`.
2. No security control defaults to the permissive value.
3. No flag may change the meaning of another flag.
4. No flag may be read outside `core/config.py`.

---

## 5. Local database bootstrap

The local PostgreSQL 16 server is used for both development and tests.
Development must not run against SQLite.

Already performed on this workstation:

```bash
# role password for TCP development connections (local only, never reused)
psql -c "ALTER ROLE ksschkw WITH PASSWORD 'ahia_local_dev_only';"

# one database per purpose
psql -c "CREATE DATABASE ahia_dev OWNER ksschkw;"
psql -c "CREATE DATABASE ahia_test OWNER ksschkw;"
```

Resulting local connection strings (development, not secrets that leave this
machine):

```text
DATABASE_URL=postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_dev
TEST_DATABASE_URL=postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test
```

The password above exists only because this workstation's PostgreSQL
configuration requires password authentication over TCP. In any deployed
environment the password is generated by the provider, stored in the platform's
secret store, and rotated on a documented schedule.

---

## 6. What must never appear in the repository

- `.env`, `.env.local`, `.env.*` other than `.env.example`
- real `DATABASE_URL` values containing credentials
- `JWT_SECRET`, `REFRESH_TOKEN_PEPPER`, R2 keys, provider tokens
- private keys, certificates, keystores
- production data exports, customer lists, phone numbers
- any credential in a test fixture, docstring, comment or commit message

Enforcement is automated: `gitleaks` runs in the pre-commit hook and in the test
command, and a custom guard rejects any secret-shaped value in `.env.example`.

---

## 7. Secrets rotation paths

| Secret | Rotation procedure | Blast radius if leaked |
|---|---|---|
| `JWT_SECRET` | publish a new secret with a short dual-validation window, then retire the old one; all sessions are invalidated at cutover | forged access tokens until retired |
| `REFRESH_TOKEN_PEPPER` | requires forced re-authentication of all users; rotate only with a maintenance notice | replay of stolen refresh tokens |
| `DATABASE_URL` password | rotate in the provider, update the platform secret, restart; pooled connections drain | full tenant data access |
| R2 access key | create a second token, deploy, revoke the first | object read/write in one bucket |
| Cloudinary API key | generate a second key in the console, deploy, disable the first | media upload/delete in one cloud |
| Provider API tokens | revoke and reissue in the provider console | depends on the provider scope |

Every rotation is recorded as an operational event with date, operator and
reason.

---

## 8. Decision record: object storage (provider-neutral, R2 by default)

Question raised: Cloudinary or Cloudflare R2 for project storage.

Decision: support both behind one provider-neutral port, and default to R2.

Reasoning.

1. Egress cost shape. Storefront images are public and read many times by many
   customers, so bandwidth dominates the cost model. R2 charges no egress;
   Cloudinary's value is transformation and delivery rather than cheap bulk
   egress. R2 is therefore the default.
2. No structural dependency on either provider. The domain depends on a storage
   capability, not on a vendor. If a provider changes its pricing, availability
   or terms, the response is a configuration change plus an adapter, not a
   rewrite.
3. Switching is a configuration change. `STORAGE_PROVIDER=r2` and
   `STORAGE_PROVIDER=cloudinary` select different adapters with the same
   contract and the same tests. Product, Storefront and ProductImage services do
   not change.
4. Existing assets survive a switch. Persisted metadata records which provider
   holds each object, so an object written under R2 remains readable after the
   active provider changes. A migration is a deliberate backfill, not a
   prerequisite for switching new uploads.
5. Provider separation. The database runs on Neon, the API on Northflank, the
   web on Vercel. Object storage as a separate, S3-compatible concern keeps the
   data plane from concentrating in one vendor.

What this costs us.

- Two adapters to maintain instead of one. The mitigation is a shared contract
  test suite that runs against both, so a behavioural difference is a test
  failure rather than a production surprise.
- Cloudinary's transformation features are available on the Cloudinary path
  only. Delivery URL construction therefore goes through the port, and the
  provider-specific encoding stays inside the adapter.
- Images are optimized before storage regardless of provider, so we do not
  depend on Cloudinary's automatic transformations for correctness. Those
  transformations are a delivery optimization where they exist.

Reversibility: the port lives in `core/ports/storage_port.py`, the adapters in
`integrations/storage/`, and the selection happens in the composition root.
Adding a third provider means one new adapter and one enum value.

---

## 9. Readiness checklist

Backend work may begin when every line below is true.

- [x] Python 3.12 available
- [x] Docker available
- [x] local PostgreSQL 16 running, `ahia_dev` and `ahia_test` created
- [x] repository cloned with working-tree access
- [x] git author identity set to `Ksschkw <kookafor893@gmail.com>`
- [ ] `backend/.venv` created and dependencies installed from the lockfile
- [ ] `gitleaks` present in the workspace tool directory
- [ ] `make check` runs tests, lint, architecture check and secret scan locally
- [ ] `.env` created locally from `.env.example` (never committed)

Frontend work (M18, M19) additionally requires Node 20+, pnpm, and the Expo/EAS
account from section 2.6.
