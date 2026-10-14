"""Public deployment store (dealsniffers.com, MBOS_PUBLIC_DEPLOYMENT=1): no operator spine and no database.

Customer pages (home, privacy, terms, sign-in, Marketplace, Settings, Sell, My Bids) keep their data in per-account files and only ask
the store for the answers below. Every other call is an operator action (queue, items, decisions, capital, campaigns) and is refused,
so a public deployment can never read or change the owner's development spine."""
from __future__ import annotations


class PublicModeRefused(ValueError):
    """A ValueError so a customer form that reaches an operator action shows a plain message instead of failing."""


class PublicStore:
    lane = "public"
    owner_login = False

    def system_state(self) -> str:
        return "RUNNING"

    def ping(self) -> bool:
        return True

    def campaigns_supported(self) -> bool:
        return True                     # answer saved-search questions here, never from the shared local campaigns file

    def campaign_records(self) -> list:
        return []                       # saved searches are an operator (Wanted) feature and are not per-account yet: none on the public site

    def __getattr__(self, name):
        raise PublicModeRefused(f"'{name}' is an operator action and is not available on the public deployment")
