"""Style a Friend: a "style me" request in chat, a look sent back, and saving its pieces."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.conversation import send_limiter
from app.tryon import get_tryon_generator
from tests.conftest import AuthedUser, make_image_bytes
from tests.test_tryons import FakeGenerator

CONVERSATIONS_URL = "/api/v1/conversations"
MESSAGES_URL = "/api/v1/messages"
FITS_URL = "/api/v1/fits"
TRYONS_URL = "/api/v1/tryons"
PIECES_URL = "/api/v1/users/me/saved-pieces"
LOOKS_URL = "/api/v1/users/me/saved-looks"


@pytest.fixture(autouse=True)
def reset_rate_limit():
    send_limiter.reset()
    yield
    send_limiter.reset()


@pytest.fixture
def people(create_user: Callable[..., AuthedUser], client: TestClient):
    jane, bob, carol = create_user("jane"), create_user("bob"), create_user("carol")
    client.put("/api/v1/users/bob/follow", headers=jane.headers)
    return jane, bob, carol


@pytest.fixture
def chat(client: TestClient, people) -> str:
    jane, bob, _ = people
    response = client.post(
        CONVERSATIONS_URL, headers=jane.headers, json={"type": "direct", "member_ids": [str(bob.id)]}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def generator(client: TestClient) -> FakeGenerator:
    fake = FakeGenerator()
    app.dependency_overrides[get_tryon_generator] = lambda: fake
    return fake


def send(client: TestClient, user: AuthedUser, conversation_id: str, **body):
    return client.post(f"{CONVERSATIONS_URL}/{conversation_id}/messages", headers=user.headers, json=body)


def ask(client: TestClient, user: AuthedUser, conversation_id: str, **body) -> dict:
    response = send(client, user, conversation_id, kind="style_request", **body)
    assert response.status_code == 201, response.text
    return response.json()


def thread(client: TestClient, user: AuthedUser, conversation_id: str) -> list[dict]:
    response = client.get(f"{CONVERSATIONS_URL}/{conversation_id}/messages", headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def post_fit(client: TestClient, user: AuthedUser, upload_image, **extra) -> dict:
    photo = upload_image(user)
    body = {
        "image_ids": [photo],
        "items": [
            {"category": "top", "name": "Relaxed tee", "brand": "Uniqlo", "url": "https://example.com/tee"},
            {"category": "shoes", "name": "Sambas", "color": "white"},
        ],
        **extra,
    }
    response = client.post(FITS_URL, headers=user.headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def save_piece(client: TestClient, user: AuthedUser, fit: dict, index: int) -> dict:
    response = client.post(f"{FITS_URL}/{fit['id']}/items/{fit['items'][index]['id']}/save", headers=user.headers)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def look_parts(client: TestClient, people, upload_image):
    """Bob's options: a piece he saved from Carol's fit, Carol's fit itself, and his own upload."""
    _, bob, carol = people
    fit = post_fit(client, carol, upload_image)
    saved = save_piece(client, bob, fit, 0)
    upload = upload_image(bob)
    return fit, saved, upload


def look_body(request_id: str, fit: dict, saved: dict, upload: str, **look) -> dict:
    return {
        "kind": "styled_look",
        "body": "Wear the tee untucked",
        "request_id": request_id,
        "look": {
            "pieces": [
                {"saved_piece_id": saved["id"]},
                {"fit_id": fit["id"], "item_id": fit["items"][1]["id"], "url": "https://example.com/sambas"},
                {"image_id": upload, "category": "bottom", "name": "Wide-leg jeans", "url": "https://shop.example/jeans"},
            ],
            **look,
        },
    }


def test_ask_to_be_styled_with_a_note_and_photo(client: TestClient, people, chat, upload_image) -> None:
    jane, bob, _ = people
    photo = upload_image(jane)

    request = ask(client, jane, chat, body="Date night, under $100", image_id=photo)

    assert request["kind"] == "style_request"
    assert request["body"] == "Date night, under $100"
    assert request["payload"]["image"]["id"] == photo
    seen = thread(client, bob, chat)[0]
    assert seen["id"] == request["id"] and seen["payload"]["image"]["id"] == photo


def test_ask_without_a_photo(client: TestClient, people, chat) -> None:
    jane, _, _ = people
    request = ask(client, jane, chat)
    assert request["body"] is None
    assert request["payload"].get("image") is None


