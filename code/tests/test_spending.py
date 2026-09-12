"""Spending tests: flexible-only, max 3, no dup event, format."""

import unittest
from datetime import date
from decimal import Decimal

from forecast.spending import format_spending_amount, plan_spending_candidates


def _occ(key: str, eid: str, n: int = 3, amt: str = "300.00"):
    from datetime import timedelta
    base = date(2026, 1, 3)
    return [
        {"date": base + timedelta(days=30 * (i + 1)), "amount": Decimal(amt),
         "series_key": key, "category": "streaming", "essential": False,
         "flexible": True, "representative_event_id": eid}
        for i in range(n)
    ]


class TestSpending(unittest.TestCase):
    def test_stop_preferred_for_max_savings(self):
        rec = [{"series_key": "u|streaming", "category": "streaming", "flexible": True,
                "flexibility": "reducible_or_stoppable", "forecast_amount": "300.00",
                "minimum_allowed_amount": "150.00", "representative_event_id": "event_1"}]
        occ = _occ("u|streaming", "event_1")
        actions, stop, rmap = plan_spending_candidates(
            rec, occ, {"streaming"}, {"streaming"}, "EUR")
        self.assertEqual(actions, ["stop:event_1"])
        self.assertEqual(stop, {"u|streaming"})
        self.assertEqual(rmap, {})

    def test_reduce_only_when_stop_not_permitted(self):
        rec = [{"series_key": "u|dining", "category": "dining", "flexible": True,
                "flexibility": "reducible", "forecast_amount": "1000.00",
                "minimum_allowed_amount": "489.50", "representative_event_id": "event_9"}]
        occ = _occ("u|dining", "event_9", n=2, amt="1000.00")
        for o in occ:
            o["category"] = "dining"
        actions, stop, rmap = plan_spending_candidates(
            rec, occ, {"dining"}, set(), "ZAR")
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].startswith("reduce_to:event_9:"))
        self.assertEqual(stop, set())

    def test_max_three_and_deterministic(self):
        rec, occ = [], []
        for i in range(5):
            rec.append({"series_key": f"u|c{i}", "category": "streaming", "flexible": True,
                        "flexibility": "stoppable", "forecast_amount": "100.00",
                        "minimum_allowed_amount": "", "representative_event_id": f"event_{i}"})
            occ += _occ(f"u|c{i}", f"event_{i}", n=1)
        actions, _, _ = plan_spending_candidates(rec, occ, set(), {"streaming"}, "EUR")
        self.assertEqual(len(actions), 3)

    def test_format(self):
        self.assertEqual(format_spending_amount(Decimal("665950.00"), "IDR"), "665950")
        self.assertEqual(format_spending_amount(Decimal("23.50"), "USD"), "23.50")


if __name__ == "__main__":
    unittest.main()
