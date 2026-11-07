import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("origin", ["capacitor://localhost", "ionic://localhost", "https://localhost", "http://localhost:5173"])
def test_app_origins_pass_preflight(client: TestClient, origin: str) -> None:
    response = client.options(
        "/api/v1/conversations",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_unknown_origins_are_refused(client: TestClient) -> None:
    response = client.options(
        "/api/v1/conversations",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 400
