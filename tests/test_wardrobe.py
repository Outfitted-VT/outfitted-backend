from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AuthedUser

WARDROBE_URL = "/api/v1/wardrobe"


@pytest.fixture
def jane(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("jane")


@pytest.fixture
def bob(create_user: Callable[..., AuthedUser]) -> AuthedUser:
    return create_user("bob")


def test_create_and_list_wardrobe_items(client: TestClient, jane: AuthedUser):
    # Add a shoe
    res1 = client.post(
        WARDROBE_URL,
        headers=jane.headers,
        json={
            "primary_category": "shoes",
            "name": "Retro Metallic Silver Runners",
            "brand": "ASICS",
            "price": 120.0,
            "times_worn": 4,
            "color": "#c8cbcf",
            "tag": "Streetwear Essential",
        },
    )
    assert res1.status_code == 201
    shoe_data = res1.json()
    assert shoe_data["name"] == "Retro Metallic Silver Runners"
    assert shoe_data["cost_per_wear"] == 30.0  # 120 / 4

    # Add a top
    res2 = client.post(
        WARDROBE_URL,
        headers=jane.headers,
        json={
            "primary_category": "clothing",
            "sub_category": "outerwear",
            "name": "Oversized Vintage Denim Jacket",
            "brand": "Levi's",
            "price": 150.0,
            "times_worn": 10,
            "color": "#475569",
        },
    )
    assert res2.status_code == 201

    # Add an accessory
    res3 = client.post(
        WARDROBE_URL,
        headers=jane.headers,
        json={
            "primary_category": "accessories",
            "name": "Patent Espresso Baguette Bag",
            "brand": "By Far",
            "price": 300.0,
            "times_worn": 15,
            "color": "#292524",
        },
    )
    assert res3.status_code == 201

    # List all items
    list_res = client.get(WARDROBE_URL, headers=jane.headers)
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) == 3

    # Filter by category
    filter_res = client.get(f"{WARDROBE_URL}?category=shoes", headers=jane.headers)
    assert filter_res.status_code == 200
    shoes = filter_res.json()
    assert len(shoes) == 1
    assert shoes[0]["name"] == "Retro Metallic Silver Runners"


def test_wardrobe_summary_and_cpw(client: TestClient, jane: AuthedUser):
    client.post(
        WARDROBE_URL,
        headers=jane.headers,
        json={"primary_category": "shoes", "name": "Shoe 1", "price": 100.0, "times_worn": 10},
    )
    client.post(
        WARDROBE_URL,
        headers=jane.headers,
        json={"primary_category": "clothing", "name": "Jacket 1", "price": 200.0, "times_worn": 20},
    )

    summary_res = client.get(f"{WARDROBE_URL}/summary", headers=jane.headers)
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert summary["total_pieces"] == 2
    assert summary["total_valuation"] == 300.0
    assert summary["shoes_count"] == 1
    assert summary["clothing_count"] == 1
    assert summary["average_cost_per_wear"] == 10.0  # 300 / 30


def test_log_wear_increments_and_recalculates_cpw(client: TestClient, jane: AuthedUser):
    res = client.post(
        WARDROBE_URL,
        headers=jane.headers,
        json={"primary_category": "shoes", "name": "Loafers", "price": 100.0, "times_worn": 1},
    )
    item_id = res.json()["id"]
    assert res.json()["cost_per_wear"] == 100.0

    # Log wear
    wear_res = client.post(f"{WARDROBE_URL}/{item_id}/wear", headers=jane.headers)
    assert wear_res.status_code == 200
    data = wear_res.json()
    assert data["times_worn"] == 2
    assert data["cost_per_wear"] == 50.0  # 100 / 2
    assert data["last_worn_at"] is not None


def test_wardrobe_isolation_between_users(client: TestClient, jane: AuthedUser, bob: AuthedUser):
    res = client.post(
        WARDROBE_URL,
        headers=jane.headers,
        json={"primary_category": "clothing", "name": "Jane's Trench", "price": 250.0},
    )
    item_id = res.json()["id"]

    # Bob cannot view Jane's wardrobe item
    bob_res = client.get(f"{WARDROBE_URL}/{item_id}", headers=bob.headers)
    assert bob_res.status_code == 404

    # Bob cannot delete Jane's item
    del_res = client.delete(f"{WARDROBE_URL}/{item_id}", headers=bob.headers)
    assert del_res.status_code == 404

    # Jane can delete her item
    jane_del = client.delete(f"{WARDROBE_URL}/{item_id}", headers=jane.headers)
    assert jane_del.status_code == 204
