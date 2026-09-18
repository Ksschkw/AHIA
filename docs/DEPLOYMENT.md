# Deploying AHIA

> **Doing this for the first time? Read `docs/DEPLOYMENT_STEPS.md` instead.** That one is the same
> setup at the click level - where the Northflank API token lives, what the registry integration's
> fields want, which of the three SSH identities pages to ignore, and what to try when a step fails.
> This file is the reference: why each piece is the way it is.

Written for the product owner's own free-tier setup, and written to be **done once, from a terminal,
without clicking around a dashboard**. Every value below is either something you paste once or something
a script sets for you.

The shape of it: **GitHub Actions builds the image; Northflank runs it; Vercel serves the web app.**
Nothing is compiled on the platform, because compile minutes are the scarcest thing on a free tier and
an expensive deploy is a deploy you avoid.

---

## 0. What you need, and where each thing comes from

| # | What | Where it comes from | Used as |
|---|---|---|---|
| 1 | GitHub account with this repository pushed | you already have it | the source of everything |
| 2 | Container registry package | created automatically on the first image push | the image Northflank pulls |
| 3 | GitHub token with `read:packages` | GitHub, Settings, Developer settings, Personal access tokens (fine-grained) | Northflank's registry credential |
| 4 | Northflank account, one project | northflank.com | runs the API |
| 5 | Northflank API token | Northflank, Account, API tokens | GitHub secret, so Actions can deploy |
| 6 | Northflank project id, service id, migration job id | in the Northflank URLs once the resources exist | GitHub variables |
| 7 | Neon database | neon.tech | the database |
| 8 | Neon connection string | Neon console, Connection details, **asyncpg** tab | GitHub secret |
| 9 | Cloudinary cloud name, api key, api secret | cloudinary.com dashboard | GitHub secrets |
| 10 | Vercel account | vercel.com | serves the web app |
| 11 | Vercel project id and org id | Vercel project settings | GitHub secrets, only if automating the web env |
| 12 | A JWT secret, generated fresh | `openssl rand -hex 32` | GitHub secret |

That is the whole list. Nothing else is needed, and nothing on it is a paid feature.

---

## 1. Everything, once, from your terminal

### 1.1 Create the deploy values file

Create `backend/.env.deploy` (it is gitignored, and it holds real secrets - never commit it):

```
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST/DATABASE
JWT_SECRET=<paste the output of openssl rand -hex 32>
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

Generate the JWT secret with:

```bash
openssl rand -hex 32
```

**Three things that will cost you an hour each if you skip them:**

- **No `?sslmode=require` on the URL.** This driver rejects the parameter and fails at connect time.
  TLS is asked for with `DATABASE_REQUIRE_SSL=true` instead, which the script sets for you.
- **The Neon URL must be the asyncpg one**, `postgresql+asyncpg://`, not the `postgres://` one the
  console shows first.
- **The JWT secret must be fresh.** Not copied from your development `.env`, ever.

### 1.2 Push it all into GitHub

```bash
cd /home/ksschkw/kss/AHIA
bash backend/scripts/configure_deployment.sh
```

That script reads `backend/.env.deploy` and sets every GitHub secret and variable the workflows need,
using `gh`. It is idempotent - run it again whenever a value rotates. It prints each thing it sets, so
you can see what exists. It needs `gh auth status` to be a signed-in session with `repo` and
`write:packages` scope; it checks and tells you if not.

**This is the "not manual" part.** After this, no secret is ever typed into a dashboard.

### 1.3 Create the two Northflank resources

This part is a dashboard, because it needs a service that does not exist yet - after which even this is
scriptable, and the script for that is section 3.

**The API service**

| Setting | Value |
|---|---|
| Type | **Service** (not Build Service - the image is already built) |
| Deployment | **External image** |
| Image | `ghcr.io/<your-github-username>/ahia-backend:main` |
| Registry credential | the token from item 3 above |
| Port | `8000`, HTTP |
| Health check | path `/health` |
| Replicas | 1 |

Point it at `:main` **first**, so the platform can start; section 3 switches it to pinning the commit
sha automatically from then on.

Then paste these into the service's environment (values from `backend/.env.deploy`, plus the rest):

```
APP_ENV=production
DATABASE_URL=<from .env.deploy>
DATABASE_REQUIRE_SSL=true
JWT_SECRET=<from .env.deploy>
PHONE_COUNTRY_CODE=+234
CORS_ALLOWED_ORIGINS=https://<your-vercel-domain>
STORAGE_PROVIDER=cloudinary
CLOUDINARY_CLOUD_NAME=<from .env.deploy>
CLOUDINARY_API_KEY=<from .env.deploy>
CLOUDINARY_API_SECRET=<from .env.deploy>
FEATURE_MEDIA_UPLOAD=true
FEATURE_STOREFRONT_PUBLIC_PUBLISHING=true
```

**The migration job**

A second resource, type **Job**, same image and same environment, with the command overridden:

```
alembic upgrade head
```

