# Deployment, step by step

The click-level version of `docs/DEPLOYMENT.md`, written because the dashboard is the confusing part and
a guide that assumes you already know where things live is not a guide. Do these in order; each step
produces something the next one needs.

Labels are the ones on your screenshots and in Northflank's documentation. A platform renames buttons
from time to time, so if one word is different, the shape of the thing is still the same.

---

## Before any of this: push

Every step below assumes your commits are on GitHub. The image is built by a workflow that has to exist
on the remote, so a local commit that was never pushed is an image that was never built - and the
symptom at the end of the chain is Northflank saying "this image could not be found", which points at
the registry rather than at the unpushed commit that is really responsible.

```bash
git status -sb        # "ahead N" means N commits are not on GitHub yet
git push origin main
```

Then watch GitHub -> Actions -> *backend image* go green before touching the registry integration.

## A. A GitHub token that can read your image (for Northflank to pull it)

Northflank has to authenticate against GitHub to pull a private image. That needs a token, and it is
**not** the same token GitHub Actions uses - Actions gets its own automatically.

1. github.com, signed in. Click your **avatar** (top right) -> **Settings**.
2. In the left sidebar, at the very bottom: **Developer settings**.
3. **Personal access tokens** -> **Tokens (classic)** -> **Generate new token (classic)**.
4. Note: `northflank-pull`. Expiration: 90 days or longer (a token that expires silently breaks deploys;
   put the renewal in your calendar).
5. Tick exactly one scope: **`read:packages`** - the row that reads *"Download packages from GitHub
   Package Registry"*, in the same group as `write:packages` and `delete:packages`. Nothing else. It
   only needs to read your images.
   - **Untick `workflow` if it is ticked.** It is easy to catch while scrolling and it grants the right
     to modify your workflow files, which this token has no business doing.
   - **`repo` is not needed** to pull a public-repository image. If the Northflank integration refuses
     with a permission error, tick `repo` as well and try again - it is the fallback for a package
     attached to a private repository, and it is a bigger grant, so reach for it only if refused.
6. **Generate token**, then copy it. GitHub shows it once - if you lose it, generate another.
7. **Check the expiration.** 30 days is the default and a token that expires takes your deploys down
   silently on a day you are not thinking about deployment. Pick the longest offered, or 90 days with
   the renewal in your calendar.

A fine-grained token also works, but classic is fewer steps and `read:packages` is exactly the
permission needed.

---

## B. Where your image will appear

Nothing to do yet. Push to `main` and the `backend image` workflow builds and publishes
`ghcr.io/<your-username>/ahia-backend`, tagged both `sha-<12 chars>` and `main`. It appears under your
GitHub profile -> **Packages**.

The package is **private by default**, which is right. Do not make it public to avoid the token: an
image contains your application.

To confirm it worked: repo -> **Actions** -> *backend image* -> the run is green, and the step summary
prints the two tags.

---

## C. A Northflank API token (so Actions can deploy)

This is what lets GitHub do the deploying instead of you.

