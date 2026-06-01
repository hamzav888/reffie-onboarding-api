from unittest import mock

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from reffie.auth import CurrentUser, get_current_user

# Minimal app used only in these tests — keeps the main app unmodified.
_app = FastAPI()


@_app.get("/protected")
async def protected_endpoint(user: CurrentUser = Depends(get_current_user)) -> dict[str, str]:
    return {"email": user.email, "name": user.name}


async def test_valid_reffie_token_passes() -> None:
    with mock.patch("google.oauth2.id_token.verify_oauth2_token") as mock_verify:
        mock_verify.return_value = {"email": "alice@reffie.me", "name": "Alice Smith"}
        async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
            response = await client.get(
                "/protected", headers={"Authorization": "Bearer fake-google-token"}
            )

    assert response.status_code == 200
    assert response.json() == {"email": "alice@reffie.me", "name": "Alice Smith"}


async def test_non_reffie_domain_returns_401() -> None:
    with mock.patch("google.oauth2.id_token.verify_oauth2_token") as mock_verify:
        mock_verify.return_value = {"email": "attacker@gmail.com", "name": "Attacker"}
        async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
            response = await client.get(
                "/protected", headers={"Authorization": "Bearer fake-google-token"}
            )

    assert response.status_code == 401


async def test_expired_or_invalid_token_returns_401() -> None:
    with mock.patch("google.oauth2.id_token.verify_oauth2_token") as mock_verify:
        mock_verify.side_effect = ValueError("Token expired or invalid")
        async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
            response = await client.get("/protected", headers={"Authorization": "Bearer bad-token"})

    assert response.status_code == 401


async def test_missing_authorization_header_returns_401() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
        response = await client.get("/protected")

    assert response.status_code == 401
