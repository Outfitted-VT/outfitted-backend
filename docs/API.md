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
  "created_at": "2026-10-19T20:23:53.343519Z",
  "style_tags": ["minimal"],
  "fit_preference": "relaxed",
  "top_size": "S",
  "bottom_size": "M",
  "feedback_tone": "kind",
  "timezone": "America/New_York",
  "current_streak": 4
}
```

`avatar` is `null` until one is set. `current_streak` is your [streak](#streaks) right now (0 if it lapsed).

### Update your profile

`PATCH /users/me` 🔒

Send **only the fields you want to change**. Omitted fields stay the same. Send `null` to clear `full_name`, `bio`, or `avatar_image_id`.

| Field | Rules |
|---|---|
| `username` | Same rules as sign-up. Can't be `null`. |
| `full_name` | Up to 100 characters. |
| `bio` | Up to 160 characters. |
| `avatar_image_id` | An image `id` from [Upload an image](#upload-an-image). |
| `style_tags` | Up to 3 of `minimal`, `tailored`, `streetwear`, `y2k`, `romantic`, `sporty`. |
| `fit_preference` | `fitted`, `true`, or `relaxed`. |
| `top_size`, `bottom_size` | `XS`, `S`, `M`, `L`, or `XL` (US sizing). |
| `feedback_tone` | How your circle should talk to you: `honest`, `kind`, or `hype`. |
| `timezone` | IANA name from the device, e.g. `America/New_York` (default `UTC`). Streak days and quiet hours follow it. Send it on every app start: `Intl.DateTimeFormat().resolvedOptions().timeZone`. Unknown names are `422`. |

The style profile fields come from the onboarding quiz and are returned by `GET /users/me`.

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
  "created_at": "2026-10-19T20:23:53.343519Z",
  "current_streak": 4
}
```

