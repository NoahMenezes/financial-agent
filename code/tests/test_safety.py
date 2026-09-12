"""Unit tests for safety predicate (stdlib unittest, no deps)."""

import unittest
from datetime import date
from decimal import Decimal

from forecast.safety import build_base_balances, is_safe_with_payments


def _dates(s: str, n: int = 5) -> list[date]:
    y, m, d = map(int, s.split("-"))
    base = date(y, m, d)
    from datetime import timedelta
    return [base + timedelta(days=i) for i in range(n)]


class TestSafety(unittest.TestCase):
    def test_base_cumulative(self):
        ds = _dates("2024-03-03", 3)
        nets = {ds[1]: Decimal("-100.00")}
        out = build_base_balances(Decimal("1000.00"), nets, ds)
        self.assertEqual(out, [Decimal("1000.00"), Decimal("900.00"), Decimal("900.00")])

    def test_safe_and_unsafe(self):
        ds = _dates("2024-03-03", 3)
        base = [Decimal("1000.00")] * 3
        self.assertTrue(is_safe_with_payments(base, ds, {ds[0]: Decimal("100.00")}, Decimal("800")))
        self.assertFalse(is_safe_with_payments(base, ds, {ds[0]: Decimal("300.00")}, Decimal("800")))

    def test_future_expense_matters(self):
        ds = _dates("2024-03-03", 3)
        base = [Decimal("1000.00"), Decimal("850.00"), Decimal("850.00")]
        # 100 today leaves 750 on day1 < 800 -> unsafe even though day0 ok.
        self.assertFalse(is_safe_with_payments(base, ds, {ds[0]: Decimal("100.00")}, Decimal("800")))
        # Waiting until day2 is safe.
        self.assertTrue(is_safe_with_payments(base, ds, {ds[2]: Decimal("50.00")}, Decimal("800")))


if __name__ == "__main__":
    unittest.main()
