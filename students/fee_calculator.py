"""
students/fee_calculator.py

Pure fee calculation logic — no database access, no side effects.
Single responsibility: compute semester fees based on student attributes.

Functions:
  calculate_student_fees()  → returns FeeBreakdown with itemized fees
"""

from decimal import Decimal
from dataclasses import dataclass
from django.conf import settings


@dataclass
class FeeBreakdown:
    """Immutable fee breakdown for a student."""
    tuition: Decimal
    technology: Decimal
    library: Decimal
    total: Decimal

    def to_dict(self) -> dict:
        """Convert to dict for serialization."""
        return {
            "tuition": str(self.tuition),
            "technology": str(self.technology),
            "library": str(self.library),
            "total": str(self.total),
        }


def calculate_student_fees(allowed_hours: int) -> FeeBreakdown:
    """
    Calculate semester fees based on allowed credit hours.

    Defaults preserve the original project behavior:
      - Base tuition: 500 EGP per credit hour
      - Technology fee: 200 EGP fixed
      - Library fee: 100 EGP fixed

    Test suites may override the fee model through Django settings:
      - FEE_PER_CREDIT_HOUR
      - FIXED_SEMESTER_FEE   (legacy single fixed-fee contract)
      - TECHNOLOGY_FEE
      - LIBRARY_FEE
    """
    if allowed_hours <= 0:
        raise ValueError(f"allowed_hours must be positive, got {allowed_hours}")

    tuition_per_hour = Decimal(str(getattr(settings, "FEE_PER_CREDIT_HOUR", "500")))
    legacy_fixed_fee = getattr(settings, "FIXED_SEMESTER_FEE", None)

    tuition = Decimal(str(allowed_hours)) * tuition_per_hour

    if legacy_fixed_fee is not None:
        technology = Decimal(str(legacy_fixed_fee))
        library = Decimal("0")
    else:
        technology = Decimal(str(getattr(settings, "TECHNOLOGY_FEE", "200")))
        library = Decimal(str(getattr(settings, "LIBRARY_FEE", "100")))

    total = tuition + technology + library

    return FeeBreakdown(
        tuition=tuition,
        technology=technology,
        library=library,
        total=total,
    )


def apply_scholarship_discount(breakdown: FeeBreakdown, discount_percentage: Decimal) -> FeeBreakdown:
    """
    Apply a scholarship discount to the total fees.
    
    Args:
        breakdown (FeeBreakdown): Original fee breakdown
        discount_percentage (Decimal): Discount percentage (0-100)
    
    Returns:
        FeeBreakdown: Updated breakdown with discount applied to tuition
    """
    if not Decimal("0") <= discount_percentage <= Decimal("100"):
        raise ValueError(f"discount_percentage must be 0-100, got {discount_percentage}")

    discount_amount = (breakdown.tuition * discount_percentage) / Decimal("100")
    new_tuition = breakdown.tuition - discount_amount

    return FeeBreakdown(
        tuition=new_tuition,
        technology=breakdown.technology,
        library=breakdown.library,
        total=new_tuition + breakdown.technology + breakdown.library,
    )