- `is_following` — whether **you** follow them (always `false` on your own profile).
- `current_streak` — their [streak](#streaks) right now.
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

### Blur the faces in an image

`POST /images/{image_id}/blur-faces` 🔒

Makes a **copy** of one of your images with every face blurred, for example a try-on result someone wants to post without showing their face. No body. Takes a few seconds (a Gemini model finds the faces).

- Post the returned image's `id` with [Post a fit](#post-a-fit) instead of the original. The original is unchanged.
- The copy keeps `generated`, so a blurred try-on is still labeled as AI.
- Each call makes a new copy: keep the result rather than calling again when the user toggles back and forth.

**Responses:** `201` (an image object, as above) · `404` `{"detail": "Image not found"}` (doesn't exist or isn't yours) · `422` `{"detail": "No face found in this photo"}` · `503` `{"detail": "Face blurring is temporarily unavailable"}`.

Only treat the face as hidden after a `201`.

---

## Virtual try-on

### Generate a try-on

`POST /tryons` 🔒

Puts clothes onto a photo of you, using a Google image model. There are two modes, which map to an **Entire fit / Pieces** toggle in the UI:

- **Entire fit**: one photo of a whole outfit (on its own, or worn by someone). Send `outfit_image_id`.
- **Pieces**: separate photos combined into one outfit, e.g. a top from one photo, jeans from another, and shoes from a third. Send `pieces`.

1. Upload the photos with [Upload an image](#upload-an-image): a photo of yourself, plus the outfit photo or each piece's photo.
2. Call this endpoint. **It takes a while, often 10–30 seconds, and longer with more pieces**: show progress, and don't time out the request early.
3. To post the result, [create a fit](#post-a-fit) with `result_image.id` in `image_ids`, and `tryon_id` set to the try-on's `id` so others can [try the same look](#try-this-look).

| Field | Required | Rules |
|---|---|---|
| `person_image_id` | yes | An image you uploaded. A clear photo of one person works best, ideally full-body. |
| `outfit_image_id` | one of these two | Entire-fit mode. An image you uploaded. |
| `pieces` | one of these two | Pieces mode. 1–7 items of `{ "slot": ..., "image_id": ... }`. |
| `fit_id` | no | [Try this look](#try-this-look): the fit being copied. Its clothing photos may then be used even though someone else uploaded them. |

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
| `400` | `"Image not found"` | An id doesn't exist or isn't yours (or, with `fit_id`, isn't one of that fit's clothing photos). |
| `403` | `"Try-ons are turned off for this fit"` | With `fit_id`: the poster turned off try-ons for it, or it's in their vault. |
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

### Try this look

Lets a viewer try a posted fit's clothes on themselves.

1. **Posting a try-on:** send `tryon_id` with [Post a fit](#post-a-fit). The fit then has a `try_on_source` (see [the fit object](#the-fit-object)) with the try-on's clothing photos: the outfit photo, or each piece and its slot. **The poster's own photo is never shared.**
2. **Trying it:** open the try-on screen with those clothing photos already filled in (`try_on_source.mode` picks Entire fit or Pieces). For a fit with no `try_on_source`, use its cover photo as the outfit. The viewer adds their own photo.
3. Call [Generate a try-on](#generate-a-try-on) with those image ids and `fit_id` set to the fit's id. The viewer can still swap any piece for a photo of their own.

`try_on_source` is `null` when the fit didn't come from a try-on or the poster turned off `allow_friend_try_on`. Calls with `fit_id` are refused (`403`) when try-ons are off or the fit is in the poster's vault.

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
  "poll": {
    "question": "Would you wear it?",
    "options": [{ "label": "Wear it", "votes": 9 }, { "label": "Rethink", "votes": 3 }],
    "total_votes": 12,
    "my_vote": 0,
    "locked": true
  },
  "try_on_source": null,
  "created_at": "2026-10-19T20:23:53.789725Z"
}
```

- `images` are in display order (first = cover).
- `liked_by_me` / `saved_by_me` / `poll.my_vote` are for **the current user**.
- `poll` is `null` when the poster chose no poll. Otherwise each answer has the tally everyone sees; `my_vote` is the index of your answer or `null`, and `locked` is `true` once anyone has voted (the poll can't change then). See [Voting](#voting).
- `try_on_source` is set when the fit was posted from a try-on and its author allows try-ons: `{ "mode": "outfit" | "pieces", "outfit_image": image | null, "pieces": [{ "slot", "image" }] }`, the same shapes as a try-on's. See [Try this look](#try-this-look).
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
| `tryon_id` | no | Posting a try-on: the try-on's `id`, so others can [try this look](#try-this-look). Must be one of your try-ons, or `400 "Try-on not found"`. |
| `poll` | no | `{ "question": "Rate this fit", "options": ["Fire", "Solid", "Meh"] }`: a question (1–100 characters) and 2–4 different answers (1–30 characters each). Left out: "Would you wear it?" with "Wear it" / "Rethink". `null`: no poll. |

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

Suggests the clothing pieces and occasion/style tags in one of your photos, so people don't have to tag them by hand. Takes a few seconds: call it right after uploading the cover photo (or right after a [try-on](#virtual-try-on), with `result_image.id`), while the user writes the caption.

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
      "url": null,
      "pin": { "image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26", "x": 0.508, "y": 0.501 },
      "source": "detected"
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
      "source": "detected"
    }
  ],
  "occasion_tags": ["casual", "gym"],
  "style_tags": ["minimalist", "sporty"],
  "model": "gemini-3.1-flash-lite"
}
```

- `items` are already in the shape [Post a fit](#post-a-fit) accepts. Show them as editable suggestions, then send the ones the user keeps, plus the tags, in `POST /fits`.
- `pin` marks where the piece is on this image (`null` if the model didn't locate it). Brands are never guessed.
- **Shop links:** `url` is always `null`; there's no automatic product search. Let the user paste a link to where they bought each piece (any `http(s)` link) before posting.
- The result is stored per image: asking again for the same image returns it instantly.
- A photo the model won't process returns empty lists, not an error.

**Responses:** `200` ↑ · `400` `{"detail": "Image not found"}` · `429` daily limit reached (default 200 new images per day) · `503` `{"detail": "Piece detection is temporarily unavailable"}` or `"Piece detection isn't set up on this server"`: let the user tag pieces by hand.

### Get a fit

`GET /fits/{fit_id}` 🔒 → [the fit object](#the-fit-object), or `404` `{"detail": "Fit not found"}`.

### Edit your fit

`PATCH /fits/{fit_id}` 🔒

Send any of `caption`, `items`, `occasion_tags`, `style_tags`, `poll`. Omitted fields stay the same. **Lists replace the whole list**: send every item or tag you want to keep (send `[]` to remove all). Photos can't be changed after posting. `poll` replaces the poll (`null` removes it), but only until someone votes (`poll.locked`); sending the same poll again is fine.

**Responses:** `200` with the updated fit · `400` `{"detail": "Each item pin must reference one of the fit's images"}` · `403` `{"detail": "You can only change your own fits"}` · `404` · `409` `{"detail": "The poll can't change after people have voted"}`.

### Delete your fit

`DELETE /fits/{fit_id}` 🔒 → `204`. Also deletes the fit's photos (unless one is your avatar or in one of your stories). `403` if it's not yours, `404` if it doesn't exist.

### List a user's fits

`GET /users/{username}/fits?limit=20&cursor=...` 🔒 → [page](#pagination) of fits, newest first.

---

## Privacy tiers

Every fit has a `privacy_tier`, and every account has a default for new posts.

| Tier | Explore feed | Following feed | Author's profile (others) | Author |
|---|---|---|---|---|
| `public` | yes | yes | yes | yes |
| `close_friends` | no | yes | yes | yes |
| `vault` (private drafts) | no | no | no | yes |

- Set it when posting (`privacy_tier` on `POST /fits`, default `public`) or later with
  `PATCH /fits/{id}/privacy` `{"privacy_tier": "close_friends", "allow_friend_try_on": false}` → the fit.
- `allow_friend_try_on` (default `true`) controls whether others can [try this look](#try-this-look); vault fits never can.
- `GET /users/me/privacy` → `{"default_closet_privacy": "public"}`; `PATCH /users/me/privacy` with the same shape changes it.
- Vault fits don't count toward your [streak](#streaks).
- [Stories](#stories) use `public` and `close_friends` too, but there "close friends" means **people you follow
  who follow you back**, and close-friends stories are hidden from everyone else.

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

## Voting

Answering a fit's poll — "Would you wear it?" unless the poster picked their own
question and answers (see `poll` on [Post a fit](#post-a-fit)).

| Action | Request | Response |
|---|---|---|
| Vote | `PUT /fits/{fit_id}/vote` | `200` → [the fit object](#the-fit-object) |
| Retract | `DELETE /fits/{fit_id}/vote` | `200` → [the fit object](#the-fit-object) |

- Both 🔒. `404` `{"detail": "Fit not found"}` if the fit doesn't exist.
- **Request body** (vote only): `{"option": 0}`, the index of the answer in `poll.options`.
  Past the last answer: `400` `{"detail": "No such poll answer"}`. A fit posted without a
  poll: `409` `{"detail": "This fit has no poll"}`.
- **One vote per person per fit.** Voting again replaces your previous choice rather
  than adding a second vote, so both calls are idempotent. Retracting when you never
  voted is a no-op, not an error.
- Unlike likes and saves, these return **the whole fit** instead of `204`, so you can
  redraw the result bar from the authoritative tallies without a second request.
- Anyone who can see a fit can vote on it, including its author.

```ts
// Optimistic vote, reconciled with the server's tallies
async function vote(fit: Fit, option: number | null) {
  const previous = fit;
  setFit(optimisticVote(fit, option));   // move the bars straight away
  const res = await apiFetch(`/fits/${fit.id}/vote`, {
    method: option === null ? "DELETE" : "PUT",
    ...(option !== null && {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ option }),
    }),
  });
  if (!res.ok) return setFit(previous);  // roll back
  setFit(await res.json());              // real counts, including other people's
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
| Search | `GET /users/search?q=...&limit=20` | list of users matching query, including `is_following` |

All 🔒. Users in follower/following lists have the compact shape:

```json
{ "id": "...", "username": "bob", "full_name": null, "avatar": null }
```

To show a Follow/Following button for someone, read `is_following` from [Get a profile](#get-a-profile).

---

## Messaging

Direct chats and circles (group chats). Every endpoint is 🔒 and only works for members:
anyone else gets `404 {"detail": "Conversation not found"}`.

### Your circle

People you follow or who follow you. Chats can only be started with them.

- `GET /conversations/circle` → `[{ "user", "online", "last_seen_at", "has_live_fit_check", "has_active_story", "has_unseen_story" }]`
  (`has_live_fit_check`: posted a fit in the last 24 hours; `has_active_story`: has a [story](#stories) you can see;
  `has_unseen_story`: one of those you haven't viewed — draw the story ring).
- `GET /users/search?q=&scope=circle` searches only your circle. Without `scope` it searches everyone.
- `GET /users/suggestions?limit=6` → people you don't follow, most mutual follows first, each with `mutual_count`.

### Conversations

| Action | Request | Response |
|---|---|---|
| List | `GET /conversations` | `200` → conversations, most recent activity first |
| Start | `POST /conversations` `{"type": "direct" \| "circle", "member_ids": [...], "title": null}` | `201` new, or `200` an existing direct chat |
| Get one | `GET /conversations/{id}` | `200` |
| Mute / rename | `PATCH /conversations/{id}` `{"muted": true}` or `{"title": "..."}` (circles only) | `200` |
| Leave / hide | `DELETE /conversations/{id}` | `204`: leaves a circle; hides a direct chat until its next message |
| Mark read | `POST /conversations/{id}/read` | `200` receipt |
| Mark delivered | `POST /conversations/{id}/delivered` | `200` receipt |

A conversation:

```json
{
  "id": "...", "type": "circle", "title": "Gallery night", "created_at": "...",
  "muted": false, "unread_count": 2, "last_activity_at": "...",
  "members": [{ "user": { "id": "...", "username": "maya", "full_name": "Maya Chen", "avatar": null },
                "role": "member", "online": true, "last_seen_at": "...",
                "last_read_at": "...", "last_delivered_at": "..." }],
  "last_message": { "...": "a message" }
}
```

`member_ids` excludes you. A direct chat has exactly one; a circle up to 31. Members must be in
your circle (`403` otherwise).

### Messages

`GET /conversations/{id}/messages?before=<next_cursor>&limit=30` → `{ "items", "next_cursor" }`, newest first.

`POST /conversations/{id}/messages`:

| `kind` | Fields |
|---|---|
| `text` | `body` (1-2000 characters) |
| `image` | `image_id` from [Upload an image](#upload-an-image) (10 MB cap), optional `body` |
| `fit_check` | `image_id`, `question` (up to 280), optional `context` ("Vernissage · 18°C") and `fit_id` |
| `product` | `product: { name, color, price, url, image_id }`, optional `body` |

A fifth kind, `story_reply`, only arrives from [Reply to a story](#reply-to-a-story); you can't send it here (`422`).
Its `body` is the reply and `payload` is `{ "story_id", "caption", "image" }`. `image` becomes `null`
about a week after the story expires: show "Story unavailable".
Also send a `client_id` (any string up to 64 characters): retrying with the same one returns the
stored message instead of sending twice. Text is trimmed and stripped of control and invisible
characters. Sending more than 20 messages in 10 seconds returns `429`.

**Errors:** `400 "Image not found"` (not your image) · `404 "Conversation not found"` (not a member) ·
`409 "client_id was already used in another conversation"` · `422` validation (missing fields for the
`kind`, body over 2000 characters) · `429 "You're sending messages too fast. Wait a moment."`

A message:

```json
{
  "id": "...", "conversation_id": "...", "sender": { "...": "user summary" },
  "kind": "fit_check", "body": "Too dressed up?", "client_id": "c-123",
  "payload": { "image": { "...": "image" }, "question": "Too dressed up?", "context": "Vernissage · 18°C", "fit_id": null },
  "votes": { "wear": 2, "rethink": 1, "total": 3, "wear_pct": 67, "rethink_pct": 33, "my_vote": "wear" },
  "created_at": "...", "edited_at": null, "deleted_at": null
}
```

- `POST /messages/{id}/vote` `{"vote": "wear" | "rethink"}` → the new tally. One vote per member; voting again replaces it.
- `DELETE /messages/{id}` → `204`. Sender only (`403` otherwise). The message stays with `deleted_at` set and `body`/`payload` cleared.

**Delivery and read state** of your own messages: compare a message's `created_at` with the other
members' `last_delivered_at` and `last_read_at`.

### Realtime

Open a WebSocket to `/api/v1/ws` and send `{"type": "auth", "token": "<access token>"}` first
(within 10 seconds; a bad token closes with code `4401`). After `{"type": "ready"}` the server pushes:

| Event | Fields |
|---|---|
| `message:new` | `message` |
| `message:deleted` | `conversation_id`, `message_id` |
| `vote:update` | `message_id`, `conversation_id`, tallies |
| `receipt:update` | `conversation_id`, `user_id`, `last_read_at`, `last_delivered_at` |
| `typing:start` / `typing:stop` | `conversation_id`, `user_id` |
| `presence:update` | `user_id`, `online`, `last_seen_at` |
| `conversation:update` | `conversation_id` (created, renamed, someone left): refetch it |
| `story:new` | `story_id`, `user` — someone in your circle posted a story you can see: refetch the story feed |
| `story:viewed` | `story_id`, `viewer`, `view_count` — to the owner, on someone's first view |
| `notification:new` | `notification` ([the notification object](#notifications)) |
| `notification:count` | `unread` — after any change to your unread notifications |

Send `{"type": "typing:start" | "typing:stop", "conversation_id": "..."}` and `{"type": "ping"}`
(answered with `pong`). Reconnect with a fresh token after it expires. Events go to sockets on the
same server process, so run one worker (or add a shared broker) until that changes.

**After reconnecting**, catch up with `GET /conversations` (unread counts and last messages) and
`GET /conversations/{id}/messages` for the open chat: messages sent while you were away are
not replayed over the socket.

---

## Stories

Photos shared for 24 hours with your circle. Every endpoint is 🔒. Stories you aren't allowed to
see, expired ones, and deleted ones all return `404 {"detail": "Story not found"}`.

**Who sees a story:** `public` stories are shown to your circle in the feed and to anyone who opens
your profile; `close_friends` stories only to people you follow who follow you back.

### The story object

```json
{
  "id": "6f1c...", "user_id": "3a2f...",
  "image": { "id": "...", "width": 1080, "height": 1920, "generated": false, "url": "http://localhost:8000/media/images/....webp" },
  "caption": "Gallery night", "fit_id": null, "visibility": "public",
  "created_at": "2026-11-09T20:00:00Z", "expires_at": "2026-11-10T20:00:00Z",
  "seen": false, "view_count": null
}
```

`seen` is whether you viewed it (always `true` for your own). `view_count` is only set on your own stories.

### Post a story

`POST /stories` 🔒

| Field | Required | Rules |
|---|---|---|
| `image_id` | yes | From [Upload an image](#upload-an-image). To hide faces, [blur them](#blur-the-faces-in-an-image) first and send the blurred copy's id. |
| `caption` | no | Up to 200 characters. |
| `fit_id` | no | One of your fits, not in your vault. |
| `visibility` | no | `public` (default) or `close_friends`. |

```json
{ "image_id": "16cc86b0-3f41-48af-b5b2-1ba3a3e36c26", "caption": "Gallery night", "visibility": "close_friends" }
```

**Responses:** `201` story · `400 "Image not found"` · `400 "Fit not found"` · `409 "You can have at most 20 active stories"` · `422` validation.
Posting a story counts toward your [streak](#streaks) and sends `story:new` to your audience.

### Story feed

`GET /stories/feed` 🔒 → groups, one per person in your circle with active stories you can see:

```json
[
  {
    "user": { "id": "...", "username": "jane", "full_name": "Jane", "avatar": null },
    "stories": [ { "...": "story, oldest first" } ],
    "has_unseen": false,
    "latest_at": "2026-11-09T20:00:00Z"
  }
]
```

Order: **your own group first** (if you have stories), then people with unseen stories, then everyone
else; within each, most recent first.

### A user's stories

`GET /users/{user_id}/stories` 🔒 → one group (as above) with the stories you can see, `stories: []` when there are none. `404 "User not found"`.

### View, viewers, delete

| Action | Request | Response |
|---|---|---|
| Mark seen | `POST /stories/{id}/view` | `204`. Idempotent; your own views aren't counted. The owner gets `story:viewed`. |
| Viewers | `GET /stories/{id}/viewers?limit=20&cursor=` | `200` `{ "items": [{ "user", "viewed_at" }], "next_cursor" }`, newest first. Owner only: `403 "Only the story's owner can do that"`. |
| Delete | `DELETE /stories/{id}` | `204`. Owner only (`403`). |

### Reply to a story

`POST /stories/{id}/reply` 🔒 `{"body": "Obsessed with this", "client_id": "optional"}`

Sends a `story_reply` message into your direct chat with the owner, creating the chat if needed, and
returns the [message](#messages) (`201`). The owner gets a `story_reply` notification.

**Errors:** `400 "You can't reply to your own story"` · `403 "You can only chat with people in your circle"` · `404` · `409` (client_id reused elsewhere) · `422` (empty body) · `429`.

---

## Streaks

A day counts when you **post a fit** (not vault), **post a story**, or **send a fit check**, using your
local calendar day (`timezone` on [your account](#update-your-profile)).

- Each 7 days in a row earns a **freeze** (max 2). Missing one day uses a freeze automatically and keeps the streak.
- Missing two days in a row, or one day with no freeze, ends it; your next activity starts again at 1.
- Milestones: 3, 7, 14, 30, 50, 100, 365.

`GET /users/me/streak` 🔒

```json
{ "current": 8, "longest": 21, "active_today": false, "freezes_available": 1, "hours_left_today": 5.25, "next_milestone": 14 }
```

`hours_left_today` counts down to your local midnight (23 or 25 hours on daylight-saving change days).
Your current streak is also on `GET /users/me` and everyone's profile as `current_streak`.

Notifications: `streak_milestone`, `streak_reminder` (between 19:00 and 20:00 your time when you have a 2+ day
streak and haven't counted today, once a day), `streak_saved` (a freeze was used), `streak_lost`.

---

## Notifications

Every endpoint is 🔒.

### The notification object

```json
{
  "id": "9b0e...",
  "type": "fit_vote",
  "actor": { "id": "...", "username": "maya", "full_name": "Maya", "avatar": null },
  "actors": [ { "...": "Maya" }, { "...": "Leo" } ],
  "actor_count": 4,
  "entity_type": "fit",
  "entity_id": "44bf...",
  "title": "New votes",
  "body": "Maya and 3 others voted on your fit",
  "link": "/fits/44bf...",
  "data": {},
  "read": false,
  "created_at": "2026-11-09T20:00:00Z"
}
```

Show `title`/`body` as they are and navigate to `link` on tap. Likes, fit votes, fit-check votes and story
view milestones on the same item within 24 hours **merge into one row**: it moves back to the top and
becomes unread when someone new joins it.

| `type` | When | `link` |
|---|---|---|
| `follow` | Someone followed you | `/users/{username}` |
| `like` | Liked your fit (grouped) | `/fits/{id}` |
| `comment` | Commented on your fit (`data.preview`) | `/fits/{id}` |
| `fit_vote` | Voted on your fit (grouped) | `/fits/{id}` |
| `fit_check_vote` | Voted on your fit check (grouped) | `/conversations/{id}?message={message_id}` |
| `story_reply` | Replied to your story | `/conversations/{id}` |
| `story_view_milestone` | Your story reached 10, 50, or 100 viewers (`data.viewers`) | `/stories/{id}/viewers` |
| `circle_added` | Added you to a circle | `/conversations/{id}` |
| `message` | A message while you had no open socket | `/conversations/{id}` |
| `streak_reminder`, `streak_milestone`, `streak_saved`, `streak_lost` | See [Streaks](#streaks) (`data.count`) | `/streak` |

You're never notified about your own actions, or about muted conversations.

### Endpoints

| Action | Request | Response |
|---|---|---|
| List | `GET /notifications?limit=20&cursor=` | `200` page, newest first. `400 "Invalid cursor"` |
| Unread count | `GET /notifications/unread-count` | `200` `{"unread": 3}` |
| Mark read | `POST /notifications/read` `{"ids": ["..."]}` or `{"all": true}` | `200` `{"unread": 0}`. Sending neither or both is `422`. |
| Settings | `GET /users/me/notification-settings` | `200` (below) |
| Change settings | `PATCH /users/me/notification-settings` | `200`. Send only what changes. |

```json
{ "social": true, "messages": true, "stories": true, "streaks": true,
  "quiet_hours_start": "22:00:00", "quiet_hours_end": "07:30:00", "timezone": "America/New_York" }
```

Settings control **push**; everything still appears in the in-app list. Groups: `social` (follow, like,
comment, fit_vote, fit_check_vote, circle_added), `messages` (message), `stories` (story_reply,
story_view_milestone), `streaks` (the four streak types). Quiet hours are local times and can wrap midnight;
send both, or both `null` to turn them off (`422` if only one is sent).

---

## Devices and push

| Action | Request | Response |
|---|---|---|
| Register / refresh | `POST /devices` `{"platform": "ios" \| "android", "token": "...", "app_version": "1.4.0"}` | `200` `{ "platform", "token", "app_version", "created_at", "last_seen_at" }` |
| Remove (logout) | `DELETE /devices/{token}` | `204`. Idempotent; only removes your own token. |

Register after login and on every app start (it's an upsert by `token`; a token registered by another
account moves to you). iOS sends the APNs device token as hex; Android sends the FCM registration token.

Every notification is also pushed to your devices unless its group is off or it's quiet hours. Pushes
for the same item replace each other (APNs `apns-collapse-id`, FCM `collapse_key`). The iOS badge is
unread notifications plus unread messages. Each push carries `data`: `{ "notification_id", "type", "link" }`.

---

## Wardrobe

Your digital closet with cost-per-wear. Every endpoint is 🔒 and only sees your own items;
others' or missing ids are `404 {"detail": "Wardrobe item not found"}`.

| Action | Request | Response |
|---|---|---|
| List | `GET /wardrobe?category=shoes` (`shoes`, `clothing`, `accessories`; optional) | `200` items, newest first |
| Summary | `GET /wardrobe/summary` | `200` `{ "total_pieces", "total_valuation", "average_cost_per_wear", "shoes_count", "clothing_count", "accessories_count" }` |
| Add | `POST /wardrobe` | `201` item |
| Get | `GET /wardrobe/{id}` | `200` item |
| Edit | `PATCH /wardrobe/{id}` (only fields sent) | `200` item |
| Log a wear | `POST /wardrobe/{id}/wear` | `200` item with `times_worn + 1` and `last_worn_at` now |
| Delete | `DELETE /wardrobe/{id}` | `204` |

```json
{ "primary_category": "shoes", "name": "Retro Metallic Silver Runners", "brand": "Onitsuka", "sub_category": "sneakers",
  "color": "silver", "price": 140, "times_worn": 3, "tag": "daily", "image_url": "https://...", "notes": null }
```

An item adds `id`, `user_id`, `cost_per_wear` (price / wears), `last_worn_at`, `created_at`, `updated_at`.
`name` is 1-120 characters; `price` and `times_worn` can't be negative.

---

## Memories

A daily outfit log for the calendar. Every endpoint is 🔒; other people's ids are `404 {"detail": "Outfit memory not found"}`.

| Action | Request | Response |
|---|---|---|
| List | `GET /memories?year=2026&month=11` (both optional) | `200` memories, newest date first |
| Log | `POST /memories` | `201` memory |
| Get | `GET /memories/{id}` | `200` |
| Delete | `DELETE /memories/{id}` | `204` |

```json
{ "date": "2026-11-02", "title": "Monday Studio Critique", "photo_url": null, "notes": "Felt sharp",
  "weather": "12°C, cloudy", "rating": 4, "tagged_pieces": ["Silver Runners"], "auto_log_wear": true }
```

`date` is `YYYY-MM-DD`; `rating` 1-5 (default 5). With `auto_log_wear` (default `true`), each tagged piece
that matches one of your wardrobe item names logs a wear on that item.

---

## Sizing (TrueSize Passport)

Benchmark garments that fit you, used to recommend sizes at other brands. Every endpoint is 🔒.

| Action | Request | Response |
|---|---|---|
| Your passport | `GET /sizing/passport` | `200` `{ "user_id", "benchmarks_count", "top_brands", "items", "calibrated_baseline" }` |
| Add a benchmark | `POST /sizing/passport` | `201` garment |
| Remove one | `DELETE /sizing/passport/{id}` | `204` · `404 "Reference garment not found"` |
| Recommend a size | `POST /sizing/translate` | `200` recommendation |

```json
{ "brand": "Levi's", "category": "bottoms", "item_name": "501 Original Fit", "size": "30W 32L", "fit_feeling": "perfect", "is_favorite": true }
```

`category`: `tops`, `bottoms`, `dresses`, `outerwear`, `shoes`, `other`. `fit_feeling`: `perfect`, `snug`, `oversized`.

Translate request `{ "target_brand": "Zara", "category": "tops", "target_item_fit_pref": "standard", "target_item_name": null, "product_url": null }`
(`target_item_fit_pref`: `standard`, `relaxed`, `snug`) returns `{ "target_brand", "category", "recommended_size",
"confidence_score" (50-99), "alternative_size", "brand_calibration_note", "fabric_stretch_advice",
"matched_reference_pieces", "avoided_return_risk" }`.

---

## Impact

Returns you avoided, in dollars and CO₂. Every endpoint is 🔒.

- `GET /impact` → `{ "user_id", "total_dollars_saved", "returns_prevented_count", "post_office_trips_avoided", "co2_kg_saved", "milestone_badge", "milestone_progress_pct", "recent_saves" }`
- `POST /impact/record` → `201` record (`id`, the fields below, `dollars_saved`, `co2_saved_kg`, `created_at`):

```json
{ "item_name": "Oversized Wool Trench", "brand": "Aritzia", "category": "outerwear", "estimated_price": 148,
  "action_type": "size_corrected", "fit_id": null, "notes": null }
```

`action_type`: `size_corrected`, `avoided_bad_cut`, `fit_check_voted_rethink`, `confirmed_first_try`,
`stolen_from_friend`. `estimated_price` is 1-5000 (default 75).

---

## Health

### Health check

`GET /health`

```json
{ "status": "ok", "version": "0.1.0", "environment": "development", "database": "ok" }
```

Useful to check the backend is up. `database` is `"unavailable"` if the API can't reach the database.
