"""End-to-end smoke test for messaging against a running server.

Creates fresh users, then exercises conversations, messages, receipts, realtime events,
votes, moderation limits and reconnect catch-up over HTTP and two live WebSockets, followed
by story replies, notifications, devices and streaks.

    python -m scripts.smoke_messaging http://localhost:8000

Exits non-zero if any step fails.
"""

import argparse
import asyncio
import io
import json
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from PIL import Image
from websockets.asyncio.client import ClientConnection, connect

PASSWORD = "smoke-test-passw0rd"
EVENT_TIMEOUT = 5.0


@dataclass
class Account:
    id: str
    username: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


class Socket:
    """A WebSocket whose events are read into a queue, so steps can wait for a specific one."""

    def __init__(self, connection: ClientConnection) -> None:
        self.connection = connection
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self.reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self.connection:
                await self.events.put(json.loads(raw))
        except Exception:
            pass

    async def send(self, event: dict) -> None:
        await self.connection.send(json.dumps(event))

    async def expect(self, match: Callable[[dict], bool], timeout: float = EVENT_TIMEOUT) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError("expected event never arrived")
            event = await asyncio.wait_for(self.events.get(), remaining)
            if match(event):
                return event

    async def close(self) -> None:
        await self.connection.close()
        self.reader.cancel()


class Smoke:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        self.api = f"{self.base}/api/v1"
        self.ws_url = self.api.replace("http", "ws", 1) + "/ws"
        self.http = httpx.AsyncClient(base_url=self.api, timeout=15)
        self.failures: list[str] = []

    async def step(self, name: str, check: Callable[[], Awaitable[None]]) -> None:
        try:
            await check()
        except Exception as error:
            self.failures.append(name)
            print(f"FAIL  {name}: {type(error).__name__}: {error}")
        else:
            print(f"PASS  {name}")

    async def call(self, method: str, path: str, user: Account | None = None, expect: int | None = None, **kwargs):
        response = await self.http.request(method, path, headers=user.headers if user else None, **kwargs)
        if expect is not None and response.status_code != expect:
            raise AssertionError(f"{method} {path} -> {response.status_code}, wanted {expect}: {response.text[:300]}")
        return response

    async def socket(self, user: Account) -> Socket:
        sock = Socket(await connect(self.ws_url))
        await sock.send({"type": "auth", "token": user.token})
        await sock.expect(lambda e: e.get("type") == "ready")
        return sock


def jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), color="teal").save(buffer, format="JPEG")
    return buffer.getvalue()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def run(base_url: str) -> int:
    s = Smoke(base_url)
    tag = uuid.uuid4().hex[:8]
    users: dict[str, Account] = {}
    state: dict = {}

    async def signup_and_login() -> None:
        for name in ("ava", "ben", "cy"):
            username = f"smoke_{name}_{tag}"
            email = f"{username}@example.com"
            body = {"email": email, "username": username, "password": PASSWORD}
            created = (await s.call("POST", "/auth/signup", json=body, expect=201)).json()
            login = {"email": email, "password": PASSWORD, "client": "native"}
            tokens = (await s.call("POST", "/auth/login", json=login, expect=200)).json()
            check(bool(tokens.get("refresh_token")), "native login must return refresh_token in the body")
            users[name] = Account(created["id"], username, tokens["access_token"])

    await s.step("sign up and log in (native)", signup_and_login)
    if len(users) != 3:
        print("Cannot continue without users.")
        return 1
    ava, ben, cy = users["ava"], users["ben"], users["cy"]

    async def follow_each_other() -> None:
        await s.call("PUT", f"/users/{ben.username}/follow", ava, expect=204)
        await s.call("PUT", f"/users/{ava.username}/follow", ben, expect=204)
        await s.call("PUT", f"/users/{cy.username}/follow", ava, expect=204)
        await s.call("PUT", f"/users/{ava.username}/follow", cy, expect=204)
        await s.call("PUT", f"/users/{cy.username}/follow", ben, expect=204)

    await s.step("follow each other", follow_each_other)

    async def circle_list() -> None:
        people = (await s.call("GET", "/conversations/circle", ava, expect=200)).json()
        names = {p["user"]["username"] for p in people}
        check({ben.username, cy.username} <= names, f"circle missing people: {names}")
        check(all("online" in p and "has_live_fit_check" in p for p in people), "circle fields missing")

    await s.step("circle list", circle_list)

    async def create_direct() -> None:
        body = {"type": "direct", "member_ids": [ben.id]}
        response = await s.call("POST", "/conversations", ava, expect=201, json=body)
        state["direct"] = response.json()["id"]

    await s.step("create direct conversation", create_direct)

    async def reuse_direct() -> None:
        again = await s.call("POST", "/conversations", ava, expect=200, json={"type": "direct", "member_ids": [ben.id]})
        from_ben = await s.call("POST", "/conversations", ben, expect=200, json={"type": "direct", "member_ids": [ava.id]})
        check(again.json()["id"] == state["direct"] == from_ben.json()["id"], "direct chat was not reused")

    await s.step("reuse existing direct conversation", reuse_direct)

    async def create_circle() -> None:
        body = {"type": "circle", "member_ids": [ben.id, cy.id], "title": "Smoke circle"}
        created = (await s.call("POST", "/conversations", ava, expect=201, json=body)).json()
        check(len(created["members"]) == 3 and created["title"] == "Smoke circle", "circle not created right")
        state["circle"] = created["id"]

    await s.step("create circle conversation", create_circle)
    direct = state.get("direct")
    circle = state.get("circle")
    if not direct or not circle:
        print("Cannot continue without conversations.")
        return 1

    sock_ava = await s.socket(ava)
    sock_ben = await s.socket(ben)

    def messages_url(conversation_id: str) -> str:
        return f"/conversations/{conversation_id}/messages"

    async def send(user: Account, conversation_id: str, expect: int | None = 201, **body):
        body.setdefault("kind", "text")
        return await s.call("POST", messages_url(conversation_id), user, expect=expect, json=body)

    def new_message(message_id: str) -> Callable[[dict], bool]:
        return lambda e: e.get("type") == "message:new" and e["message"]["id"] == message_id

    async def send_text() -> None:
        sent = (await send(ava, direct, body="hello from smoke")).json()
        event = await sock_ben.expect(new_message(sent["id"]))
        check(event["message"]["body"] == "hello from smoke", "text body mismatch over socket")
        state["text_id"] = sent["id"]

    await s.step("send text (reaches other user's socket)", send_text)

    async def send_image() -> None:
        files = {"file": ("smoke.jpg", jpeg(), "image/jpeg")}
        image = (await s.call("POST", "/images", ava, expect=201, files=files)).json()
        state["image_id"] = image["id"]
        sent = (await send(ava, direct, kind="image", image_id=image["id"])).json()
        check(sent["payload"]["image"]["id"] == image["id"] and sent["payload"]["image"]["url"], "image payload missing")
        await sock_ben.expect(new_message(sent["id"]))

    await s.step("send image", send_image)

    async def send_fit_check() -> None:
        body = {"kind": "fit_check", "image_id": state["image_id"], "question": "Wear it tonight?", "context": "Dinner"}
        sent = (await send(ava, direct, **body)).json()
        check(sent["votes"] == {"wear": 0, "rethink": 0, "total": 0, "wear_pct": 0, "rethink_pct": 0, "my_vote": None}, f"bad tally {sent['votes']}")
        check(sent["payload"]["question"] == "Wear it tonight?", "fit_check question missing")
        await sock_ben.expect(new_message(sent["id"]))
        state["fit_check_id"] = sent["id"]

    await s.step("send fit_check", send_fit_check)

    async def send_product() -> None:
        product = {"name": "Linen shirt", "price": "$48", "url": "https://example.com/shirt"}
        sent = (await send(ava, direct, kind="product", product=product)).json()
        check(sent["payload"]["product"]["name"] == "Linen shirt", "product payload missing")
        await sock_ben.expect(new_message(sent["id"]))

    await s.step("send product", send_product)

    async def client_id_dedupe() -> None:
        client_id = f"smoke-{tag}"
        first = (await send(ava, direct, body="once", client_id=client_id)).json()
        second = await send(ava, direct, expect=None, body="once", client_id=client_id)
        check(second.status_code in (200, 201), f"retry returned {second.status_code}")
        check(second.json()["id"] == first["id"], "client_id retry created a second message")
        page = (await s.call("GET", messages_url(direct), ava, expect=200, params={"limit": 50})).json()
        check(sum(1 for m in page["items"] if m["client_id"] == client_id) == 1, "duplicate stored")

    await s.step("client_id duplicate protection", client_id_dedupe)

    async def pagination() -> None:
        for i in range(4):
            await send(ben, direct, body=f"page {i}")
        first = (await s.call("GET", messages_url(direct), ava, expect=200, params={"limit": 3})).json()
        check(len(first["items"]) == 3 and first["next_cursor"], "first page wrong")
        params = {"limit": 3, "before": first["next_cursor"]}
        second = (await s.call("GET", messages_url(direct), ava, expect=200, params=params)).json()
        ids_first = [m["id"] for m in first["items"]]
        ids_second = [m["id"] for m in second["items"]]
        check(not set(ids_first) & set(ids_second), "pages overlap")
        stamps = [m["created_at"] for m in first["items"] + second["items"]]
        check(stamps == sorted(stamps, reverse=True), "not newest first")
        bad = await s.call("GET", messages_url(direct), ava, params={"before": "garbage"})
        check(bad.status_code == 400, f"invalid cursor gave {bad.status_code}")

    await s.step("pagination with before= cursor", pagination)

    async def unread_counts() -> None:
        inbox = (await s.call("GET", "/conversations", ava, expect=200)).json()
        mine = next(c for c in inbox if c["id"] == direct)
        check(mine["unread_count"] == 4, f"ava unread {mine['unread_count']}, wanted 4")
        check(next(c for c in inbox if c["id"] == circle)["unread_count"] == 0, "circle should have 0 unread")

    await s.step("unread counts", unread_counts)

    async def receipts() -> None:
        delivered = (await s.call("POST", f"/conversations/{direct}/delivered", ava, expect=200)).json()
        check(delivered["last_delivered_at"] is not None, "delivered not set")
        event = await sock_ben.expect(lambda e: e.get("type") == "receipt:update" and e["user_id"] == ava.id)
        check(event["last_delivered_at"] is not None, "delivered event missing time")
        read = (await s.call("POST", f"/conversations/{direct}/read", ava, expect=200)).json()
        check(read["last_read_at"] is not None, "read not set")
        event = await sock_ben.expect(lambda e: e.get("type") == "receipt:update" and e["user_id"] == ava.id)
        check(event["last_read_at"] is not None, "read event missing time")
        inbox = (await s.call("GET", "/conversations", ava, expect=200)).json()
        check(next(c for c in inbox if c["id"] == direct)["unread_count"] == 0, "unread not cleared by read")
        members = {m["user"]["id"]: m for m in next(c for c in inbox if c["id"] == direct)["members"]}
        check(members[ava.id]["last_read_at"] is not None, "member last_read_at missing")

    await s.step("delivered and read receipts", receipts)

    async def typing() -> None:
        await sock_ava.send({"type": "typing:start", "conversation_id": direct})
        event = await sock_ben.expect(lambda e: e.get("type") == "typing:start")
        check(event == {"type": "typing:start", "conversation_id": direct, "user_id": ava.id}, f"bad typing {event}")
        await sock_ava.send({"type": "typing:stop", "conversation_id": direct})
        await sock_ben.expect(lambda e: e.get("type") == "typing:stop" and e["user_id"] == ava.id)

    await s.step("typing start/stop", typing)

    async def ping() -> None:
        await sock_ava.send({"type": "ping"})
        await sock_ava.expect(lambda e: e.get("type") == "pong")

    await s.step("socket ping/pong", ping)

    async def presence() -> None:
        nonlocal sock_ben
        await sock_ben.close()
        offline = await sock_ava.expect(lambda e: e.get("type") == "presence:update" and e["user_id"] == ben.id)
        check(offline["online"] is False and offline["last_seen_at"], f"bad offline event {offline}")
        conversation = (await s.call("GET", f"/conversations/{direct}", ava, expect=200)).json()
        ben_member = next(m for m in conversation["members"] if m["user"]["id"] == ben.id)
        check(ben_member["online"] is False and ben_member["last_seen_at"], "ben should be offline with last_seen_at")
        sock_ben = await s.socket(ben)
        online = await sock_ava.expect(lambda e: e.get("type") == "presence:update" and e["user_id"] == ben.id)
        check(online["online"] is True, "online event missing")
        conversation = (await s.call("GET", f"/conversations/{direct}", ava, expect=200)).json()
        check(next(m for m in conversation["members"] if m["user"]["id"] == ben.id)["online"] is True, "ben not online")

    await s.step("presence online/offline and last_seen_at", presence)

    async def vote() -> None:
        url = f"/messages/{state['fit_check_id']}/vote"
        result = (await s.call("POST", url, ben, expect=200, json={"vote": "wear"})).json()
        check(result["wear"] == 1 and result["wear_pct"] == 100 and result["my_vote"] == "wear", f"bad vote {result}")
        event = await sock_ava.expect(lambda e: e.get("type") == "vote:update")
        check(event["message_id"] == state["fit_check_id"] and "my_vote" not in event, f"bad vote event {event}")
        changed = (await s.call("POST", url, ben, expect=200, json={"vote": "rethink"})).json()
        check(changed["total"] == 1 and changed["rethink"] == 1, "revote should replace")
        await sock_ava.expect(lambda e: e.get("type") == "vote:update" and e["rethink"] == 1)
        bad = await s.call("POST", f"/messages/{state['text_id']}/vote", ben, json={"vote": "wear"})
        check(bad.status_code == 400, f"voting on text gave {bad.status_code}")

    await s.step("fit_check vote and live vote:update", vote)

    async def delete_message() -> None:
        target = (await send(ava, direct, body="delete me")).json()
        await sock_ben.expect(new_message(target["id"]))
        forbidden = await s.call("DELETE", f"/messages/{target['id']}", ben)
        check(forbidden.status_code == 403, f"other user delete gave {forbidden.status_code}")
        await s.call("DELETE", f"/messages/{target['id']}", ava, expect=204)
        event = await sock_ben.expect(lambda e: e.get("type") == "message:deleted")
        check(event["message_id"] == target["id"], "deleted event for wrong message")
        page = (await s.call("GET", messages_url(direct), ben, expect=200, params={"limit": 5})).json()
        stored = next(m for m in page["items"] if m["id"] == target["id"])
        check(stored["deleted_at"] and stored["body"] is None and stored["payload"] is None, "content not cleared")

    await s.step("message delete (content cleared)", delete_message)

    async def mute() -> None:
        updated = (await s.call("PATCH", f"/conversations/{circle}", ben, expect=200, json={"muted": True})).json()
        check(updated["muted"] is True, "mute not applied")
        others = (await s.call("GET", f"/conversations/{circle}", ava, expect=200)).json()
        check(others["muted"] is False, "mute leaked to other member")

    await s.step("mute", mute)

    async def rename() -> None:
        updated = (await s.call("PATCH", f"/conversations/{circle}", ben, expect=200, json={"title": "Renamed"})).json()
        check(updated["title"] == "Renamed", "rename not applied")
        await sock_ava.expect(lambda e: e.get("type") == "conversation:update" and e["conversation_id"] == circle)
        bad = await s.call("PATCH", f"/conversations/{direct}", ava, json={"title": "nope"})
        check(bad.status_code == 400, f"renaming direct gave {bad.status_code}")

    await s.step("rename", rename)

    async def non_member_blocked() -> None:
        read = await s.call("GET", messages_url(direct), cy)
        write = await s.call("POST", messages_url(direct), cy, json={"kind": "text", "body": "let me in"})
        get = await s.call("GET", f"/conversations/{direct}", cy)
        check((read.status_code, write.status_code, get.status_code) == (404, 404, 404), f"non-member got {read.status_code}/{write.status_code}/{get.status_code}")

    await s.step("non-member blocked from reading and sending", non_member_blocked)

    async def length_cap() -> None:
        response = await send(ava, direct, expect=None, body="x" * 2001)
        check(response.status_code == 422, f"2001 chars gave {response.status_code}")
        ok = await send(ava, direct, expect=None, body="x" * 2000)
        check(ok.status_code == 201, f"2000 chars gave {ok.status_code}")

    await s.step("message length cap", length_cap)

    async def rate_limit() -> None:
        codes = [(await send(cy, circle, expect=None, body=f"burst {i}")).status_code for i in range(21)]
        check(codes[:20] == [201] * 20, f"first 20 not all accepted: {codes[:20]}")
        check(codes[20] == 429, f"21st gave {codes[20]}")

    await s.step("rate limit (21st message in 10s rejected)", rate_limit)

    async def leave() -> None:
        await s.call("DELETE", f"/conversations/{circle}", cy, expect=204)
        inbox = (await s.call("GET", "/conversations", cy, expect=200)).json()
        check(all(c["id"] != circle for c in inbox), "circle still in leaver's inbox")
        remaining = (await s.call("GET", f"/conversations/{circle}", ava, expect=200)).json()
        check(len(remaining["members"]) == 2, "member count after leave")
        gone = await s.call("GET", messages_url(circle), cy)
        check(gone.status_code == 404, "left member can still read")

    await s.step("leave circle", leave)

    async def hide() -> None:
        await s.call("DELETE", f"/conversations/{direct}", ben, expect=204)
        inbox = (await s.call("GET", "/conversations", ben, expect=200)).json()
        check(all(c["id"] != direct for c in inbox), "hidden chat still listed")
        await send(ava, direct, body="come back")
        inbox = (await s.call("GET", "/conversations", ben, expect=200)).json()
        check(any(c["id"] == direct for c in inbox), "new message did not unhide")

    await s.step("hide direct chat (returns on new message)", hide)

    async def reconnect_catch_up() -> None:
        nonlocal sock_ben
        await sock_ben.close()
        newest = (await s.call("GET", messages_url(direct), ben, expect=200, params={"limit": 1})).json()["items"][0]
        missed = [(await send(ava, direct, body=f"while away {i}")).json()["id"] for i in range(3)]
        sock_ben = await s.socket(ben)
        live = (await send(ava, direct, body="after reconnect")).json()
        await sock_ben.expect(new_message(live["id"]))
        page = (await s.call("GET", messages_url(direct), ben, expect=200, params={"limit": 30})).json()
        ids = [m["id"] for m in page["items"]]
        caught_up = ids[: ids.index(newest["id"])]
        check(set(missed) <= set(caught_up), "missed messages not returned after reconnect")
        inbox = (await s.call("GET", "/conversations", ben, expect=200)).json()
        check(next(c for c in inbox if c["id"] == direct)["unread_count"] >= 4, "unread count missing missed messages")

    await s.step("WebSocket reconnect then catch up on missed messages", reconnect_catch_up)

    async def bad_socket_token() -> None:
        async with connect(s.ws_url) as raw:
            await raw.send(json.dumps({"type": "auth", "token": "nope"}))
            try:
                await asyncio.wait_for(raw.recv(), EVENT_TIMEOUT)
            except Exception:
                pass
            check(raw.close_code == 4401, f"close code {raw.close_code}")

    await s.step("socket rejects a bad token (4401)", bad_socket_token)

    async def device_register() -> None:
        body = {"platform": "ios", "token": f"smoke-{tag}", "app_version": "smoke"}
        device = (await s.call("POST", "/devices", ava, expect=200, json=body)).json()
        check(device["token"] == body["token"], "device not registered")

    await s.step("register a push device", device_register)

    async def story_post_and_view() -> None:
        files = {"file": ("story.jpg", jpeg(), "image/jpeg")}
        image = (await s.call("POST", "/images", ava, expect=201, files=files)).json()
        body = {"image_id": image["id"], "caption": "Smoke fit", "visibility": "close_friends"}
        story = (await s.call("POST", "/stories", ava, expect=201, json=body)).json()
        state["story"] = story
        event = await sock_ben.expect(lambda e: e.get("type") == "story:new")
        check(event["story_id"] == story["id"], "story:new for wrong story")
        feed = (await s.call("GET", "/stories/feed", ben, expect=200)).json()
        group = next(g for g in feed if g["user"]["id"] == ava.id)
        check(group["has_unseen"] and group["stories"][0]["id"] == story["id"], "story missing from feed")
        await s.call("POST", f"/stories/{story['id']}/view", ben, expect=204)
        await s.call("POST", f"/stories/{story['id']}/view", ben, expect=204)
        viewed = await sock_ava.expect(lambda e: e.get("type") == "story:viewed")
        check(viewed["view_count"] == 1, f"view_count {viewed['view_count']}")
        viewers = (await s.call("GET", f"/stories/{story['id']}/viewers", ava, expect=200)).json()
        check([v["user"]["id"] for v in viewers["items"]] == [ben.id], "viewers list wrong")
        forbidden = await s.call("GET", f"/stories/{story['id']}/viewers", ben)
        check(forbidden.status_code == 403, f"non-owner viewers gave {forbidden.status_code}")

    await s.step("story post, story:new, idempotent view, story:viewed", story_post_and_view)

    async def story_reply() -> None:
        story = state["story"]
        reply = (await s.call("POST", f"/stories/{story['id']}/reply", ben, expect=201, json={"body": "fire"})).json()
        check(reply["kind"] == "story_reply" and reply["conversation_id"] == direct, "reply not in the direct chat")
        check(reply["payload"]["story_id"] == story["id"] and reply["payload"]["image"], "reply payload missing")
        await sock_ava.expect(new_message(reply["id"]))
        event = await sock_ava.expect(lambda e: e.get("type") == "notification:new")
        check(event["notification"]["type"] == "story_reply", f"got {event['notification']['type']}")

    await s.step("story reply (story_reply message and notification)", story_reply)

    async def notifications() -> None:
        page = (await s.call("GET", "/notifications", ava, expect=200)).json()
        types = {n["type"] for n in page["items"]}
        check({"follow", "story_reply", "fit_check_vote"} <= types, f"missing notification types: {types}")
        check(all(n["title"] and n["body"] and n["link"] for n in page["items"]), "notification text missing")
        count = (await s.call("GET", "/notifications/unread-count", ava, expect=200)).json()["unread"]
        check(count >= 3, f"unread {count}")
        cleared = (await s.call("POST", "/notifications/read", ava, expect=200, json={"all": True})).json()
        check(cleared == {"unread": 0}, f"mark read gave {cleared}")
        await sock_ava.expect(lambda e: e.get("type") == "notification:count" and e["unread"] == 0)

    await s.step("notifications list, unread count, mark read", notifications)

    async def streak() -> None:
        mine = (await s.call("GET", "/users/me/streak", ava, expect=200)).json()
        check(mine["current"] == 1 and mine["active_today"] is True, f"streak {mine}")
        me = (await s.call("GET", "/users/me", ava, expect=200)).json()
        profile = (await s.call("GET", f"/users/{ava.username}", ben, expect=200)).json()
        check(me["current_streak"] == 1 == profile["current_streak"], "streak missing on profile")

    await s.step("streak counts fit checks and stories", streak)

    async def device_remove() -> None:
        await s.call("DELETE", f"/devices/smoke-{tag}", ava, expect=204)

    await s.step("remove a push device", device_remove)

    await sock_ava.close()
    await sock_ben.close()
    await s.http.aclose()

    print()
    if s.failures:
        print(f"{len(s.failures)} step(s) failed: {', '.join(s.failures)}")
        return 1
    print("All steps passed.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base_url", help="Server root, e.g. http://localhost:8000")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.base_url)))


if __name__ == "__main__":
    main()
