"""Income projection tests: monthly detect, commission exclusion, stops."""

import unittest
from datetime import date
from decimal import Decimal

from forecast.income import (
    detect_monthly_salary,
    income_stopped_by_message,
    merge_income,
)


def _hist(dates, amt="1000.00"):
    return [(date.fromisoformat(d), Decimal(amt)) for d in dates]


class TestIncome(unittest.TestCase):
    def test_monthly_detected(self):
        h = _hist(["2025-03-15", "2025-04-15", "2025-05-15", "2025-06-15", "2025-07-15"])
        det = detect_monthly_salary(h)
        self.assertIsNotNone(det)
        self.assertEqual(det["last_amount"], Decimal("1000.00"))

    def test_weekly_rejected(self):
        h = _hist(["2024-07-04", "2024-07-11", "2024-07-18", "2024-07-25"])
        self.assertIsNone(detect_monthly_salary(h))

    def test_too_few_rejected(self):
        h = _hist(["2025-03-15", "2025-04-15"])
        self.assertIsNone(detect_monthly_salary(h))

    def test_message_stop(self):
        msgs = [{"user_id": "u", "sent_at": "2025-07-29T09:30:00Z",
                 "message_text": "The seasonal contract has ended. No off-season income confirmed."}]
        self.assertTrue(income_stopped_by_message(msgs, "u", date(2025, 8, 5)))

    def test_message_future_ignored(self):
        msgs = [{"user_id": "u", "sent_at": "2025-09-01T09:30:00Z",
                 "message_text": "Employment has ended. No regular salary after final settlement."}]
        self.assertFalse(income_stopped_by_message(msgs, "u", date(2025, 8, 5)))

    def test_bonus_pending_is_not_stop(self):
        msgs = [{"user_id": "u", "sent_at": "2024-06-01T09:30:00Z",
                 "message_text": "Bonus is still pending approval. Amount and date not approved."}]
        self.assertFalse(income_stopped_by_message(msgs, "u", date(2024, 6, 4)))

    def test_merge_prefers_scheduled(self):
        sched = [{"amount_home": 1000.0, "settlement_date": "2025-08-15"}]
        proj = [{"date": date(2025, 8, 16), "amount": Decimal("1000.00"), "kind": "x"}]
        out = merge_income(sched, proj, date(2025, 8, 5), date(2025, 11, 3))
        self.assertEqual(len(out), 1)  # projected dropped as duplicate cycle
        proj2 = [{"date": date(2025, 9, 15), "amount": Decimal("1000.00"), "kind": "x"}]
        out2 = merge_income(sched, proj2, date(2025, 8, 5), date(2025, 11, 3))
        self.assertEqual(len(out2), 2)


if __name__ == "__main__":
    unittest.main()
