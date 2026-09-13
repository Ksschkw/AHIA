# API reference: the User slice

Status: implemented and verified (milestone M2)
Base path: `/api/v1`
Authentication: bearer access token

This is the first vertical slice. It exists to prove the architecture end to end
before the remaining entities are built on the same shape, and this document is
the contract a client can rely on.

---

## Conventions

### Correlation ID

Every response carries the correlation ID for the request, in the header
`X-Correlation-ID`.

- Send your own value to have it echoed back and used in every log line for that
  request. It must be 8 to 128 characters from `A-Z a-z 0-9 . _ : -`.
- Send nothing, or send a value that does not match, and the service generates
  one. An invalid value is replaced rather than rejected, so a broken client
  integration never blocks a request.
- Quote this value when reporting a problem. It is the only thing an engineer
  needs to find the exact request.

### Error envelope

Every failure, from every route, uses one shape:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "The requested resource was not found.",
    "correlation_id": "8f3a1c2e4b2c9d1e"
  }
}
```

Three fields, always. The message is safe to show a user and never contains a
stack trace, a SQL fragment, a file path, a hostname, a framework name or a
statement about whether an account exists.

| Code | Status | Meaning |
|---|---|---|
| `INVALID_REQUEST` | 422 | The request body or parameters failed validation |
| `INVALID_MEDIA` | 422 | An uploaded file is not acceptable |
| `NOT_FOUND` | 404 | No such resource, or not yours. The two are deliberately indistinguishable |
| `CONFLICT` | 409 | A uniqueness or state conflict |
| `BUSINESS_RULE_VIOLATION` | 422 | The operation is not allowed in the current state |
| `STORAGE_QUOTA_EXCEEDED` | 413 | The workspace is at its storage limit |
| `RESOURCE_LIMIT_EXCEEDED` | 422 | A per-resource limit was reached |
| `UNAUTHENTICATED` | 401 | No usable credential was presented |
| `INVALID_CREDENTIALS` | 401 | Credentials were presented and rejected |
| `FORBIDDEN` | 403 | Authenticated, but not permitted |
| `RATE_LIMITED` | 429 | Too many requests; see `Retry-After` |
| `DEPENDENCY_UNAVAILABLE` | 503 | A dependent service is unavailable |
| `DEPENDENCY_TIMEOUT` | 504 | A dependent service did not respond in time |
| `DEPENDENCY_BUSY` | 503 | A dependent service is saturated |
| `STORAGE_UNAVAILABLE` | 503 | File storage is temporarily unavailable |
| `STORAGE_ERROR` | 502 | A file could not be stored |
| `INTERNAL_ERROR` | 500 | An unexpected failure. Nothing internal is disclosed |

### Authentication

```http
Authorization: Bearer <access token>
```

Every rejection - missing header, wrong scheme, empty token, malformed token,
expired token, wrong issuer, wrong audience, unknown subject, deactivated
account - produces the same `401` with code `UNAUTHENTICATED`. That is
deliberate: a client must not be able to learn from the response whether an
account exists, whether it is disabled, or whether a token was ever valid.

---

## Endpoints

### GET `/api/v1/users/me`

Return the authenticated user's own profile.

```bash
curl -s https://api.example.com/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "id": "6a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d",
  "first_name": "Emeka",
  "last_name": "Okonkwo",
  "email": "emeka@example.com",
  "phone": "+2348031234567",
  "is_active": true,
  "is_email_verified": false,
  "is_phone_verified": false,
  "created_at": "2026-09-13T09:30:00+00:00",
  "updated_at": "2026-09-13T09:30:00+00:00",
  "last_login_at": null
}
```

The password hash is never present, and a test asserts that no field in this
response can be credential-shaped.

### PATCH `/api/v1/users/me`

Apply a partial update to the authenticated user's own profile.

```bash
curl -s -X PATCH https://api.example.com/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"first_name": "Chinedu", "email": "chinedu@example.com"}'
```

Accepted fields: `first_name`, `last_name`, `email`, `phone`. Any other field is
rejected with `422`, including `id`, `is_active` and anything credential-shaped:
this endpoint is not a password endpoint and must never become one.

An omitted field means "leave it alone". Contact values are normalized
(`"  ADA@Example.com "` is stored as `ada@example.com`; `"0803 123 4567"` is
stored as `08031234567`), which is what keeps the uniqueness rules meaningful.

`409 CONFLICT` means another account already holds that email address or phone
number.

### DELETE `/api/v1/users/me`

Deactivate the authenticated user's own account. Returns `200` with the resulting
representation, where `is_active` is `false`.

This is not a deletion. Business history - sales, receipts, inventory movements -
references the person, and a receipt must not lose its seller because they closed
their account. Every token the account holds stops working immediately; the next
request returns `401`.

---

## What this slice deliberately does not do

- **No `{user_id}` path parameter.** A client cannot ask for another account by
  changing an identifier. Administrative endpoints, when they arrive, resolve
  access through the service from a membership, never from a path parameter.
- **No tenant or role handling.** A user is an identity; tenant membership,
  roles and permissions are separate facts with separate failure modes and
  arrive in M4 through M6. An authenticated user with no active membership can do
  nothing, and that is the correct state.
- **No password endpoint.** Password change and reset arrive with authentication
  in M3.

---

## Verified behaviour

The slice is covered by 51 tests at four layers, plus seven end-to-end tests that
run against a real PostgreSQL database with nothing mocked:

- a user is created, reads their profile, changes it, deactivates the account,
  and the token they were holding stops authenticating immediately
- a change made in one request is visible in the next, in a new transaction
- two users never see each other's record, whatever the request contains
- a duplicate email surfaces as a typed conflict through the whole stack
- a database that is unreachable produces a response whose body contains no
  path, SQL, driver name, hostname, port or traceback
- the correlation ID travels from the request into the response
