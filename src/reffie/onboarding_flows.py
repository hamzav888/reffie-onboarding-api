"""
Product-to-onboarding-flow registry.

To add support for a new product: add an entry to ``PRODUCT_FLOWS``.
No other code changes are required.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OnboardingFlow:
    """
    Maps a product SKU to the platform onboarding configuration it triggers.

    :param sku: HubSpot product SKU (uppercase canonical form).
    :param product_name: Human-readable product name used in logs and UI.
    :param initial_stage: Platform stage the account starts at on creation.
    """

    sku: str
    product_name: str
    initial_stage: str


PRODUCT_FLOWS: dict[str, OnboardingFlow] = {
    "PRO": OnboardingFlow(
        sku="PRO",
        product_name="Pro",
        initial_stage="Pre-kick off",
    ),
}


def flow_for_sku(sku: str | None) -> OnboardingFlow | None:
    """
    Return the :class:`OnboardingFlow` for a given product SKU, or ``None``.

    Matching is case-insensitive — the SKU is uppercased before lookup.

    :param sku: Product SKU from a HubSpot line item, or ``None``.
    :returns: Matching flow, or ``None`` if unrecognised.
    """
    if sku is None:
        return None
    return PRODUCT_FLOWS.get(sku.upper())
