# Deploying AHIA

The product owner said he would handle the platform, so this is the guide he asked for rather than a
configuration he has to reverse-engineer. It is written for his own free-tier setup: **GitHub Actions
builds, the platform runs**.

## 1. Why the image is built in Actions

His suggestion, and it is the right one. The expensive half of a deployment is compiling the dependency
closure and assembling layers. A platform's build minutes are the scarcest thing on a free tier, and
spending them on every deploy means deploy becomes something to avoid - which is precisely the habit
that makes a project painful.

So: **GitHub Actions builds the image and pushes it to the GitHub Container Registry; Northflank pulls
it and starts it.** What that buys:

- The platform does no building at all. A deploy is a pull and a restart, which is seconds.
- Layer caching lives in Actions (`cache-from: type=gha`), so a build that changes one line of Python
  reuses the dependency layer instead of reinstalling it.
- The image is **immutable and addressed by commit**: `ghcr.io/<owner>/ahia-backend:sha-<12 chars>`.
  A rollback is pointing the service at an earlier tag, not rebuilding an earlier commit and hoping the
  dependencies resolve the same way. That is the difference between a rollback you can do at midnight
  and one you cannot.
- The same image runs wherever you point it: a staging service, a production service, or your own
  machine, with only environment variables differing.

### Prerequisites this adds

Being straight about what it costs, since you asked:

1. **A GitHub Container Registry package.** Created automatically on the first successful push. It is
   private by default, which is correct - keep it private.
2. **A registry credential on Northflank.** A GitHub personal access token with `read:packages` (a
   fine-grained token scoped to this repository/package is enough). Northflank needs it once, as a
   registry secret, to pull a private image.
3. **A migration step.** This is the one people forget. The image starts the API; it does **not** run
   `alembic upgrade head` on boot, and it should not - a migration that runs inside an API container
   races itself when the platform starts more than one replica. The schema is moved by a **separate
   one-off job** (see section 3).
4. **No secret in the image.** Everything arrives as environment variables at runtime, which is already
   how the container is built.

## 2. The backend on Northflank

### 2.1 The service

Create a **Service**, not a Build Service: the image already exists, so there is nothing to build.

| Setting | Value |
|---|---|
| Deployment source | **External image** |
| Image | `ghcr.io/<your-username>/ahia-backend:sha-<the commit you want>` |
| Registry credential | the GHCR token from section 1 |
| Port | `8000`, HTTP |
| Health check path | `/health` (liveness) - readiness is `/health/ready` |
| Command | leave the image's default (`uvicorn ...`, honouring `$PORT`) |
| Replicas | 1 to start |

Pin the **sha tag**, not `main`. Pinning by commit is what makes the deployed thing identifiable, and
`main` is a moving target that makes "what is running" an unanswerable question.

### 2.2 Environment variables

Everything the runtime needs, as secret or plain values in the service's configuration. The full list
with descriptions is in `docs/PREREQUISITES.md`; the ones a deployment cannot start without:

```
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<neon-host>/<database>
DATABASE_REQUIRE_SSL=true
JWT_SECRET=<a long random value, unique to this environment>
PHONE_COUNTRY_CODE=+234
CORS_ALLOWED_ORIGINS=https://<your-vercel-domain>
STORAGE_PROVIDER=cloudinary
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
FEATURE_MEDIA_UPLOAD=true
FEATURE_STOREFRONT_PUBLIC_PUBLISHING=true
```

Three things about this list that matter:

- **`CORS_ALLOWED_ORIGINS` must be the Vercel domain**, or the browser will refuse every call while
  `curl` works perfectly - the most confusing half-hour in any deployment.
- **`JWT_SECRET` must be different from every other environment.** Sharing it between staging and
  production means a token minted in one is valid in the other.
- **Do not put `?sslmode=require` on `DATABASE_URL`.** The driver this project uses rejects the
  parameter and fails at connect time; `DATABASE_REQUIRE_SSL=true` is how TLS is asked for here.

### 2.3 The migration job

A second Northflank resource: a **Job**, same image, same environment, with the command overridden:

```
alembic upgrade head
```

Run it **before** rolling the new service image. Two rules, both learned the hard way by somebody:

- Migrations must be **backwards compatible with the currently running code**, because both versions
  serve traffic during a rollout. Add columns; do not remove them in the same release that stops using
  them.
- The job runs **once**, never as part of the service start command. Two containers racing to migrate
  the same database is a corruption story, not a scaling story.

## 3. The web app on Vercel

The web app does not need Actions or a container: Vercel builds it from the repository, and its free
tier is generous for a Next.js app.

1. **Import the repository** in Vercel, and set the **root directory to `web`**. The monorepo layout is
   the only thing that trips this up.
2. Framework preset: **Next.js**. Build command and output are detected.
3. Environment variables:

```
NEXT_PUBLIC_API_BASE_URL=https://<your-northflank-domain>
API_PROXY_TARGET=https://<your-northflank-domain>
NEXT_PUBLIC_SITE_URL=https://<your-vercel-domain>
```

4. **Then go back to Northflank and put the Vercel domain in `CORS_ALLOWED_ORIGINS`.** The order
   matters: the backend has to allow the frontend, and you only know the frontend's address after Vercel
   gives it to you.
5. Custom domain, when you want one: add it in Vercel, then point the DNS record it asks for.

### Why the API is proxied

`next.config.ts` rewrites `/api/*` to `API_PROXY_TARGET`. That exists because the session lives in a
**cookie**, and a cookie set by `api.example.com` is not sent by a page served from `www.example.com`
unless the browsers' cross-site rules are satisfied - and on `localhost` with different ports they
never are. Proxying means the browser sees one origin, the cookie is first-party, and none of that
becomes a puzzle in production that it was not in development.

## 4. What a deploy looks like once this is set up

```
git push origin main
  |
  +-- backend-check.yml    the gate: tests, lint, types, architecture, secrets, dependencies
  +-- backend-image.yml    build the image, push ghcr.io/<owner>/ahia-backend:sha-<12>
  +-- Vercel               build and deploy the web app
        |
        v
  Northflank: run the migration job, then point the service at the new sha tag
```

The last step is the one to automate later, and it can be: Northflank has an API and a CLI, so a third
workflow can call it with a token and pin the service to `sha-${GITHUB_SHA::12}` after the migration job
succeeds. That is deliberately **not** built yet. Deploying by hand a few times first is how you learn
what the pipeline should do; automating a sequence nobody has run is how you get a pipeline that
deploys confidently and wrongly.

## 5. Prerequisites for live testing

To test against a live deployment you need, in this order:

1. A **Neon database** reachable from the API (the connection string above). Its password is a secret
   that has appeared in a gitignored file on this machine, so it should be **rotated** before it guards
   anything real.
2. A **Cloudinary** account. The secret currently in the local `.env` should also be rotated.
3. The **GHCR package** and the **Northflank registry secret** from section 1.
4. The Vercel project, and the Vercel domain copied into `CORS_ALLOWED_ORIGINS`.
5. `JWT_SECRET` generated fresh for production - not copied from development, ever.
