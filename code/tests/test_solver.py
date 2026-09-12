"""Solver tests: binary search bounds + earliest scan (deterministic)."""

import unittest
from datetime import date, timedelta
from decimal import Decimal

from forecast.safety import build_base_balances
from forecast.solver import amount_safe_to_pay, earliest_date_for_full_payment


def _dates(s: str, n: int = 91) -> list[date]:
    y, m, d = map(int, s.split("-"))
    base = date(y, m, d)
    return [base + timedelta(days=i) for i in range(n)]


class TestSolver(unittest.TestCase):
    def test_full_safe_today(self):
        ds = _dates("2024-03-03", 10)
        base = [Decimal("50000.00")] * 10
        req = Decimal("25256.00")
        self.assertEqual(amount_safe_to_pay(base, ds, Decimal("18000"), req), req)
        self.assertEqual(
            earliest_date_for_full_payment(base, ds, Decimal("18000"), req), ds[0]
        )

    def test_nothing_safe(self):
        ds = _dates("2024-03-03", 10)
        base = [Decimal("100.00")] * 10
        req = Decimal("5000.00")
        self.assertEqual(amount_safe_to_pay(base, ds, Decimal("800"), req), Decimal("0.00"))
        self.assertIsNone(earliest_date_for_full_payment(base, ds, Decimal("800"), req))

    def test_becomes_safe_later(self):
        ds = _dates("2024-03-03", 10)
        # Salary 20000 lands on day 5.
        base = [Decimal("5000.00")] * 5 + [Decimal("25000.00")] * 5
        req = Decimal("10000.00")
        self.assertLess(amount_safe_to_pay(base, ds, Decimal("1000"), req), req)
        self.assertEqual(
            earliest_date_for_full_payment(base, ds, Decimal("1000"), req), ds[5]
        )

    def test_bounds_invariant(self):
        ds = _dates("2026-01-03", 91)
        base = [Decimal("1942.40")] * 91
        for req_s in ("620.40", "0.01", "100000.00"):
            req = Decimal(req_s)
            safe = amount_safe_to_pay(base, ds, Decimal("800"), req)
            self.assertTrue(Decimal("0.00") <= safe <= req)


if __name__ == "__main__":
    unittest.main()
