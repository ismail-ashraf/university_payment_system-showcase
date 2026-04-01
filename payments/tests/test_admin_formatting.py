from decimal import Decimal
from django.test import TestCase
from django.utils.safestring import mark_safe

from payments.admin import _format_amount


class AdminAmountFormattingTests(TestCase):
    def test_decimal_formats(self):
        self.assertEqual(_format_amount(Decimal("1234.5")), "1,234.50")

    def test_float_formats(self):
        self.assertEqual(_format_amount(1234.5), "1,234.50")

    def test_string_formats(self):
        self.assertEqual(_format_amount("1234.5"), "1,234.50")

    def test_safestring_formats(self):
        self.assertEqual(_format_amount(mark_safe("1234.5")), "1,234.50")

    def test_none_formats(self):
        self.assertEqual(_format_amount(None), "-")

