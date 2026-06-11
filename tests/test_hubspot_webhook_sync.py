"""
Tests for the sync_deal_property and sync_company_property background handlers —
applying a single HubSpot property webhook change to the matching account.
"""

import uuid
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import SQLAlchemyError

from reffie.hubspot.webhook_sync import sync_company_property, sync_deal_property
from reffie.models import Account

_DEAL_ID = "deal-9001"
_COMPANY_ID = "company-8001"


def _make_account(
    deal_id: str = _DEAL_ID,
    company_id: str | None = None,
    cs_rep: str = "Alice",
) -> Account:
    account = Account(
        id=uuid.uuid4(),
        hubspot_deal_id=deal_id,
        hubspot_company_id=company_id,
        company_name="Test Co",
        location="Austin, TX",
        property_type="SFR",
        cs_rep=cs_rep,
        onboarding_stage="Pre-kick off",
        tech_stack={},
        skipped_stages=[],
        archived=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    account.pocs = []
    account.checklist_items = []
    return account


def _patch_db(account: Account | None) -> tuple[AbstractContextManager[Any], AsyncMock]:
    """Patch AsyncSessionLocal; return the patcher and the underlying mock session."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = account
    mock_session.execute = AsyncMock(return_value=execute_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    patcher: AbstractContextManager[Any] = mock.patch(
        "reffie.db.session.AsyncSessionLocal", MagicMock(return_value=mock_session)
    )
    return patcher, mock_session


async def test_sync_cs_rep_updates_existing_account() -> None:
    account = _make_account(cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_deal_property(_DEAL_ID, "onboarding_cs_rep", "Bob")
    assert account.cs_rep == "Bob"
    session.commit.assert_awaited_once()


async def test_sync_cs_rep_strips_whitespace() -> None:
    account = _make_account(cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_deal_property(_DEAL_ID, "onboarding_cs_rep", "  Bob  ")
    assert account.cs_rep == "Bob"
    session.commit.assert_awaited_once()


async def test_sync_cs_rep_account_missing_is_noop() -> None:
    patcher, session = _patch_db(None)
    with patcher:
        await sync_deal_property(_DEAL_ID, "onboarding_cs_rep", "Bob")
    session.commit.assert_not_awaited()


async def test_sync_cs_rep_empty_value_preserves_existing() -> None:
    account = _make_account(cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_deal_property(_DEAL_ID, "onboarding_cs_rep", "")
    # Blank value must NOT overwrite the existing rep, and must not touch the DB.
    assert account.cs_rep == "Alice"
    session.execute.assert_not_called()
    session.commit.assert_not_awaited()


async def test_sync_cs_rep_none_value_preserves_existing() -> None:
    account = _make_account(cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_deal_property(_DEAL_ID, "onboarding_cs_rep", None)
    assert account.cs_rep == "Alice"
    session.execute.assert_not_called()
    session.commit.assert_not_awaited()


async def test_sync_cs_rep_whitespace_only_preserves_existing() -> None:
    account = _make_account(cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_deal_property(_DEAL_ID, "onboarding_cs_rep", "   ")
    assert account.cs_rep == "Alice"
    session.execute.assert_not_called()
    session.commit.assert_not_awaited()


async def test_sync_unmapped_property_is_noop() -> None:
    account = _make_account(cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_deal_property(_DEAL_ID, "amount", "120000")
    assert account.cs_rep == "Alice"
    session.execute.assert_not_called()
    session.commit.assert_not_awaited()


async def test_sync_db_error_is_caught() -> None:
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=SQLAlchemyError("DB connection error"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    with mock.patch("reffie.db.session.AsyncSessionLocal", MagicMock(return_value=mock_session)):
        # Reaching the assertion without raising confirms the error is swallowed.
        await sync_deal_property(_DEAL_ID, "onboarding_cs_rep", "Bob")
    mock_session.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# sync_company_property
# ---------------------------------------------------------------------------


async def test_sync_company_cs_rep_updates_account() -> None:
    account = _make_account(company_id=_COMPANY_ID, cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_company_property(_COMPANY_ID, "onboarding_cs_rep", "Carol")
    assert account.cs_rep == "Carol"
    session.commit.assert_awaited_once()


async def test_sync_company_cs_rep_strips_whitespace() -> None:
    account = _make_account(company_id=_COMPANY_ID, cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_company_property(_COMPANY_ID, "onboarding_cs_rep", "  Carol  ")
    assert account.cs_rep == "Carol"
    session.commit.assert_awaited_once()


async def test_sync_company_cs_rep_account_missing_is_noop() -> None:
    patcher, session = _patch_db(None)
    with patcher:
        await sync_company_property(_COMPANY_ID, "onboarding_cs_rep", "Carol")
    session.commit.assert_not_awaited()


async def test_sync_company_cs_rep_empty_value_preserves_existing() -> None:
    account = _make_account(company_id=_COMPANY_ID, cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_company_property(_COMPANY_ID, "onboarding_cs_rep", "")
    assert account.cs_rep == "Alice"
    session.execute.assert_not_called()
    session.commit.assert_not_awaited()


async def test_sync_company_cs_rep_none_value_preserves_existing() -> None:
    account = _make_account(company_id=_COMPANY_ID, cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_company_property(_COMPANY_ID, "onboarding_cs_rep", None)
    assert account.cs_rep == "Alice"
    session.execute.assert_not_called()
    session.commit.assert_not_awaited()


async def test_sync_company_unmapped_property_is_noop() -> None:
    account = _make_account(company_id=_COMPANY_ID, cs_rep="Alice")
    patcher, session = _patch_db(account)
    with patcher:
        await sync_company_property(_COMPANY_ID, "state", "Texas")
    assert account.cs_rep == "Alice"
    session.execute.assert_not_called()
    session.commit.assert_not_awaited()


async def test_sync_company_db_error_is_caught() -> None:
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=SQLAlchemyError("DB connection error"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    with mock.patch("reffie.db.session.AsyncSessionLocal", MagicMock(return_value=mock_session)):
        await sync_company_property(_COMPANY_ID, "onboarding_cs_rep", "Carol")
    mock_session.commit.assert_not_awaited()
