"""
=== FILE: payments/gateways/registry.py ===

Gateway Registry — single source of truth for all supported providers.

Adding a new provider requires only:
  1. Implement BasePaymentGateway in a new file
  2. Register it in _REGISTRY below
  3. No other file needs to change

Design: lazy instantiation — gateways are created fresh per request,
not shared as singletons, to avoid state leakage between requests.
"""

from __future__ import annotations

from typing import Optional
from .base import BasePaymentGateway
from .fawry    import FawryGateway
from .vodafone import VodafoneGateway
from .bank     import MockBankGateway


# ── Registry ──────────────────────────────────────────────────────────────────
# Maps provider name → gateway class (not instance — instantiated on demand)

_REGISTRY: dict[str, type[BasePaymentGateway]] = {
    "fawry":    FawryGateway,
    "vodafone": VodafoneGateway,
    "bank":     MockBankGateway,
}

SUPPORTED_PROVIDERS: list[str] = list(_REGISTRY.keys())


def get_gateway(provider: str) -> Optional[BasePaymentGateway]:
    """
    Return a fresh gateway instance for the given provider name.
    Returns None for unknown providers — caller must handle this.
    Provider name matching is case-insensitive and whitespace-tolerant.
    """
    cls = _REGISTRY.get(provider.lower().strip() if provider else "")
    return cls() if cls else None


def is_valid_provider(provider: str) -> bool:
    """Return True if provider is registered and supported."""
    if not provider or not isinstance(provider, str):
        return False
    return provider.lower().strip() in _REGISTRY