1. app.northflank.com, signed in to the **Ksschkw's Team** account.
2. Click your **avatar** (top right) -> **Account**.
3. **API tokens** (in the Account settings sidebar).
4. **Create API token**. Name: `github-actions`. Give it access to your team (an *editor*-level token
   scoped to your project is enough - it needs to trigger a job and change a service's image).
5. Copy it. Shown once.

Then, on your machine:

```bash
cd /home/ksschkw/kss/AHIA
gh secret set NORTHFLANK_API_TOKEN --body "<paste the token>"
```

---

## D. The registry integration (the page you were on)

**Skip "SSH identities" entirely.** Your screenshot shows you on it, and it is for something else: SSH
identities are public keys for connecting *into* running containers or pulling from a Git repository over
SSH. Nothing about pulling a container image needs one.

You want the tab next to it: **Integrations -> Registries**.

1. **Add registry integration**.
2. Fill it in like this:

| Field | Value |
|---|---|
| Name | `ghcr` |
| Registry type / provider | **Custom** (GitHub's is under "other" - the form asks for a host) |
| Registry host / URL | `ghcr.io` |
| Username | your **GitHub username**, `Ksschkw` |
| Password / token | the token from **A** above |
| Email | leave blank, or any address |

3. **Save**. Northflank verifies it by trying to read the registry, so if the token is wrong you find out
   here rather than at deploy time. If it fails: the username must be your GitHub *username*, not your
   email, and the token must have `read:packages`.

The other two things on that page - "Save registry credentials" and "Run an image from a container
registry" - are links into the two flows below.

---

## E. The API service

**Create -> Service**, then choose the deployment source **Run an image from a container registry** (or
"External image"). If there is no image to list yet, push to `main` first so the package exists.

| Setting | Value |
|---|---|
| Name | `ahia-api` |
| Registry credentials | the `ghcr` integration from D |
| Image path | `ghcr.io/ksschkw/ahia-backend:main` |

**The tag goes inside the image path, after a colon** - Northflank's form has no separate tag box. Leave
it off and it means `:latest`, which does not exist in this registry: the workflow publishes `main` and
`sha-<12 chars>`, so the deploy fails with "manifest unknown" and the cause is invisible unless you know
that a bare path implies `latest`.

`main` is right for the very first deploy, because the pipeline has not pinned anything yet. Once the
three ids are set in step G, the workflow re-points the service at `sha-<that commit>` by itself, and
from then on the service never follows whatever `main` happens to be.
| Region | the one nearest you, and **the same one for the job below** |
| Port | `8000`, protocol **HTTP** (in the networking section, further down the form) |
| Health check path | `/health` |
| Instances | 1 |

Then open the service's **Environment** section and add every variable from
`docs/DEPLOYMENT.md` section 1.3. The three that break things quietly:

- `CORS_ALLOWED_ORIGINS` must be the Vercel URL, exact, with `https://` and no trailing slash.
- `DATABASE_URL` must be `postgresql+asyncpg://...` and must **not** carry `?sslmode=require`.
- `DATABASE_REQUIRE_SSL=true` is how TLS is asked for instead.

Deploy it. Watch **Logs**: a healthy start prints the application startup lines and then the health
check begins answering.

---

## F. The migration job

**Create -> Job** (a one-off job, not a service). Same image and registry as E. Then:

- Command / entrypoint override: `alembic upgrade head`
- No port, no health check.
- The same environment variables as the service. The job needs the database and the JWT secret to
  import the application's configuration at all.

Run it once by hand now: the **Run** button. This is the step that creates your tables in Neon. If it
fails, the log says why and it is almost always the database URL.

**Why not let the API do this on boot:** two instances starting together would both run the migration,
and a schema changed by two processes at once is a corruption story rather than a scaling story.

---

## G. The three ids, and pointing Actions at them

Open the project in your browser and read the **URL**:

```
https://app.northflank.com/t/ksschkw-s-team/projects/<PROJECT_ID>/services/<SERVICE_ID>
```

- `PROJECT_ID` - the segment after `/projects/`
- `SERVICE_ID` - the segment after `/services/`
- `JOB_ID` - open the job and read the same segment shape from its URL

Then:

```bash
gh variable set NORTHFLANK_PROJECT_ID --body "<PROJECT_ID>"
gh variable set NORTHFLANK_SERVICE_ID --body "<SERVICE_ID>"
gh variable set NORTHFLANK_JOB_ID     --body "<JOB_ID>"
```

From now on, `git push origin main` builds the image, runs the migration, and re-points the service at
that commit. The `backend deploy` workflow prints exactly these four commands if you have not set them,
so you cannot lose them.

---

## H. The web app

1. vercel.com -> **Add New Project** -> import the repository.
2. **Root Directory: `web`**. Set it before the first build; the monorepo layout is the one thing that
   trips this up.
3. Framework preset: **Next.js**.
4. Environment variables:

```
NEXT_PUBLIC_API_BASE_URL=https://<your-northflank-domain>
API_PROXY_TARGET=https://<your-northflank-domain>
NEXT_PUBLIC_SITE_URL=https://<your-vercel-domain>
```

5. Deploy, then **copy the Vercel domain back into Northflank's `CORS_ALLOWED_ORIGINS`** and let the
   service redeploy.

**The order is the whole point.** The backend has to allow the frontend, and you only learn the
frontend's address after Vercel gives it to you. Get it backwards and the browser blocks every request
while `curl` from the same machine works - the most confusing half-hour in any deployment.

---

## I. Check it, then use it

```bash
curl -s https://<your-northflank-domain>/health
```

A `{"status":"ok"}` means the API, the database and the migration all agree. Then open the Vercel URL and
create an account - that is the first real test, because it exercises the browser, the proxy, CORS, the
cookie and the database in one go.

---

## J. When something is wrong

| What you see | What it usually is |
|---|---|
| The service starts and then restarts in a loop | a missing environment variable; the log names it |
| `/health` hangs | the database URL, or Neon blocking the connection |
| The API works from `curl` but the browser says CORS | `CORS_ALLOWED_ORIGINS` is not exactly the Vercel origin |
| Sign-in appears to work and then everything is 401 | the cookie is being refused: the web app is not proxying `/api`, so the cookie is cross-site |
| The registry integration will not save | token missing `read:packages`, or the username is an email |
| **"This image could not be found" on the Northflank form** | almost always that the image does not exist yet: the commits are not pushed, or the *backend image* workflow has not run for them. Check GitHub -> Actions first, then the package under GitHub -> your profile -> Packages. Only after that is it a wrong tag or a wrong repository name |
| The image tag is "not found" and the package does exist | the tag is `sha-` with the wrong 12 characters, or the image path omits `:main` and so means `:latest` |

## K. Secrets, once more

- `backend/.env.deploy` is where the values live on this machine. It is gitignored; confirm with
  `git check-ignore -v backend/.env.deploy`.
- `bash backend/scripts/configure_deployment.sh` pushes them to GitHub and is safe to re-run whenever a
  value rotates. It strips inline comments, so a leftover `# local dev only` cannot end up inside a
  production secret.
- The Neon password and the Cloudinary secret have both sat in a gitignored file on this machine.
  Rotate both before they guard anything real, then re-run that script.
