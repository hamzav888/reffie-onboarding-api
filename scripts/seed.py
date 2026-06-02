import asyncio
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

import reffie.db.session as db_session_module
from reffie.models import Account

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


async def main() -> None:
    """
    Seed the database with demo accounts for development and testing.

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

            session.add(
                Account(
                    id=uuid.uuid4(),
                    hubspot_deal_id=None,
                    company_name=company_name,
                    location=data["location"],
                    property_type=data["property_type"],
                    arr=data["arr"],
                    contract_length=data["contract_length"],
                    success_metrics=data["success_metrics"],
                    onboarding_stage=data["onboarding_stage"],
                    cs_rep=_CS_REP,
                    skipped_stages=[],
                )
            )
            print(f"[ADD]  {company_name}")
            added += 1

        await session.commit()

    print(f"Done. Added {added}, skipped {skipped}.")


if __name__ == "__main__":
    asyncio.run(main())