This exists because the API container must never migrate: two replicas racing to change one schema is a
corruption story, not a scaling story. The job is triggered by the deploy pipeline, once, before the
new code serves traffic.

### 1.4 The web app on Vercel

1. vercel.com, **Add New Project**, import this repository.
2. **Root directory: `web`.** The monorepo layout is the one thing that trips this up.
3. Framework preset: **Next.js**. Build and output settings are detected.
4. Environment variables:

```
NEXT_PUBLIC_API_BASE_URL=https://<your-northflank-domain>
API_PROXY_TARGET=https://<your-northflank-domain>
NEXT_PUBLIC_SITE_URL=https://<your-vercel-domain>
```

5. Deploy, then **copy the Vercel domain back into Northflank's `CORS_ALLOWED_ORIGINS`.**

**The order matters.** The backend has to allow the frontend, and you only learn the frontend's address
after Vercel gives it to you. Getting this backwards produces the most confusing half-hour in any
deployment: the browser refuses every call while `curl` from the same machine works perfectly.

**Why the API is proxied at all:** the session lives in a cookie, and a cookie set by
`api.example.com` is not sent by a page served from `www.example.com` under the browsers' cross-site
rules. `next.config.ts` rewrites `/api/*` to `API_PROXY_TARGET`, so the browser sees one origin and the
cookie is first-party.

### 1.5 Check it

```bash
curl -s https://<your-northflank-domain>/health
```

`{"status":"ok"}` means the API, the database and the migration all agree. If it hangs, the database URL
is wrong; if it refuses, the container did not start and the service's log will say why.

---

## 2. Do you have to update the sha tag every time?

**Today: yes, if you are doing it by hand - one field, one service.** The pipeline publishes
`ghcr.io/<owner>/ahia-backend:sha-<12 chars>` and `:main`, and pinning the sha by hand is what makes
"what is running" answerable and a rollback a single field edit.

**But you should not, and after section 3 you will not.** Once the Northflank API token is in GitHub,
the deploy workflow pins the service to the new sha itself, after the migration job has finished. From
then on a deployment is `git push origin main` and nothing else.

There is a deliberate order to this. Deploy by hand two or three times **first**. Automating a sequence
nobody has watched run produces a pipeline that deploys confidently and wrongly, and when it goes wrong
at midnight you have no memory of what the steps are. Watch it work, then automate what you watched.

---

## 3. Automating the pinning, so a push is the whole deploy

Once the resources exist, collect four values from their URLs:

- Northflank **project id** - in the project's URL.
- **service id** - in the service's URL.
- **migration job id** - in the job's URL.
- **API token** - Account, API tokens.

```bash
gh secret set NORTHFLANK_API_TOKEN --body "<the token>"
gh variable set NORTHFLANK_PROJECT_ID --body "<project id>"
gh variable set NORTHFLANK_SERVICE_ID --body "<service id>"
gh variable set NORTHFLANK_JOB_ID --body "<job id>"
```

`.github/workflows/backend-deploy.yml` then does the rest on every push to `main`, in this order, and
stops if any step fails:

1. Confirm the image for this commit exists in the registry.
2. Trigger the **migration job** and wait for it to finish.
3. Pin the **service** to `ghcr.io/<owner>/ahia-backend:sha-<12>`.

Migrations run before the new code serves traffic, and the pin happens only if the migration succeeded -
which is the whole reason the sequence is explicit rather than three independent triggers.

If the workflow is not configured yet (no `NORTHFLANK_SERVICE_ID`), it prints what to do and exits
without failing your push. An unconfigured pipeline should not look like a broken build.

---

## 4. What a deploy looks like afterwards

```
git push origin main
  |
  +-- backend-check.yml     the gate: tests, lint, types, architecture, secrets, dependencies
  +-- backend-image.yml     build and push ghcr.io/<owner>/ahia-backend:sha-<12>
  +-- backend-deploy.yml    migrate, then pin the service to that sha
  +-- Vercel                build and deploy the web app
```

**Rolling back** is pointing the service at an earlier `sha-` tag. That is why the tags are immutable
and commit-addressed: a rollback that rebuilds an old commit is a rollback that can fail, at the worst
possible moment, for reasons unrelated to the thing you are rolling back from.

---

## 5. Secrets hygiene, because this is a live product

- `backend/.env`, `backend/.env.deploy` and `web/.env.local` are gitignored. Confirm with
  `git check-ignore -v backend/.env.deploy` before you paste anything into it.
- The Neon password and the Cloudinary secret **have both appeared in a gitignored file on this
  machine**, so rotate both before they guard anything real. Cloudinary: Settings, Security, rotate.
  Neon: Settings, Reset password.
- Rotating a GitHub secret is `bash backend/scripts/configure_deployment.sh` again.
- Rotating what the service sees means editing the service's environment in Northflank; the next deploy
  picks it up.
- Nothing secret is ever baked into the image. Configuration arrives as environment variables at
  runtime, which is what makes the same image usable in every environment.