def test_the_request_photo_must_be_yours(client: TestClient, people, chat, upload_image) -> None:
    jane, bob, _ = people
    response = send(client, jane, chat, kind="style_request", image_id=upload_image(bob))
    assert response.status_code == 400


def test_send_a_look_back(client: TestClient, people, chat, look_parts) -> None:
    jane, bob, _ = people
    fit, saved, upload = look_parts
    request = ask(client, jane, chat, body="Something casual")

    response = send(client, bob, chat, **look_body(request["id"], fit, saved, upload))

    assert response.status_code == 201, response.text
    look = response.json()
    assert look["kind"] == "styled_look"
    assert look["body"] == "Wear the tee untucked"
    payload = look["payload"]
    assert payload["request_id"] == request["id"]
    assert payload["tryon_image"] is None
    tee, shoes, jeans = payload["pieces"]
    assert (tee["name"], tee["brand"], tee["url"]) == ("Relaxed tee", "Uniqlo", "https://example.com/tee")
    assert tee["source_username"] == "carol" and tee["fit_id"] == fit["id"]
    assert tee["photo"]["id"] == fit["images"][0]["id"]
    # The stylist's link replaces the fit's (it had none).
    assert (shoes["name"], shoes["color"], shoes["url"]) == ("Sambas", "white", "https://example.com/sambas")
    assert (jeans["category"], jeans["name"], jeans["url"]) == ("bottom", "Wide-leg jeans", "https://shop.example/jeans")
    assert jeans["photo"]["id"] == upload and jeans["source_username"] is None
    assert all(piece["saved_piece_id"] is None for piece in payload["pieces"])

    # Jane sees the same look in her chat.
    assert thread(client, jane, chat)[0]["payload"]["pieces"][2]["name"] == "Wide-leg jeans"


def test_look_rules(client: TestClient, people, chat, look_parts, upload_image) -> None:
    jane, bob, _ = people
    fit, saved, upload = look_parts
    request = ask(client, jane, chat)
    text = send(client, jane, chat, kind="text", body="hi").json()

    # Not your own request, not a text message, not a made-up id.
    assert send(client, jane, chat, **look_body(request["id"], fit, saved, upload)).status_code == 400
    assert send(client, bob, chat, **look_body(text["id"], fit, saved, upload)).status_code == 400
    # A piece must have exactly one source, and an upload needs a name and category.
    bad = {"kind": "styled_look", "request_id": request["id"], "look": {"pieces": [{}]}}
    assert send(client, bob, chat, **bad).status_code == 422
    bad["look"]["pieces"] = [{"image_id": upload}]
    assert send(client, bob, chat, **bad).status_code == 422
    # Someone else's saved piece or upload isn't Bob's to send.
    bad["look"]["pieces"] = [{"image_id": upload_image(jane), "category": "top", "name": "Tee"}]
    assert send(client, bob, chat, **bad).status_code == 400
    jane_saved = save_piece(client, jane, fit, 1)
    bad["look"]["pieces"] = [{"saved_piece_id": jane_saved["id"]}]
    assert send(client, bob, chat, **bad).status_code == 400
    # A look needs pieces.
    bad["look"]["pieces"] = []
    assert send(client, bob, chat, **bad).status_code == 422


def test_a_deleted_request_cant_be_answered(client: TestClient, people, chat, look_parts) -> None:
    jane, bob, _ = people
    fit, saved, upload = look_parts
    request = ask(client, jane, chat)
    assert client.delete(f"{MESSAGES_URL}/{request['id']}", headers=jane.headers).status_code == 204
    assert send(client, bob, chat, **look_body(request["id"], fit, saved, upload)).status_code == 400


def test_try_the_look_on_the_friend(
    client: TestClient, people, chat, look_parts, upload_image, generator: FakeGenerator
) -> None:
    jane, bob, _ = people
    fit, saved, upload = look_parts
    photo = upload_image(jane)
    request = ask(client, jane, chat, image_id=photo)
    pieces = [
        {"slot": "top", "image_id": saved["photo"]["id"], "note": "relaxed tee"},
        {"slot": "bottom", "image_id": upload},
    ]

    response = client.post(
        TRYONS_URL,
        headers=bob.headers,
        json={"person_image_id": photo, "pieces": pieces, "style_request_id": request["id"]},
    )

    assert response.status_code == 201, response.text
    tryon = response.json()
    assert tryon["person_image"]["id"] == photo
    assert len(generator.calls) == 1
    assert [g.slot for g in generator.calls[0][1]] == ["top", "bottom"]

    look = send(client, bob, chat, **look_body(request["id"], fit, saved, upload, tryon_id=tryon["id"]))
    assert look.status_code == 201, look.text
    assert look.json()["payload"]["tryon_image"]["id"] == tryon["result_image"]["id"]


