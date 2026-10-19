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

## Authentication

There are two tokens:

| | Access token | Refresh token |
|---|---|---|
| Lifetime | 15 minutes | 30 days |
| Where you get it | Response body of login / refresh | `refresh_token` cookie, set by the backend |
| Where it lives | `localStorage` (your code stores it) | Browser cookie jar, `HttpOnly` — **your JavaScript can't read it** |
| How it's sent | You add `Authorization: Bearer <access_token>` | The browser sends it automatically to `/auth/*` |
| Used for | Every protected endpoint | Only `/auth/refresh` and `/auth/logout` |

**The flow**

1. Sign up with `POST /auth/signup` (once).
2. Log in with `POST /auth/login`. Store `access_token`; the browser stores the refresh cookie.
3. Send the access token on protected endpoints:
   ```
   Authorization: Bearer <access_token>
   ```
4. When a protected endpoint returns **401**, call `POST /auth/refresh`. You get a new access token (and the browser gets a new cookie). Retry the original request.
5. If `/auth/refresh` returns **401**, the session is over: show the login screen.
6. On page load with no access token, call `POST /auth/refresh` first — if the cookie is still valid, the user stays logged in.
7. Log out with `POST /auth/logout` (the backend clears the cookie), then delete the access token.

**Important rules**

- **Send `credentials: "include"` on every `/auth/*` call** (login, refresh, logout). Without it the browser won't store or send the cookie, and refresh will always fail.
- **Only one refresh at a time, across all tabs.** The cookie is shared between tabs, so use the [`apiFetch` wrapper](#refresh) below, which uses the Web Locks API to make tabs take turns.
- You can't read or delete the refresh cookie from JavaScript — that's the point. Logout must go through the backend.
- Never put tokens in a URL.
- In Swagger UI (`/docs`), click **Authorize** and paste the access token to try protected endpoints.

## CORS and cookies

The backend only accepts browser requests from allowed origins. `http://localhost:3000` is allowed by default. If your dev server runs on another port, ask for it to be added to `CORS_ORIGINS`.

For the refresh cookie to work:

- Use `credentials: "include"` on `/auth/*` requests.
- Call the API as `http://localhost:8000` from `http://localhost:3000` — not `127.0.0.1` for one and `localhost` for the other, which browsers treat as different sites.
- Safari won't store the `Secure` cookie over plain `http://localhost`. Use Chrome/Firefox locally, or ask for `REFRESH_COOKIE_SECURE=false` in the backend's local `.env`.

## Errors

Every error response has a `detail` field. Check the status code first:

**4xx errors from the API** (e.g. 401, 409) — `detail` is a string you can show to the user:

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

Creates a new account. Does **not** log the user in. Call [Log in](#log-in) afterwards to get a token.

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

### Log in

`POST /auth/login`

**Request body**

| Field | Type | Required |
|---|---|---|
| `email` | string | yes (case-insensitive) |
| `password` | string | yes |

```json
{ "email": "jane@example.com", "password": "s3cure-passw0rd" }
```

**Responses**

`200 OK` — the access token in the body, plus a `Set-Cookie` header with the refresh token.

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900
}
```

```
Set-Cookie: refresh_token=...; HttpOnly; Secure; SameSite=lax; Path=/api/v1/auth; Max-Age=2592000
```

- `expires_in` is how long the access token lasts, in seconds.
- Treat `access_token` as an opaque string. Don't decode it or rely on what's inside.

`401 Unauthorized` — wrong email or password. The message is the same either way on purpose, so don't tell the user which one was wrong.

```json
{ "detail": "Incorrect email or password" }
```

`422 Unprocessable Entity` — missing field or malformed email.

**Example**

```ts
const API = "http://localhost:8000/api/v1";

const res = await fetch(`${API}/auth/login`, {
  method: "POST",
  credentials: "include", // required, so the browser stores the refresh cookie
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password }),
});

if (res.ok) {
  const { access_token } = await res.json();
  localStorage.setItem("access_token", access_token);
} else if (res.status === 401) {
  // show "Incorrect email or password"
}
```

### Refresh

`POST /auth/refresh`

Gets a new access token using the refresh cookie. No request body. Call it with `credentials: "include"`.

The refresh cookie is **rotated**: the old one stops working and the response sets a new one. The browser handles this for you.

**Responses**

`200 OK` — same as [Log in](#log-in): a new access token in the body and a new refresh cookie.

`401 Unauthorized` — no cookie, or it's invalid, expired, or logged out. Show the login screen.

```json
{ "detail": "Invalid or expired refresh token" }
```

**Example: a fetch wrapper that refreshes automatically**

Use this for every call to a protected endpoint. On 401 it refreshes once and retries. The `navigator.locks` call makes all tabs take turns refreshing; a tab that waited re-checks for a token another tab already got, instead of sending the old cookie again.

```ts
const API = "http://localhost:8000/api/v1";

async function refreshAccessToken(staleToken: string | null): Promise<boolean> {
  return navigator.locks.request("auth-refresh", async () => {
    // Another tab may have refreshed while we waited for the lock.
    const current = localStorage.getItem("access_token");
    if (current && current !== staleToken) return true;

    const res = await fetch(`${API}/auth/refresh`, { method: "POST", credentials: "include" });
    if (!res.ok) {
      localStorage.removeItem("access_token");
      return false;
    }
    const { access_token } = await res.json();
    localStorage.setItem("access_token", access_token);
    return true;
  });
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const send = (token: string | null) =>
    fetch(`${API}${path}`, {
      ...init,
      headers: { ...init.headers, ...(token && { Authorization: `Bearer ${token}` }) },
    });

  const token = localStorage.getItem("access_token");
  const res = await send(token);
  if (res.status !== 401) return res;

  if (!(await refreshAccessToken(token))) {
    // redirect to login
    return res;
  }
  return send(localStorage.getItem("access_token"));
}

// On app start: restore the session from the refresh cookie if there's no access token.
export async function restoreSession(): Promise<boolean> {
  if (localStorage.getItem("access_token")) return true;
  return refreshAccessToken(null);
}
```

### Log out

`POST /auth/logout`

Ends this session: the backend revokes the refresh token and clears the cookie. Other devices stay logged in. No body and no `Authorization` header needed. Call it with `credentials: "include"`.

**Responses**

`204 No Content` — always, even if there was no cookie. There's nothing to handle.

The access token keeps working until it expires (at most 15 minutes), so **delete it on the client** too.

**Example**

```ts
await fetch(`${API}/auth/logout`, { method: "POST", credentials: "include" });
localStorage.removeItem("access_token");
// redirect to login
```

### Get current user

`GET /users/me` — 🔒 requires an access token

Returns the logged-in user.

**Responses**

`200 OK` — same shape as the sign-up response.

```json
{
  "id": "1b5975a3-f86c-413a-861a-e7fa01aeb233",
  "email": "jane@example.com",
  "full_name": "Jane Doe",
  "is_active": true,
  "created_at": "2026-10-19T18:20:40Z"
}
```

`401 Unauthorized` — access token missing, invalid, or expired. Refresh and retry (`apiFetch` under [Refresh](#refresh) does this for you).

```json
{ "detail": "Not authenticated" }
```

**Example** (using `apiFetch` from [Refresh](#refresh))

```ts
const res = await apiFetch("/users/me");
if (res.ok) {
  const user = await res.json();
}
```

### Health check

`GET /health`

```json
{ "status": "ok", "version": "0.1.0", "environment": "development", "database": "ok" }
```

Useful to check the backend is up. `database` is `"unavailable"` if the API can't reach the database.
