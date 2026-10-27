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

## Auth

### Sign up

`POST /auth/signup`

Creates a new account. Does **not** log the user in. Call [Log in](#log-in) afterwards to get a token.

**Request body**

| Field | Type | Required | Rules |
|---|---|---|---|
| `email` | string | yes | Valid email. Case-insensitive (`Jane@X.com` and `jane@x.com` are the same account). |
| `username` | string | yes | 3–30 characters: lowercase letters, numbers, `_` and `.`. Can't start/end with `.` or contain `..`. Stored lowercase. Some names (`me`, `admin`, …) are reserved. Public. |
| `password` | string | yes | 8–128 characters. |
| `full_name` | string | no | Up to 100 characters. |

```json
{
  "email": "jane@example.com",
  "username": "jane.doe",
  "password": "s3cure-passw0rd",
  "full_name": "Jane Doe"
}
```

**Responses**

`201 Created` — the new user (same shape as [Get your account](#get-your-account)). The password is never returned.

- `id` is a UUID string.
- `email` and `username` come back lowercased.
- `created_at` is ISO 8601 in UTC.

`409 Conflict` — email or username already in use. Check `detail` to tell which:

```json
{ "detail": "Email is already registered" }
```

```json
{ "detail": "Username is already taken" }
```

`422 Unprocessable Entity` — invalid email or username, password too short/long, etc. See [Errors](#errors).

**Example**

```ts
const res = await fetch("http://localhost:8000/api/v1/auth/signup", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, username, password, full_name: fullName }),
});

if (res.status === 201) {
  const user = await res.json();
} else if (res.status === 409) {
  const { detail } = await res.json(); // email or username taken
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
| `client` | `"web"` or `"native"` | no, defaults to `"web"`. See [Native apps](#native-apps-ios--android). |

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

### Native apps (iOS / Android)

Inside the Capacitor app the page and the API are on different sites, so the refresh cookie isn't stored or sent. Native apps get the refresh token in the response body instead and keep it in the device's secure storage (Keychain / Keystore). Everything else (access token, `apiFetch`, rotation) works the same.

| | Web | Native |
|---|---|---|
| Log in | `{ email, password }` | `{ email, password, "client": "native" }` |
| Refresh token arrives as | `refresh_token` cookie | `refresh_token` in the body, plus `refresh_expires_in` (seconds) |
| Refresh | no body, `credentials: "include"` | body `{ "refresh_token": "..." }` |
| Log out | no body, `credentials: "include"` | body `{ "refresh_token": "..." }` |

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900,
  "refresh_token": "kq3V0m...",
  "refresh_expires_in": 2592000
}
```

- **Save the new refresh token from every refresh response** before doing anything else. The old one stops working (rotation), exactly like the cookie.
- When a refresh body is sent, any cookie is ignored and no cookie is set.
- A cookie refresh never returns the token in the body, so a script on the website can't read the refresh token.
- Never put the refresh token in `localStorage` — use secure storage.

## Conventions for the endpoints below

- **Everything requires an access token** (`Authorization: Bearer ...`) — use `apiFetch` from [Refresh](#refresh). Without one you get **401**.
- **IDs** are UUID strings. **Timestamps** are ISO 8601 in UTC.
- **Like, save, and follow are idempotent.** `PUT` turns it on, `DELETE` turns it off, and repeating either is harmless. They return **204** with no body. That makes optimistic UI easy: update the screen immediately, send the request, and only roll back if it fails.

### Pagination

Every list endpoint returns:

```json
{ "items": [ ... ], "next_cursor": "WyIyMDI2LTEwLTE5VDIwOjIz..." }
```

- Query params: `limit` (1–50, default 20) and `cursor`.
- To load more, send `next_cursor` back as `cursor`. **`next_cursor: null` means there's nothing more.**
- Cursors are opaque strings — don't build or parse them. A malformed cursor returns **400** `{"detail": "Invalid cursor"}`.
- Cursor pagination doesn't skip or repeat items when new posts arrive while someone scrolls (unlike page numbers). It can't jump to "page 5" — it's built for infinite scroll.

```ts
async function loadPage(path: string, cursor: string | null) {
  const params = new URLSearchParams({ limit: "20", ...(cursor && { cursor }) });
  const res = await apiFetch(`${path}?${params}`);
  return res.json() as Promise<{ items: unknown[]; next_cursor: string | null }>;
}
```

---

## Account & profiles

### Get your account

`GET /users/me` 🔒

Your own account, including private fields like `email`.

```json
{
  "id": "3a2f9264-afa7-4a8e-9d47-066fca89a985",
  "username": "jane.doe",
  "full_name": "Jane Doe",
  "avatar": {
    "id": "517830fe-d102-41c1-84b5-f7036e814611",
    "width": 1080,
    "height": 1350,
    "url": "http://localhost:8000/media/images/ac474d14eeb24db699978debafbf5f6f.webp"
  },
  "email": "jane.doe@example.com",
  "bio": "Thrift addict",
  "is_active": true,
  "created_at": "2026-10-19T20:23:53.343519Z"
}
```

`avatar` is `null` until one is set.

### Update your profile

`PATCH /users/me` 🔒

Send **only the fields you want to change**. Omitted fields stay the same. Send `null` to clear `full_name`, `bio`, or `avatar_image_id`.

| Field | Rules |
|---|---|
| `username` | Same rules as sign-up. Can't be `null`. |
| `full_name` | Up to 100 characters. |
| `bio` | Up to 160 characters. |
| `avatar_image_id` | An image `id` from [Upload an image](#upload-an-image). |

```json
{ "bio": "Thrift addict", "avatar_image_id": "517830fe-d102-41c1-84b5-f7036e814611" }
```

**Responses:** `200` with your updated account · `400` `{"detail": "Image not found"}` (not your image) · `409` `{"detail": "Username is already taken"}` · `422` validation.

### Get a profile

`GET /users/{username}` 🔒

Someone's public profile with counts. Never includes their email. `{username}` is case-insensitive.

```json
{
  "id": "3a2f9264-afa7-4a8e-9d47-066fca89a985",
  "username": "jane.doe",
  "full_name": "Jane Doe",
  "avatar": { "id": "...", "width": 1080, "height": 1350, "url": "http://localhost:8000/media/images/....webp" },
  "bio": "Thrift addict",
  "fit_count": 1,
  "follower_count": 1,
  "following_count": 0,
  "is_following": true,
  "created_at": "2026-10-19T20:23:53.343519Z"
}
```

- `is_following` — whether **you** follow them (always `false` on your own profile).
- `404` `{"detail": "User not found"}`.

For your own profile page, call this with your own username to get the counts.

---

## Images

### Upload an image

`POST /images` 🔒

Upload one image as `multipart/form-data`, field name **`file`**. You get back an `id` to use in [Post a fit](#post-a-fit) or as `avatar_image_id`.

- Accepts **JPEG, PNG, or WebP**, up to **10 MB**. (iPhone HEIC photos aren't supported yet — convert to JPEG on the client.)
- The backend converts to WebP, scales the longest side down to 2048px, fixes rotation, and **strips metadata such as GPS location**.
- Upload images in parallel, then create the fit with all the ids.

```ts
async function uploadImage(file: File) {
  const body = new FormData();
  body.append("file", file);
  // Don't set Content-Type yourself — the browser adds the multipart boundary.
  const res = await apiFetch("/images", { method: "POST", body });
  if (!res.ok) throw new Error((await res.json()).detail);
  return res.json(); // { id, url, width, height }
}
```

**Responses:** `201` ↓ · `400` `{"detail": "File is not a supported image"}` / `"Image must be JPEG, PNG, or WebP"` · `413` `{"detail": "Image must be 10 MB or smaller"}`.

```json
{
  "id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26",
  "width": 1080,
  "height": 1350,
  "url": "http://localhost:8000/media/images/8df1d765e86743a79b11fd7d9cfd908d.webp",
  "generated": false
}
```

**Every image object** in the API has this shape. Use `width`/`height` to reserve space before the image loads (`aspect-ratio: width / height`) so the feed doesn't jump.

`generated` is `true` for AI-generated images ([try-on](#virtual-try-on) results). **Label these in the UI** (e.g. an "AI try-on" badge), including in the feed when someone posts one.

---

## Virtual try-on

### Generate a try-on

`POST /tryons` 🔒

Puts clothes onto a photo of you, using a Google image model. There are two modes, which map to an **Entire fit / Pieces** toggle in the UI:

- **Entire fit**: one photo of a whole outfit (on its own, or worn by someone). Send `outfit_image_id`.
- **Pieces**: separate photos combined into one outfit, e.g. a top from one photo, jeans from another, and shoes from a third. Send `pieces`.

1. Upload the photos with [Upload an image](#upload-an-image): a photo of yourself, plus the outfit photo or each piece's photo.
2. Call this endpoint. **It takes a while, often 10–30 seconds, and longer with more pieces**: show progress, and don't time out the request early.
3. To post the result, [create a fit](#post-a-fit) with `result_image.id` in `image_ids`.

| Field | Required | Rules |
|---|---|---|
| `person_image_id` | yes | An image you uploaded. A clear photo of one person works best, ideally full-body. |
| `outfit_image_id` | one of these two | Entire-fit mode. An image you uploaded. |
| `pieces` | one of these two | Pieces mode. 1–7 items of `{ "slot": ..., "image_id": ... }`. |

**Entire fit:**

```json
{
  "person_image_id": "517830fe-d102-41c1-84b5-f7036e814611",
  "outfit_image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26"
}
```

**Pieces:**

```json
{
  "person_image_id": "517830fe-d102-41c1-84b5-f7036e814611",
  "pieces": [
    { "slot": "top", "image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26" },
    { "slot": "bottom", "image_id": "9b2e4c1a-5d3f-4e8a-b7c6-0a1f2e3d4c5b" },
    { "slot": "feet", "image_id": "c4d5e6f7-a8b9-4c0d-9e1f-2a3b4c5d6e7f" }
  ]
}
```

**Slots**, head to toe. Use these for the "add an image" buttons on the body diagram:

| Slot | Body area | For |
|---|---|---|
| `head` | Head | Hats, caps, beanies |
| `top` | Upper body | Shirts, tees, sweaters |
| `outerwear` | Upper body (over the top) | Jackets, coats |
| `one_piece` | Upper + lower body | Dresses, jumpsuits |
| `bottom` | Lower body | Trousers, jeans, skirts, shorts |
| `feet` | Feet | Shoes |
| `accessory` | Anywhere | Bags, belts, scarves |

Rules (breaking them returns `422`):

- Each slot at most once, and each image at most once.
- `one_piece` can't be combined with `top` or `bottom`, since it replaces both. In the UI, picking a dress should clear or disable the top and bottom buttons, and the other way round. It can be combined with `outerwear`, `feet` and the others.
- Only fill the slots the user wants to change. Everything else on the person stays as it is in their photo.
- The order you send pieces in doesn't matter: they're always used and returned head to toe.

**Response** `201`:

```json
{
  "id": "0d5a3c4e-6f62-4bb1-9b0e-2f1c8d7a9e10",
  "result_image": { "id": "...", "width": 1024, "height": 1536, "url": "http://localhost:8000/media/images/....webp", "generated": true },
  "person_image": { "id": "517830fe-...", "width": 1080, "height": 1350, "url": "...", "generated": false },
  "outfit_image": { "id": "16cc86b0-...", "width": 1080, "height": 1350, "url": "...", "generated": false },
  "pieces": [],
  "mode": "outfit",
  "model": "gemini-3.1-flash-image",
  "created_at": "2026-10-21T01:20:00.000000Z"
}
```

In pieces mode, `outfit_image` is `null` and `pieces` lists what was used, head to toe:

```json
{
  "mode": "pieces",
  "outfit_image": null,
  "pieces": [
    { "slot": "top", "image": { "id": "16cc86b0-...", "width": 1080, "height": 1350, "url": "...", "generated": false } },
    { "slot": "feet", "image": { "id": "c4d5e6f7-...", "width": 1080, "height": 1080, "url": "...", "generated": false } }
  ]
}
```

- `result_image` is a new image **you own**, like an upload. It isn't posted anywhere until you create a fit with it.
- `mode` is `"outfit"` or `"pieces"`.
- `person_image`, `outfit_image` and each piece's `image` are `null` if those images were deleted later.

**Responses:**

| Status | `detail` | What to do |
|---|---|---|
| `400` | `"Image not found"` | An id doesn't exist or isn't yours. |
| `400` | `"Try-on can only use one photo right now. Choose 'Entire fit' instead."` | The server's configured model can't combine pieces. Only happens if the backend is switched to the older `virtual-try-on-001` model. |
| `422` | validation `detail` list | Both or neither of `outfit_image_id`/`pieces`, a repeated slot or image, `one_piece` with `top`/`bottom`, or an unknown slot. |
| `422` | `"We couldn't create a try-on from these photos"` | The model refused the photos (safety filters) or didn't return an image. Suggest different photos. |
| `429` | `"You've reached today's try-on limit. Try again tomorrow."` | Each user can make a limited number per 24 hours (default 20). |
| `503` | `"Try-on is temporarily unavailable"`, `"Try-on is busy right now..."` or `"Try-on isn't set up on this server"` | Show the message and let the user retry later. |

Failed try-ons (`422`, `503`) don't count toward the daily limit.

```ts
type Slot = "head" | "top" | "outerwear" | "one_piece" | "bottom" | "feet" | "accessory";

// mode comes from the Entire fit / Pieces toggle.
// pieceIds holds the image picked for each slot button, e.g. { top: "...", feet: "..." }.
const body =
  mode === "outfit"
    ? { person_image_id: personId, outfit_image_id: outfitId }
    : {
        person_image_id: personId,
        pieces: Object.entries(pieceIds).map(([slot, image_id]) => ({ slot, image_id })),
      };

const res = await apiFetch("/tryons", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
if (res.status === 201) {
  const tryon = await res.json(); // show tryon.result_image.url
} else {
  const { detail } = await res.json(); // see the table above
}
```

---

## Fits

### The fit object

Every endpoint that returns fits uses this shape:

```json
{
  "id": "44bf9a0f-d9a8-4755-970f-22d87197bb13",
  "author": {
    "id": "3a2f9264-afa7-4a8e-9d47-066fca89a985",
    "username": "jane.doe",
    "full_name": "Jane Doe",
    "avatar": { "id": "...", "width": 1080, "height": 1350, "url": "..." }
  },
  "caption": "Sunday thrift haul",
  "images": [
    {
      "id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26",
      "width": 1080,
      "height": 1350,
      "url": "http://localhost:8000/media/images/8df1d765e86743a79b11fd7d9cfd908d.webp"
    }
  ],
  "items": [
    {
      "id": "5a0932d4-42f2-4376-a923-95aa166ff0dd",
      "category": "outerwear",
      "name": "Oversized denim jacket",
      "brand": "Levi's",
      "color": "light wash",
      "pattern": null,
      "material": "denim",
      "silhouette": "oversized",
      "url": "https://example.com/jacket",
      "pin": { "image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26", "x": 0.42, "y": 0.31 },
      "source": "detected"
    },
    {
      "id": "6adccd1d-9975-4379-aef6-b8d71d852949",
      "category": "shoes",
      "name": "Sambas",
      "brand": "adidas",
      "color": null,
      "pattern": null,
      "material": null,
      "silhouette": null,
      "url": null,
      "pin": null,
      "source": "user"
    }
  ],
  "occasion_tags": ["casual", "weekend"],
  "style_tags": ["streetwear"],
  "like_count": 1,
  "liked_by_me": true,
  "saved_by_me": false,
  "created_at": "2026-10-19T20:23:53.789725Z"
}
```

- `images` are in display order (first = cover).
- `liked_by_me` / `saved_by_me` are for **the current user**.
- **Item pins:** `x` and `y` are fractions (0–1) of the image's width and height, measured from the top-left. To draw a pin, position it at `left: x * 100%; top: y * 100%` over the image named by `pin.image_id`. Items without a pin have `pin: null`.
- **Categories:** `top`, `bottom`, `dress`, `outerwear`, `shoes`, `bag`, `accessory`, `jewelry`, `headwear`, `other`.
- **Item `source`:** `"detected"` if the item came from [Detect the pieces in a photo](#detect-the-pieces-in-a-photo), `"user"` if a person entered it.
- **Tags:** `occasion_tags` (where you'd wear it) and `style_tags` (the look), lowercase.

### Post a fit

`POST /fits` 🔒

1. Upload each photo with [Upload an image](#upload-an-image).
2. Optional: [detect the pieces](#detect-the-pieces-in-a-photo) in the cover photo and show them as editable suggestions.
3. Post the fit with the image ids:

| Field | Required | Rules |
|---|---|---|
| `image_ids` | yes | 1–10 ids from `POST /images`, in display order, no duplicates. Must be **your** images, and **each image can only be in one fit**. |
| `caption` | no | Up to 2200 characters. |
| `items` | no | Up to 30. See below. |
| `occasion_tags` | no | Up to 10, each 1–30 characters. Stored lowercase; duplicates are dropped. |
| `style_tags` | no | Same rules. |

**Item fields:** `category` (required, one of the categories above), `name` (required, 1–100 chars), `brand` (≤100), `color`, `pattern`, `material`, `silhouette` (each ≤50), `url` (a valid `http(s)` link), `pin` (`{ image_id, x, y }` where `image_id` is one of this fit's `image_ids` and `x`/`y` are 0–1), `source` (`"user"`, the default, or `"detected"`; keep `"detected"` when the user edits a detected item).

```json
{
  "image_ids": ["16cc86b0-3f41-48af-b5b2-1ba3a3e36c26"],
  "caption": "Sunday thrift haul",
  "items": [
    {
      "category": "outerwear",
      "name": "Oversized denim jacket",
      "brand": "Levi's",
      "color": "light wash",
      "url": "https://example.com/jacket",
      "pin": { "image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26", "x": 0.42, "y": 0.31 }
    },
    { "category": "shoes", "name": "Sambas", "brand": "adidas" }
  ]
}
```

**Responses:** `201` with [the fit object](#the-fit-object) · `400` `{"detail": "Image not found"}` (an id isn't yours or doesn't exist) · `409` `{"detail": "Image is already used in another fit"}` · `422` validation (bad category, pin pointing at an image not in `image_ids`, too many images, …).

### Detect the pieces in a photo

`POST /detections` 🔒

Suggests the clothing pieces, occasion/style tags, and shop links in one of your photos, so people don't have to tag them by hand. Takes a few seconds (longer with shop links): call it right after uploading the cover photo (or right after a [try-on](#virtual-try-on), with `result_image.id`), while the user writes the caption.

```json
{ "image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26" }
```

**Response** `200`:

```json
{
  "image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26",
  "items": [
    {
      "category": "top",
      "name": "ribbed tank top",
      "brand": null,
      "color": "black",
      "pattern": null,
      "material": "ribbed cotton",
      "silhouette": "fitted",
      "url": "https://shop.example.com/ribbed-tank-black",
      "pin": { "image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26", "x": 0.508, "y": 0.501 },
      "source": "detected",
      "matches": [
        {
          "title": "Ribbed Tank Top - Black",
          "link": "https://shop.example.com/ribbed-tank-black",
          "source": "Example Shop",
          "thumbnail": "https://images.example.com/tank.jpg",
          "price": "$19.99"
        },
        {
          "title": "Men's Rib Knit Tank",
          "link": "https://store.example.org/rib-tank",
          "source": "Example Store",
          "thumbnail": "https://images.example.org/rib-tank.jpg",
          "price": null
        }
      ]
    },
    {
      "category": "bottom",
      "name": "drawstring sweat shorts",
      "brand": null,
      "color": "light blue",
      "pattern": null,
      "material": "cotton",
      "silhouette": "relaxed",
      "url": null,
      "pin": { "image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26", "x": 0.509, "y": 0.8515 },
      "source": "detected",
      "matches": []
    }
  ],
  "occasion_tags": ["casual", "gym"],
  "style_tags": ["minimalist", "sporty"],
  "model": "gemini-3.1-flash-lite"
}
```

- `items` are already in the shape [Post a fit](#post-a-fit) accepts. Show them as editable suggestions, then send the ones the user keeps, plus the tags, in `POST /fits`.
- `pin` marks where the piece is on this image (`null` if the model didn't locate it). Brands are never guessed.
- **Shop links:** each located piece is looked up with Google Lens visual search. `matches` are products that look like it (up to 3, ones with a price first), and `url` is set to the best one. Let the user pick another match (set `url` to its `link`) or remove the link. `matches` is empty, and `url` is `null`, when nothing was found, the piece wasn't located, or shop matching isn't set up. `POST /fits` ignores `matches`.
- Matches look similar; they aren't guaranteed to be the exact same product. Label them as "similar", not "the one in the photo".
- The result is stored per image: asking again for the same image returns it instantly.
- A photo the model won't process returns empty lists, not an error.

**Responses:** `200` ↑ · `400` `{"detail": "Image not found"}` · `429` daily limit reached (default 200 new images per day) · `503` `{"detail": "Piece detection is temporarily unavailable"}` or `"Piece detection isn't set up on this server"`: let the user tag pieces by hand.

### Get a fit

`GET /fits/{fit_id}` 🔒 → [the fit object](#the-fit-object), or `404` `{"detail": "Fit not found"}`.

### Edit your fit

`PATCH /fits/{fit_id}` 🔒

Send any of `caption`, `items`, `occasion_tags`, `style_tags`. Omitted fields stay the same. **Lists replace the whole list**: send every item or tag you want to keep (send `[]` to remove all). Photos can't be changed after posting.

**Responses:** `200` with the updated fit · `400` `{"detail": "Each item pin must reference one of the fit's images"}` · `403` `{"detail": "You can only change your own fits"}` · `404`.

### Delete your fit

`DELETE /fits/{fit_id}` 🔒 → `204`. Also deletes the fit's photos (unless one is your avatar). `403` if it's not yours, `404` if it doesn't exist.

### List a user's fits

`GET /users/{username}/fits?limit=20&cursor=...` 🔒 → [page](#pagination) of fits, newest first.

---

## Feeds

### Explore feed

`GET /fits?limit=20&cursor=...` 🔒 → [page](#pagination) of everyone's fits, newest first.

### Following feed

`GET /fits/following?limit=20&cursor=...` 🔒 → [page](#pagination) of fits from people you follow **plus your own**, newest first. A new user who follows nobody sees only their own fits — show the explore feed or suggested users in that case.

---

## Likes & saves

| Action | Request | Response |
|---|---|---|
| Like | `PUT /fits/{fit_id}/like` | `204` |
| Unlike | `DELETE /fits/{fit_id}/like` | `204` |
| Save | `PUT /fits/{fit_id}/save` | `204` |
| Unsave | `DELETE /fits/{fit_id}/save` | `204` |
| Your saved fits | `GET /users/me/saved?limit=20&cursor=...` | [page](#pagination) of fits, most recently saved first |

- All 🔒. `404` `{"detail": "Fit not found"}` if the fit doesn't exist.
- Saves are **private** — only you see what you saved. Likes are public as a count.
- No request body.

```ts
// Optimistic like toggle
async function toggleLike(fit: Fit) {
  const liked = !fit.liked_by_me;
  setFit({ ...fit, liked_by_me: liked, like_count: fit.like_count + (liked ? 1 : -1) });
  const res = await apiFetch(`/fits/${fit.id}/like`, { method: liked ? "PUT" : "DELETE" });
  if (!res.ok) setFit(fit); // roll back
}
```

---

## Follows

| Action | Request | Response |
|---|---|---|
| Follow | `PUT /users/{username}/follow` | `204` · `400` `{"detail": "You can't follow yourself"}` · `404` |
| Unfollow | `DELETE /users/{username}/follow` | `204` · `404` |
| Followers | `GET /users/{username}/followers?limit=20&cursor=...` | [page](#pagination) of users, most recent first |
| Following | `GET /users/{username}/following?limit=20&cursor=...` | [page](#pagination) of users, most recent first |

All 🔒. Users in follower/following lists have the compact shape:

```json
{ "id": "...", "username": "bob", "full_name": null, "avatar": null }
```

To show a Follow/Following button for someone, read `is_following` from [Get a profile](#get-a-profile).

---

## Health

### Health check

`GET /health`

```json
{ "status": "ok", "version": "0.1.0", "environment": "development", "database": "ok" }
```

Useful to check the backend is up. `database` is `"unavailable"` if the API can't reach the database.