def test_try_on_for_a_friend_rules(
    client: TestClient, people, chat, look_parts, upload_image, generator: FakeGenerator
) -> None:
    jane, bob, carol = people
    _, saved, upload = look_parts
    photo = upload_image(jane)
    request = ask(client, jane, chat, image_id=photo)

    def tryon(user, person, request_id=request["id"], outfit=upload):
        body = {"person_image_id": person, "outfit_image_id": outfit}
        if request_id:
            body["style_request_id"] = request_id
        return client.post(TRYONS_URL, headers=user.headers, json=body)

    # Without the request, Jane's photo isn't Bob's to use.
    assert tryon(bob, photo, request_id=None).status_code == 400
    # Only the request's own photo.
    assert tryon(bob, upload_image(jane)).status_code == 400
    # Not Jane on her own request, and not Carol, who isn't in the chat.
    assert tryon(jane, photo, outfit=upload_image(jane)).status_code == 400
    assert tryon(carol, photo, outfit=upload_image(carol)).status_code == 400
    # A saved piece's photo works for Bob; someone else's upload doesn't.
    assert tryon(bob, photo, outfit=saved["photo"]["id"]).status_code == 201
    assert tryon(bob, photo, outfit=upload_image(carol)).status_code == 400
    # A look can only show the stylist's own try-on.
    jane_tryon = client.post(
        TRYONS_URL, headers=jane.headers, json={"person_image_id": photo, "outfit_image_id": upload_image(jane)}
    ).json()
    bad = {
        "kind": "styled_look",
        "request_id": request["id"],
        "look": {"pieces": [{"saved_piece_id": saved["id"]}], "tryon_id": jane_tryon["id"]},
    }
    assert send(client, bob, chat, **bad).status_code == 400


def test_try_on_respects_fits_with_try_ons_off(
    client: TestClient, people, chat, upload_image, generator: FakeGenerator
) -> None:
    jane, bob, carol = people
    fit = post_fit(client, carol, upload_image, allow_friend_try_on=False)
    saved = save_piece(client, bob, fit, 0)
    photo = upload_image(jane)
    request = ask(client, jane, chat, image_id=photo)

    response = client.post(
        TRYONS_URL,
        headers=bob.headers,
        json={"person_image_id": photo, "outfit_image_id": saved["photo"]["id"], "style_request_id": request["id"]},
    )

    assert response.status_code == 400


def test_save_pieces_of_a_look(client: TestClient, people, chat, look_parts) -> None:
    jane, bob, carol = people
    fit, saved, upload = look_parts
    request = ask(client, jane, chat)
    look = send(client, bob, chat, **look_body(request["id"], fit, saved, upload)).json()
    url = f"{MESSAGES_URL}/{look['id']}/look"

    one = client.post(f"{url}/pieces/2/save", headers=jane.headers)
    assert one.status_code == 201, one.text
    jeans = one.json()
    assert (jeans["name"], jeans["category"], jeans["url"]) == ("Wide-leg jeans", "bottom", "https://shop.example/jeans")
    assert jeans["photo"]["id"] == upload
    # Bob styled it, so the piece he uploaded is credited to him.
    assert jeans["source_username"] == "bob"
    # Saving again returns the same save.
    assert client.post(f"{url}/pieces/2/save", headers=jane.headers).json()["id"] == jeans["id"]

    listed = client.get(PIECES_URL, headers=jane.headers).json()["items"]
    assert [p["id"] for p in listed] == [jeans["id"]]
    # The chat shows Jane which pieces she saved, and nobody else.
    assert [p["saved_piece_id"] for p in thread(client, jane, chat)[0]["payload"]["pieces"]] == [None, None, jeans["id"]]
    assert [p["saved_piece_id"] for p in thread(client, bob, chat)[0]["payload"]["pieces"]] == [None, None, None]


