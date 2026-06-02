import asyncio
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select

import reffie.db.session as db_session_module
from reffie.models import Account, ChecklistItem

# Canonical stage order — must match PLATFORM_STAGES in reffie.constants.
STAGE_ORDER: list[str] = [
    "Pre-kick off",
    "Kick-off call",
    "Validation call",
    "Training call",
    "Check-in (1 week post training)",
    "Check-in (3 weeks post training)",
    "30-day check-in",
    "60-day check-in",
]

# Deterministic step IDs per stage, mirroring the frontend's stepsEngine.js.
# The frontend's syncChecklist reconciles gracefully: orphaned items are dropped
# on the next mutation; missing items are initialised fresh client-side.
STAGE_STEPS: dict[str, list[str]] = {
    "Pre-kick off": [
        "pre-kick-off__welcome",
        "pre-kick-off__confirm",
        "pre-kick-off__schedule-kickoff",
    ],
    "Kick-off call": [
        "kick-off-call__pms",
        "kick-off-call__tour",
        "kick-off-call__apps",
    ],
    "Validation call": [
        "validation-call__val1",
        "validation-call__val2",
        "validation-call__schedule-training",
    ],
    "Training call": [
        "training-call__tr1",
        "training-call__tr2",
        "training-call__tr3",
        "training-call__schedule-checkin",
    ],
    "Check-in (1 week post training)": [
        "check-in-1-week-post-training__w1a",
        "check-in-1-week-post-training__w1b",
    ],
    "Check-in (3 weeks post training)": [
        "check-in-3-weeks-post-training__w3a",
        "check-in-3-weeks-post-training__w3b",
    ],
    "30-day check-in": [
        "30-day-check-in__d30a",
        "30-day-check-in__d30b",
    ],
    "60-day check-in": [
        "60-day-check-in__d60a",
        "60-day-check-in__d60b",
    ],
}

SEED_ACCOUNTS: list[dict[str, Any]] = [
    {
        "company_name": "Maple Property Group",
        "location": "Austin, TX",
        "property_type": "SFR",
        "arr": Decimal("24000"),
        "contract_length": "12 months",
        "success_metrics": "Reduce lead response time below 5 minutes",
        "onboarding_stage": "Kick-off call",
    },
    {
        "company_name": "Verdant Realty Partners",
        "location": "Denver, CO",
        "property_type": "Multifamily",
        "arr": Decimal("41500"),
        "contract_length": "24 months",
        "success_metrics": "Improve tour conversion rate to 35 percent",
        "onboarding_stage": "Training call",
    },
    {
        "company_name": "Clearview Homes LLC",
        "location": "Phoenix, AZ",
        "property_type": "SFR",
        "arr": Decimal("18000"),
        "contract_length": "12 months",
        "success_metrics": "Streamline new agent onboarding",
        "onboarding_stage": "Pre-kick off",
    },
    {
        "company_name": "Sunrise Urban Living",
        "location": "Nashville, TN",
        "property_type": "Multifamily",
        "arr": Decimal("62000"),
        "contract_length": "24 months",
        "success_metrics": "Hit 90 percent occupancy by Q2",
        "onboarding_stage": "Check-in (1 week post training)",
    },
]

_CS_REP = "Angelina LaPerla"

# Fixed timestamp used for all Phase 1 completed checklist items.
_SEED_TS = datetime(2026, 5, 1, tzinfo=UTC)

DEFAULT_TS: dict[str, Any] = {
    "pms": "",
    "tour": "None",
    "lockboxes": False,
    "applications": "None",
    "zillow": "None",
    "facebook": False,
    "sharedEmail": False,
    "sharedEmailAddr": "",
    "sharedEmailAddrs": [],
    "other": "",
}


def _done_item(account_id: uuid.UUID, step_id: str) -> ChecklistItem:
    """
    Build a completed :class:`~reffie.models.checklist_item.ChecklistItem`.

    Uses the fixed Phase 1 seed timestamp for both ``first_touched_at`` and
    ``completed_at``.

    :param account_id: UUID of the owning account.
    :param step_id: Deterministic step identifier.
    :returns: Transient ChecklistItem ready to be added to the session.
    """
    return ChecklistItem(
        id=uuid.uuid4(),
        account_id=account_id,
        step_id=step_id,
        done=True,
        note="",
        first_touched_at=_SEED_TS,
        completed_at=_SEED_TS,
    )


async def main() -> None:
    """
    Seed the database with demo accounts and Phase 1 checklist state.

    For each account, checklist items belonging to stages strictly before the
    account's current ``onboarding_stage`` are inserted as ``done=True`` with
    fixed May 2026 timestamps. Items at or after the current stage are omitted
    so the frontend's ``syncChecklist`` initialises them fresh on first visit.

    Checks each account by ``company_name`` before inserting — idempotent
    across repeated runs. All new rows are committed in a single transaction.
    """
    added = 0
    skipped = 0

    async with db_session_module.AsyncSessionLocal() as session:
        for data in SEED_ACCOUNTS:
            company_name: str = data["company_name"]
            result = await session.execute(
                select(Account).where(Account.company_name == company_name)
            )
            if result.scalar_one_or_none() is not None:
                print(f"[SKIP] {company_name} already exists")
                skipped += 1
                continue

            account_id = uuid.uuid4()
            onboarding_stage: str = data["onboarding_stage"]

            session.add(
                Account(
                    id=account_id,
                    hubspot_deal_id=None,
                    company_name=company_name,
                    location=data["location"],
                    property_type=data["property_type"],
                    arr=data["arr"],
                    contract_length=data["contract_length"],
                    success_metrics=data["success_metrics"],
                    onboarding_stage=onboarding_stage,
                    cs_rep=_CS_REP,
                    tech_stack=DEFAULT_TS,
                    skipped_stages=[],
                )
            )

            # Insert completed items for every stage strictly before the current one.
            current_idx = (
                STAGE_ORDER.index(onboarding_stage) if onboarding_stage in STAGE_ORDER else 0
            )
            for stage in STAGE_ORDER[:current_idx]:
                for step_id in STAGE_STEPS[stage]:
                    session.add(_done_item(account_id, step_id))

            # Maple is mid-Kick-off: pms + tour already done, apps still pending.
            if company_name == "Maple Property Group":
                for step_id in ["kick-off-call__pms", "kick-off-call__tour"]:
                    session.add(_done_item(account_id, step_id))

            print(f"[ADD]  {company_name}")
            added += 1

        await session.commit()

    print(f"Done. Added {added}, skipped {skipped}.")


async def reset() -> None:
    """
    Delete all 4 demo accounts and their cascaded checklist items and POCs.

    Matches only by exact ``company_name`` — never touches any other data.
    Safe to run multiple times; a no-op if the accounts do not exist.
    The DB-level ``ON DELETE CASCADE`` on POCs and checklist items handles
    the child rows automatically.
    """
    names = [str(data["company_name"]) for data in SEED_ACCOUNTS]
    async with db_session_module.AsyncSessionLocal() as session:
        await session.execute(delete(Account).where(Account.company_name.in_(names)))
        await session.commit()
    print(f"Reset: removed {len(names)} demo account(s) (if present).")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        asyncio.run(reset())
    else:
        asyncio.run(main())
