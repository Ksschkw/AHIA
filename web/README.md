# AHIA web

The trader-facing web application. Next.js (App Router), TypeScript in strict mode, and a typed
client generated from the backend's own OpenAPI document.

## Running it

The API must be running first (from the repository root):

```
make run          # serves the API on http://127.0.0.1:8000
```

Then, in this directory:

```
npm install
npm run dev       # serves this app on http://localhost:3000
```

Open <http://localhost:3000>. The console walks the product's core loop: create an account, open a
business, add a product, stock it, record a sale, and watch the quantity on hand move. Every number on
the page came from the API; a failure shows the correlation ID a support ticket should quote.

## The API types are generated, not written

`lib/api-schema.d.ts` is generated from `openapi.json`, which is the backend's own specification:

```
curl -s http://127.0.0.1:8000/openapi.json -o openapi.json
npm run api:types
```

Regenerate both after a backend change. The client in `lib/api.ts` is written against those types, so a
field the backend renamed, or a body it now requires, fails `npx tsc --noEmit` here instead of failing
at runtime - which is what happened the first time these types were generated, and it caught three real
mismatches (`/auth/login` takes `identifier`, not `email`; a business carries its own currency and
timezone; a sale line carries its own discount).

## Checking it in a real browser

```
node scripts/browser-check.mjs
```

It drives Chrome through the whole loop and writes a screenshot per step to `.review/`, failing with
the page's own text when a step does not appear. `CHROME_PATH` and `APP_URL` override the defaults.

## Configuration

`NEXT_PUBLIC_API_BASE_URL` (see `.env.example`) is the API's address, and it is compiled into the
client - which is why it is a public variable, and why no secret may go in one.