def test_save_the_whole_look(client: TestClient, people, chat, look_parts, upload_image, generator: FakeGenerator) -> None:
    jane, bob, _ = people
    fit, saved, upload = look_parts
    photo = upload_image(jane)
    request = ask(client, jane, chat, image_id=photo)
    tryon = client.post(
        TRYONS_URL,
        headers=bob.headers,
        json={"person_image_id": photo, "outfit_image_id": upload, "style_request_id": request["id"]},
    ).json()
    look = send(client, bob, chat, **look_body(request["id"], fit, saved, upload, tryon_id=tryon["id"])).json()

    response = client.post(f"{MESSAGES_URL}/{look['id']}/look/save", headers=jane.headers)

    assert response.status_code == 201, response.text
    saved_look = response.json()
    assert saved_look["message_id"] == look["id"] and saved_look["conversation_id"] == chat
    assert saved_look["stylist"]["username"] == "bob"
    assert saved_look["note"] == "Wear the tee untucked"
    assert saved_look["tryon_image"]["id"] == tryon["result_image"]["id"]
    assert [p["name"] for p in saved_look["pieces"]] == ["Relaxed tee", "Sambas", "Wide-leg jeans"]
    assert saved_look["pieces"][2]["photo"]["id"] == upload
    assert saved_look["pieces"][2]["url"] == "https://shop.example/jeans"
    assert saved_look["pieces"][0]["source_username"] == "carol"
    # Saving again returns the same save.
    assert client.post(f"{MESSAGES_URL}/{look['id']}/look/save", headers=jane.headers).json()["id"] == saved_look["id"]
    # A whole look goes to saved looks, not saved pieces.
    assert client.get(PIECES_URL, headers=jane.headers).json()["items"] == []
    listed = client.get(LOOKS_URL, headers=jane.headers).json()["items"]
    assert [item["id"] for item in listed] == [saved_look["id"]]
    assert client.get(LOOKS_URL, headers=bob.headers).json()["items"] == []
    assert thread(client, jane, chat)[0]["payload"]["saved_look_id"] == saved_look["id"]
    assert thread(client, bob, chat)[0]["payload"]["saved_look_id"] is None

    # It stays when Bob deletes the message.
    assert client.delete(f"{MESSAGES_URL}/{look['id']}", headers=bob.headers).status_code == 204
    kept = client.get(LOOKS_URL, headers=jane.headers).json()["items"][0]
    assert kept["message_id"] == look["id"] and kept["pieces"][2]["photo"]["id"] == upload

    # Only Jane can unsave it.
    assert client.delete(f"{LOOKS_URL}/{saved_look['id']}", headers=bob.headers).status_code == 404
    assert client.delete(f"{LOOKS_URL}/{saved_look['id']}", headers=jane.headers).status_code == 204
    assert client.get(LOOKS_URL, headers=jane.headers).json()["items"] == []


def test_saving_a_look_rules(client: TestClient, people, chat, look_parts) -> None:
    jane, bob, carol = people
    fit, saved, upload = look_parts
    request = ask(client, jane, chat)
    look = send(client, bob, chat, **look_body(request["id"], fit, saved, upload)).json()

    # Not in the chat, a piece that doesn't exist, and a message that isn't a look.
    assert client.post(f"{MESSAGES_URL}/{look['id']}/look/save", headers=carol.headers).status_code == 404
    assert client.post(f"{MESSAGES_URL}/{look['id']}/look/pieces/3/save", headers=jane.headers).status_code == 404
    assert client.post(f"{MESSAGES_URL}/{request['id']}/look/save", headers=jane.headers).status_code == 404


def test_a_saved_look_piece_outlives_its_fit(client: TestClient, people, chat, look_parts) -> None:
    jane, bob, carol = people
    fit, saved, upload = look_parts
    request = ask(client, jane, chat)
    look = send(client, bob, chat, **look_body(request["id"], fit, saved, upload)).json()
    assert client.delete(f"{FITS_URL}/{fit['id']}", headers=carol.headers).status_code == 204

    response = client.post(f"{MESSAGES_URL}/{look['id']}/look/pieces/1/save", headers=jane.headers)

    assert response.status_code == 201, response.text
    assert response.json()["fit_id"] is None
    assert response.json()["name"] == "Sambas"


def test_inbox_previews(client: TestClient, people, chat, look_parts) -> None:
    jane, bob, _ = people
    fit, saved, upload = look_parts
    request = ask(client, jane, chat, body="Interview outfit")
    send(client, bob, chat, **look_body(request["id"], fit, saved, upload))

    inbox = client.get(CONVERSATIONS_URL, headers=jane.headers).json()
    assert inbox[0]["last_message"]["kind"] == "styled_look"
