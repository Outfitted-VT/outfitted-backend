# Outfitted API — Frontend Guide

## Base URL

| Environment | Base URL |
|---|---|
| Local | `http://localhost:8000/api/v1` |

All request and response bodies are JSON (`Content-Type: application/json`).

## Interactive docs

While the backend is running:

- **Swagger UI** — http://localhost:8000/docs (try requests in the browser)
- **ReDoc** — http://localhost:8000/redoc (cleaner reading view)
- **OpenAPI spec** — http://localhost:8000/api/v1/openapi.json

These are generated from the code, so they are always up to date. If this guide and `/docs` ever disagree, `/docs` wins.

### Generating TypeScript types

```bash
npx openapi-typescript http://localhost:8000/api/v1/openapi.json -o src/api/schema.d.ts
```

Re-run it whenever the backend changes.

## CORS

The backend only accepts browser requests from allowed origins. `http://localhost:3000` is allowed by default. If your dev server runs on another port, ask for it to be added to `CORS_ORIGINS`.

## Errors

Every error response has a `detail` field. Check the status code first:

**4xx errors from the API** (e.g. 409) — `detail` is a string you can show to the user:

```json
{ "detail": "Email is already registered" }
```

**422 validation errors** — `detail` is a list, one entry per invalid field. `loc` tells you which field (`["body", "<field>"]`), `msg` is a human-readable message, and `type` is a stable code you can map to your own copy:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "password"],
      "msg": "String should have at least 8 characters",
      "ctx": { "min_length": 8 }
    }
  ]
}
```

## Endpoints

### Sign up

`POST /auth/signup`

Creates a new account. Does **not** log the user in yet — login is coming next.

**Request body**

| Field | Type | Required | Rules |
|---|---|---|---|
| `email` | string | yes | Valid email. Case-insensitive (`Jane@X.com` and `jane@x.com` are the same account). |
| `password` | string | yes | 8–128 characters. |
| `full_name` | string | no | Up to 100 characters. |

```json
{
  "email": "jane@example.com",
  "password": "s3cure-passw0rd",
  "full_name": "Jane Doe"
}
```

**Responses**

`201 Created` — the new user. The password is never returned.

```json
{
  "id": "67a94758-7aa1-4168-b286-4789803a30a8",
  "email": "jane@example.com",
  "full_name": "Jane Doe",
  "is_active": true,
  "created_at": "2026-10-19T16:42:34Z"
}
```

- `id` is a UUID string.
- `email` comes back lowercased.
- `created_at` is ISO 8601 in UTC.

`409 Conflict` — email already registered.

```json
{ "detail": "Email is already registered" }
```

`422 Unprocessable Entity` — invalid email, password too short/long, etc. See [Errors](#errors).

**Example**

```ts
const res = await fetch("http://localhost:8000/api/v1/auth/signup", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password, full_name: fullName }),
});

if (res.status === 201) {
  const user = await res.json();
} else if (res.status === 409) {
  // show "An account with this email already exists"
} else if (res.status === 422) {
  const { detail } = await res.json();
  // detail: [{ loc: ["body", "password"], msg: "...", type: "..." }, ...]
}
```

### Health check

`GET /health`

```json
{ "status": "ok", "version": "0.1.0", "environment": "development", "database": "ok" }
```

Useful to check the backend is up. `database` is `"unavailable"` if the API can't reach the database.
