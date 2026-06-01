import dataclasses
from typing import Any, cast

import google.auth.transport.requests as google_transport  # type: ignore[import-untyped]
import google.oauth2.id_token as google_id_token  # type: ignore[import-untyped]
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import reffie.config as config_module

# auto_error=False lets us return 401 for missing tokens instead of FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False)


@dataclasses.dataclass
class CurrentUser:
    """Authenticated Reffie employee extracted from a verified Google ID token."""

    email: str
    name: str


def _verify_google_token(token: str, client_id: str) -> dict[str, Any]:
    """
    Call Google's token verification and return the decoded claims payload.

    :param token: Raw JWT string from the Authorization header.
    :param client_id: Google OAuth client ID to validate the ``aud`` claim against.
    :returns: Decoded claims dict (includes ``email``, ``name``, ``sub``, etc.).
    :raises ValueError: If the token is invalid, expired, or issued for the wrong audience.
    """
    return cast(
        dict[str, Any],
        google_id_token.verify_oauth2_token(  # pyright: ignore[reportUnknownMemberType]
            token,
            google_transport.Request(),
            client_id,
        ),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """
    FastAPI dependency that validates a Google ID token and enforces domain restriction.

    Extracts the Bearer token from the ``Authorization`` header, verifies it with
    Google's public keys, and confirms the email belongs to ``@reffie.me``.

    :param credentials: Bearer credentials extracted from the Authorization header.
    :returns: A :class:`CurrentUser` for the authenticated Reffie employee.
    :raises HTTPException: 401 if the token is absent, invalid, expired, or the
        email does not end with ``@reffie.me``.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = _verify_google_token(
            credentials.credentials,
            config_module.settings.google_client_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    email: str = cast(str, payload.get("email", ""))
    name: str = cast(str, payload.get("name", ""))

    if not email.endswith("@reffie.me"):
        raise HTTPException(status_code=401, detail="Unauthorized domain")

    return CurrentUser(email=email, name=name)
