from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import PASSWORD, AuthedUser

SIGNUP_URL = "/api/v1/auth/signup"
ME_URL = "/api/v1/users/me"


def profile_url(username: str) -> str:
    return f"/api/v1/users/{username}"


# --- usernames at sign-up ----------------------------------------------------------------


def test_signup_requires_username(client: TestClient) -> None:
    response = client.post(SIGNUP_URL, json={"email": "a@example.com", "password": PASSWORD})

    assert response.status_code == 422


def test_signup_lowercases_username(client: TestClient) -> None:
    response = client.post(
        SIGNUP_URL, json={"email": "a@example.com", "username": "Jane.Doe", "password": PASSWORD}
    )

    assert response.json()["username"] == "jane.doe"


@pytest.mark.parametrize(
    "username",
    ["ab", "a" * 31, "jane doe", "jane-doe", "jané", ".jane", "jane.", "ja..ne", "me", "admin"],
)
def test_signup_rejects_invalid_username(client: TestClient, username: str) -> None:
    response = client.post(
        SIGNUP_URL, json={"email": "a@example.com", "username": username, "password": PASSWORD}
    )

    assert response.status_code == 422


def test_signup_rejects_taken_username_case_insensitively(
    client: TestClient, create_user: Callable[..., AuthedUser]
) -> None:
    create_user("jane")

    response = client.post(
        SIGNUP_URL, json={"email": "other@example.com", "username": "JANE", "password": PASSWORD}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Username is already taken"}


# --- public profiles -----------------------------------------------------------------------


def test_get_profile(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    viewer = create_user("viewer")
    create_user("jane", full_name="Jane Doe")

    response = client.get(profile_url("jane"), headers=viewer.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "jane"
    assert body["full_name"] == "Jane Doe"
    assert body["avatar"] is None
    assert "email" not in body


def test_get_profile_is_case_insensitive(
    client: TestClient, create_user: Callable[..., AuthedUser]
) -> None:
    viewer = create_user("viewer")
    create_user("jane")

    assert client.get(profile_url("JANE"), headers=viewer.headers).status_code == 200


def test_get_unknown_profile(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    viewer = create_user("viewer")

    response = client.get(profile_url("nobody"), headers=viewer.headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_profile_requires_login(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    create_user("jane")

    assert client.get(profile_url("jane")).status_code == 401


# --- updating your profile -----------------------------------------------------------------


def test_update_profile_fields(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    user = create_user("jane")

    response = client.patch(
        ME_URL, headers=user.headers, json={"full_name": "Jane D", "bio": "Thrift addict"}
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Jane D"
    assert response.json()["bio"] == "Thrift addict"


def test_update_only_changes_sent_fields(
    client: TestClient, create_user: Callable[..., AuthedUser]
) -> None:
    user = create_user("jane", full_name="Jane Doe")

    client.patch(ME_URL, headers=user.headers, json={"bio": "Hi"})

    assert client.get(ME_URL, headers=user.headers).json()["full_name"] == "Jane Doe"


def test_update_null_clears_field(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    user = create_user("jane", full_name="Jane Doe")

    response = client.patch(ME_URL, headers=user.headers, json={"full_name": None})

    assert response.json()["full_name"] is None


def test_update_username(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    user = create_user("jane")

    response = client.patch(ME_URL, headers=user.headers, json={"username": "jane.new"})

    assert response.json()["username"] == "jane.new"
    assert client.get(profile_url("jane.new"), headers=user.headers).status_code == 200
    assert client.get(profile_url("jane"), headers=user.headers).status_code == 404


def test_update_username_to_own_username_is_allowed(
    client: TestClient, create_user: Callable[..., AuthedUser]
) -> None:
    user = create_user("jane")

    assert client.patch(ME_URL, headers=user.headers, json={"username": "jane"}).status_code == 200


def test_update_username_taken(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    create_user("bob")
    user = create_user("jane")

    response = client.patch(ME_URL, headers=user.headers, json={"username": "bob"})

    assert response.status_code == 409


def test_update_username_cannot_be_cleared(
    client: TestClient, create_user: Callable[..., AuthedUser]
) -> None:
    user = create_user("jane")

    assert client.patch(ME_URL, headers=user.headers, json={"username": None}).status_code == 422


def test_bio_length_limit(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    user = create_user("jane")

    assert client.patch(ME_URL, headers=user.headers, json={"bio": "x" * 161}).status_code == 422


# --- avatars -------------------------------------------------------------------------------


def test_set_and_clear_avatar(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    user = create_user("jane")
    image_id = upload_image(user)

    response = client.patch(ME_URL, headers=user.headers, json={"avatar_image_id": image_id})

    assert response.status_code == 200
    avatar = response.json()["avatar"]
    assert avatar["id"] == image_id
    assert avatar["url"].endswith(".webp")
    profile = client.get(profile_url("jane"), headers=user.headers).json()
    assert profile["avatar"]["id"] == image_id

    cleared = client.patch(ME_URL, headers=user.headers, json={"avatar_image_id": None})
    assert cleared.json()["avatar"] is None


def test_cannot_use_someone_elses_image_as_avatar(
    client: TestClient, create_user: Callable[..., AuthedUser], upload_image: Callable[[AuthedUser], str]
) -> None:
    other = create_user("bob")
    user = create_user("jane")
    image_id = upload_image(other)

    response = client.patch(ME_URL, headers=user.headers, json={"avatar_image_id": image_id})

    assert response.status_code == 400
    assert response.json() == {"detail": "Image not found"}

# --- user search ---------------------------------------------------------------------------

SEARCH_URL = "/api/v1/users/search"


def test_search_users_by_username_and_name(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    viewer = create_user("viewer")
    create_user("maya_c", full_name="Maya Chen")
    create_user("jordan_l", full_name="Jordan Lee")

    res = client.get(f"{SEARCH_URL}?q=maya", headers=viewer.headers)
    assert res.status_code == 200
    results = res.json()
    assert len(results) == 1
    assert results[0]["username"] == "maya_c"
    assert results[0]["full_name"] == "Maya Chen"
    assert results[0]["is_following"] is False


def test_search_users_excludes_viewer(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    viewer = create_user("alex_kim", full_name="Alex Kim")
    res = client.get(f"{SEARCH_URL}?q=alex", headers=viewer.headers)
    assert res.status_code == 200
    assert len(res.json()) == 0


def test_search_users_shows_is_following(client: TestClient, create_user: Callable[..., AuthedUser]) -> None:
    viewer = create_user("viewer")
    target = create_user("samira", full_name="Samira Chen")
    client.put(f"/api/v1/users/{target.username}/follow", headers=viewer.headers)

    res = client.get(f"{SEARCH_URL}?q=samira", headers=viewer.headers)
    assert res.status_code == 200
    results = res.json()
    assert len(results) == 1
    assert results[0]["username"] == "samira"
    assert results[0]["is_following"] is True


def test_search_requires_login(client: TestClient) -> None:
    assert client.get(f"{SEARCH_URL}?q=test").status_code == 401
