# Frontend contract: stories, streaks, notifications, devices, story replies

The exact payloads the app builds against. Everything is under `/api/v1`, needs
`Authorization: Bearer <access token>`, uses UUID strings for ids, and ISO 8601 UTC timestamps
(`2026-11-10T03:06:11.659704Z`). Errors follow [API.md › Errors](API.md#errors). The examples below
were captured from the running API.

## Shared types

```ts
type UUID = string;
type Timestamp = string; // ISO 8601, UTC

interface Image { id: UUID; width: number; height: number; generated: boolean; url: string }
interface UserSummary { id: UUID; username: string; full_name: string | null; avatar: Image | null }
interface Page<T> { items: T[]; next_cursor: string | null } // send next_cursor back as ?cursor=
```

---

## Stories

```ts
type StoryVisibility = "public" | "close_friends";

interface Story {
  id: UUID;
  user_id: UUID;
  image: Image;
  caption: string | null;
  fit_id: UUID | null;
  visibility: StoryVisibility;
  created_at: Timestamp;
  expires_at: Timestamp;   // created_at + 24h
  seen: boolean;           // true for your own
  view_count: number | null; // only on your own stories
}

interface StoryGroup {
  user: UserSummary;
  stories: Story[];        // oldest first: play in this order
  has_unseen: boolean;
  latest_at: Timestamp | null; // null only from GET /users/{id}/stories with no stories
}

interface StoryViewer { user: UserSummary; viewed_at: Timestamp }
```

| Call | Body | Success | Errors |
|---|---|---|---|
| `POST /stories` | `{ image_id, caption?, fit_id?, visibility? }` | `201 Story` | `400 "Image not found"`, `400 "Fit not found"`, `409 "You can have at most 20 active stories"`, `422` |
| `GET /stories/feed` | | `200 StoryGroup[]` | |
| `GET /users/{user_id}/stories` | | `200 StoryGroup` | `404 "User not found"` |
| `POST /stories/{id}/view` | | `204` | `404 "Story not found"` |
| `GET /stories/{id}/viewers?limit&cursor` | | `200 Page<StoryViewer>` | `403 "Only the story's owner can do that"`, `404`, `400 "Invalid cursor"` |
| `DELETE /stories/{id}` | | `204` | `403`, `404` |
| `POST /stories/{id}/reply` | `{ body, client_id? }` | `201 Message` (kind `story_reply`) | `400 "You can't reply to your own story"`, `403 "You can only chat with people in your circle"`, `404`, `409`, `422`, `429` |

`POST /stories` request:

```json
{ "image_id": "d7868e3f-e7fc-47b6-9a2b-8cc328db43e1", "caption": "Gallery night", "visibility": "close_friends" }
```

`201` response:

```json
{
  "id": "185b8a42-45f0-4dce-af83-bc711abd06a2",
  "user_id": "5f108eaa-5053-46f1-95e8-bc605636bab8",
  "image": {
    "id": "d7868e3f-e7fc-47b6-9a2b-8cc328db43e1",
    "width": 1080,
    "height": 1920,
    "generated": false,
    "url": "http://localhost:8000/media/images/9126d2ef87104ab88631a456f41dc5ee.webp"
  },
  "caption": "Gallery night",
  "fit_id": null,
  "visibility": "close_friends",
  "created_at": "2026-11-10T03:06:11.659704Z",
  "expires_at": "2026-11-11T03:06:11.659704Z",
  "seen": true,
  "view_count": 0
}
```

`GET /stories/feed`, as a close friend sees it:

```json
[
  {
    "user": { "id": "5f108eaa-5053-46f1-95e8-bc605636bab8", "username": "maya", "full_name": "Maya Chen", "avatar": null },
    "stories": [
      {
        "id": "185b8a42-45f0-4dce-af83-bc711abd06a2",
        "user_id": "5f108eaa-5053-46f1-95e8-bc605636bab8",
        "image": { "id": "d7868e3f-e7fc-47b6-9a2b-8cc328db43e1", "width": 1080, "height": 1920, "generated": false, "url": "http://localhost:8000/media/images/9126d2ef87104ab88631a456f41dc5ee.webp" },
        "caption": "Gallery night",
        "fit_id": null,
        "visibility": "close_friends",
        "created_at": "2026-11-10T03:06:11.659704Z",
        "expires_at": "2026-11-11T03:06:11.659704Z",
        "seen": false,
        "view_count": null
      }
    ],
    "has_unseen": true,
    "latest_at": "2026-11-10T03:06:11.659704Z"
  }
]
```

`GET /stories/{id}/viewers`:

```json
{
  "items": [
    { "user": { "id": "752c3d22-bb91-47eb-ba98-e86e1fabf71d", "username": "leo", "full_name": "Leo Park", "avatar": null },
      "viewed_at": "2026-11-10T03:06:11.684591Z" }
  ],
  "next_cursor": null
}
```

**Rules the UI relies on**

- Feed order is final: your own group first, then groups with `has_unseen`, then the rest, each most recent first. Don't re-sort.
- Call `POST /stories/{id}/view` when a story is shown; it's idempotent, so calling it again is fine.
- Story rings in the circle strip: `GET /conversations/circle` items have `has_active_story` and `has_unseen_story`.
- "Close friends" are mutual follows. A `close_friends` story is invisible (`404`) to everyone else.
- Face blur: `POST /images/{id}/blur-faces` returns a new image; post the story with that new id.
- Hide a story once `expires_at` has passed, even if the feed hasn't been refetched yet.

---

## Story replies (message kind `story_reply`)

A `story_reply` message appears in `GET /conversations/{id}/messages`, in `last_message`, and in
`message:new` events like any other message. Clients can't send it with `POST /conversations/{id}/messages` (`422`).

```ts
interface StoryReplyPayload {
  story_id: UUID;
  caption: string | null;
  image: Image | null; // null once the story is cleaned up (7 days after it expires)
}
```

`POST /stories/{id}/reply` request `{ "body": "Obsessed", "client_id": "c-1" }` → `201`:

```json
{
  "id": "7afd4f1e-85f2-4e3a-a5aa-96706b1c7e33",
  "conversation_id": "ce20699f-7922-43ea-913d-46db2e51cb6c",
  "sender": { "id": "752c3d22-bb91-47eb-ba98-e86e1fabf71d", "username": "leo", "full_name": "Leo Park", "avatar": null },
  "kind": "story_reply",
  "body": "Obsessed",
  "payload": {
    "story_id": "185b8a42-45f0-4dce-af83-bc711abd06a2",
    "caption": "Gallery night",
    "image": { "id": "d7868e3f-e7fc-47b6-9a2b-8cc328db43e1", "width": 1080, "height": 1920, "generated": false, "url": "http://localhost:8000/media/images/9126d2ef87104ab88631a456f41dc5ee.webp" }
  },
  "client_id": "c-1",
  "created_at": "2026-11-10T03:06:11.708394Z",
  "edited_at": null,
  "deleted_at": null,
  "votes": null
}
```

Render it as a quoted story thumbnail above `body`. If `payload.image` is `null`, or the story has
expired, show "Story unavailable" and don't link to it. A deleted reply has `payload: null` and
`body: null`, like any deleted message. Retrying with the same `client_id` returns the same message.

---

## Streaks

```ts
interface Streak {
  current: number;
  longest: number;
  active_today: boolean;
  freezes_available: number;   // 0-2
  hours_left_today: number;    // hours to local midnight, 2 decimals
  next_milestone: number | null; // 3, 7, 14, 30, 50, 100, 365
}
```

`GET /users/me/streak` → `200`:

```json
{ "current": 1, "longest": 1, "active_today": true, "freezes_available": 0, "hours_left_today": 1.9, "next_milestone": 3 }
```

- `GET /users/me` and `GET /users/{username}` include `current_streak: number`.
- Send the device timezone on every app start: `PATCH /users/me { "timezone": "America/New_York" }`
  (from `Intl.DateTimeFormat().resolvedOptions().timeZone`). Unknown names return `422`.
- A day counts for a fit post (not vault), a story, or a fit check. Refetch the streak after any of those.

---

## Notifications

```ts
type NotificationType =
  | "follow" | "like" | "comment" | "fit_vote" | "fit_check_vote"
  | "story_reply" | "story_view_milestone" | "circle_added" | "message"
  | "streak_reminder" | "streak_milestone" | "streak_saved" | "streak_lost";

interface AppNotification {
  id: UUID;
  type: NotificationType;
  actor: UserSummary | null;  // most recent person; null for streak and milestone types
  actors: UserSummary[];      // up to 2, for stacked avatars
  actor_count: number;        // people in a grouped row
  entity_type: "user" | "fit" | "message" | "story" | "conversation" | "streak" | null;
  entity_id: UUID | null;
  title: string;              // display as-is
  body: string;               // display as-is
  link: string;               // app route to open on tap
  data: Record<string, unknown>;
  read: boolean;
  created_at: Timestamp;
}

interface NotificationSettings {
  social: boolean; messages: boolean; stories: boolean; streaks: boolean;
  quiet_hours_start: string | null; // "22:00:00", local time
  quiet_hours_end: string | null;
  timezone: string;                 // read-only here; change it with PATCH /users/me
}
```

| Call | Body | Success | Errors |
|---|---|---|---|
| `GET /notifications?limit&cursor` | | `200 Page<AppNotification>`, newest first | `400 "Invalid cursor"` |
| `GET /notifications/unread-count` | | `200 { "unread": number }` | |
| `POST /notifications/read` | `{ "ids": UUID[] }` or `{ "all": true }` | `200 { "unread": number }` | `422` (neither or both) |
| `GET /users/me/notification-settings` | | `200 NotificationSettings` | |
| `PATCH /users/me/notification-settings` | any subset; quiet hours both or neither | `200 NotificationSettings` | `422` |

`GET /notifications`:

```json
{
  "items": [
    {
      "id": "06217beb-0af4-4b73-9dd0-8f2aaeba2e99",
      "type": "story_reply",
      "actor": { "id": "752c3d22-bb91-47eb-ba98-e86e1fabf71d", "username": "leo", "full_name": "Leo Park", "avatar": null },
      "actors": [ { "id": "752c3d22-bb91-47eb-ba98-e86e1fabf71d", "username": "leo", "full_name": "Leo Park", "avatar": null } ],
      "actor_count": 1,
      "entity_type": "story",
      "entity_id": "185b8a42-45f0-4dce-af83-bc711abd06a2",
      "title": "Story reply",
      "body": "Leo Park replied to your story: “Obsessed”",
      "link": "/conversations/ce20699f-7922-43ea-913d-46db2e51cb6c",
      "data": {
        "preview": "Obsessed",
        "conversation_id": "ce20699f-7922-43ea-913d-46db2e51cb6c",
        "message_id": "7afd4f1e-85f2-4e3a-a5aa-96706b1c7e33"
      },
      "read": false,
      "created_at": "2026-11-10T03:06:11.712845Z"
    },
    {
      "id": "6bed0195-37e2-4cb5-9b98-7cb9f8d55f3b",
      "type": "follow",
      "actor": { "id": "752c3d22-bb91-47eb-ba98-e86e1fabf71d", "username": "leo", "full_name": "Leo Park", "avatar": null },
      "actors": [ { "id": "752c3d22-bb91-47eb-ba98-e86e1fabf71d", "username": "leo", "full_name": "Leo Park", "avatar": null } ],
      "actor_count": 1,
      "entity_type": "user",
      "entity_id": "752c3d22-bb91-47eb-ba98-e86e1fabf71d",
      "title": "New follower",
      "body": "Leo Park started following you",
      "link": "/users/leo",
      "data": {},
      "read": false,
      "created_at": "2026-11-10T03:06:11.436815Z"
    }
  ],
  "next_cursor": null
}
```

A grouped row (likes, fit votes, fit-check votes, story view milestones on the same item within 24 hours):

```json
{ "type": "fit_vote", "actor_count": 4, "title": "New votes", "body": "Maya Chen and 3 others voted on your fit",
  "link": "/fits/44bf9a0f-d9a8-4755-970f-22d87197bb13", "entity_type": "fit", "entity_id": "44bf9a0f-d9a8-4755-970f-22d87197bb13" }
```

When someone new joins a grouped row, the same `id` comes back with a newer `created_at` and `read: false`,
via `notification:new`. Replace the row by `id` and move it to the top.

**`data` by type**

| `type` | `data` |
|---|---|
| `comment` | `{ comment_id, preview }` |
| `fit_check_vote` | `{ conversation_id }` (`entity_id` is the message) |
| `story_reply` | `{ preview, conversation_id, message_id }` |
| `story_view_milestone` | `{ viewers }` (10, 50 or 100) |
| `circle_added` | `{ title }` |
| `message` | `{ message_id, kind, preview, conversation_title }` (`conversation_title` only for circles) |
| `streak_reminder` | `{ count, hours_left }` |
| `streak_milestone`, `streak_lost` | `{ count }` |
| `streak_saved` | `{ count, freezes_left, date }` |
| others | `{}` |

**Links** the router must handle: `/users/{username}`, `/fits/{id}`, `/conversations/{id}`,
`/conversations/{id}?message={message_id}`, `/stories/{id}/viewers`, `/streak`.

`PATCH /users/me/notification-settings` request `{ "quiet_hours_start": "22:00", "quiet_hours_end": "07:30" }` → `200`:

```json
{ "social": true, "messages": true, "stories": true, "streaks": true,
  "quiet_hours_start": "22:00:00", "quiet_hours_end": "07:30:00", "timezone": "America/New_York" }
```

Settings only affect push. The in-app list always shows everything.

---

## Devices

```ts
interface DeviceRegister { platform: "ios" | "android"; token: string; app_version?: string | null }
interface Device { platform: "ios" | "android"; token: string; app_version: string | null; created_at: Timestamp; last_seen_at: Timestamp }
```

| Call | When | Success |
|---|---|---|
| `POST /devices` `DeviceRegister` | After login and on every app start (upsert) | `200 Device` |
| `DELETE /devices/{token}` | On logout, before dropping the access token | `204` (idempotent) |

```json
{ "platform": "ios", "token": "a1b2c3", "app_version": "1.4.0" }
```

```json
{ "platform": "ios", "token": "a1b2c3", "app_version": "1.4.0", "created_at": "2026-11-10T03:06:11.749032Z", "last_seen_at": "2026-11-10T03:06:11.749032Z" }
```

With Capacitor, `@capacitor/push-notifications` `registration` gives `token.value`: the hex APNs token on
iOS, the FCM token on Android. URL-encode the token in `DELETE`.

**Push payload** received by the app:

- iOS (APNs): `aps.alert.title` and `aps.alert.body` (same as the notification's `title`/`body`), `aps.badge` (unread
  notifications plus unread messages), `aps.sound: "default"`, `aps["thread-id"]`, plus top-level
  `notification_id`, `type`, `link`.
- Android (FCM): `notification.title`/`notification.body`, and `data: { notification_id, type, link }`.

On tap, open `link`. Pushes for the same item replace each other on the device.

---

## WebSocket events

On the existing socket (`/api/v1/ws`, see [API.md › Realtime](API.md#realtime)):

```json
{ "type": "story:new", "story_id": "185b8a42-…", "user": { "id": "…", "username": "maya", "full_name": "Maya Chen", "avatar": null } }
{ "type": "story:viewed", "story_id": "185b8a42-…", "viewer": { "id": "…", "username": "leo", "full_name": "Leo Park", "avatar": null }, "view_count": 1 }
{ "type": "notification:new", "notification": { "...": "AppNotification" } }
{ "type": "notification:count", "unread": 3 }
```

- `story:new` → refetch `GET /stories/feed` (and the circle strip).
- `story:viewed` → bump the viewer count on your own story; refetch viewers if that sheet is open.
- `notification:new` → upsert by `id` at the top of the list; show an in-app banner if you like.
- `notification:count` → set the bell badge. Sent after any new notification and after marking read.
- When the app is foregrounded with an open socket, `message` notifications aren't created for you; the
  `message:new` event covers it.
