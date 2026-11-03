from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AuthedUser

MEMORIES_URL = "/api/v1/memories"
WARDROBE_URL = "/api/v1/wardrobe"


@pytest.fixture
def jane(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("jane")


@pytest.fixture
def bob(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("bob")


def test_create_and_list_memories(client: TestClient, jane: AuthedUser):
    res1 = client.post(
        MEMORIES_URL,
        headers=jane.headers,
        json={
            "date": "2026-11-02",
            "title": "Monday Studio Critique",
            "weather": "62°F · Crisp Autumn",
            "notes": "Red trousers stole the show.",
            "rating": 5,
            "tagged_pieces": ["Denim Jacket", "Red Trousers"],
        },
    )
    assert res1.status_code == 201
    data = res1.json()
    assert data["title"] == "Monday Studio Critique"
    assert data["date"] == "2026-11-02"
    assert data["tagged_pieces"] == ["Denim Jacket", "Red Trousers"]

    res2 = client.post(
        MEMORIES_URL,
        headers=jane.headers,
        json={
            "date": "2026-10-31",
            "title": "Halloween Party",
            "weather": "55°F · Chilly",
            "rating": 4,
            "tagged_pieces": [],
        },
    )
    assert res2.status_code == 201

    # List all
    all_res = client.get(MEMORIES_URL, headers=jane.headers)
    assert all_res.status_code == 200
    assert len(all_res.json()) == 2

    # Filter November 2026 for calendar
    nov_res = client.get(f"{MEMORIES_URL}?year=2026&month=11", headers=jane.headers)
    assert nov_res.status_code == 200
    nov_items = nov_res.json()
    assert len(nov_items) == 1
    assert nov_items[0]["title"] == "Monday Studio Critique"


def test_memory_auto_logs_wear_on_wardrobe_items(client: TestClient, jane: AuthedUser):
    # Add a wardrobe item
    w_res = client.post(
        WARDROBE_URL,
        headers=jane.headers,
        json={
            "primary_category": "clothing",
            "name": "Vintage Denim Jacket",
            "price": 120.0,
            "times_worn": 5,
        },
    )
    item_id = w_res.json()["id"]

    # Log memory tagging that piece with auto_log_wear
    client.post(
        MEMORIES_URL,
        headers=jane.headers,
        json={
            "date": "2026-11-02",
            "title": "Coffee Run",
            "tagged_pieces": ["Vintage Denim Jacket"],
            "auto_log_wear": True,
        },
    )

    # Verify times_worn incremented
    check_res = client.get(f"{WARDROBE_URL}/{item_id}", headers=jane.headers)
    assert check_res.status_code == 200
    assert check_res.json()["times_worn"] == 6


def test_memory_user_isolation_and_delete(client: TestClient, jane: AuthedUser, bob: AuthedUser):
    res = client.post(
        MEMORIES_URL,
        headers=jane.headers,
        json={"date": "2026-11-01", "title": "Jane's Sunday"},
    )
    mem_id = res.json()["id"]

    # Bob cannot view Jane's memory
    bob_res = client.get(f"{MEMORIES_URL}/{mem_id}", headers=bob.headers)
    assert bob_res.status_code == 404

    # Bob cannot delete Jane's memory
    bob_del = client.delete(f"{MEMORIES_URL}/{mem_id}", headers=bob.headers)
    assert bob_del.status_code == 404

    # Jane can delete her memory
    jane_del = client.delete(f"{MEMORIES_URL}/{mem_id}", headers=jane.headers)
    assert jane_del.status_code == 204
