"""Income projection tests: monthly detect, commission exclusion, stops,
calendar-day stepping, description-grouped streams, dead-stream exclusion."""

import unittest
from datetime import date
from decimal import Decimal

from forecast.income import (
    _add_months,
    detect_monthly_salary,
    income_stopped_by_message,
    merge_income,
    project_salary_occurrences,
)


def _ev(eid, day, amt, desc="Payroll credit"):
    return {"event_id": eid, "user_id": "u", "event_type": "income",
            "category": "salary", "direction": "credit", "status": "settled",
            "description": desc, "amount": str(amt), "currency": "USD",
            "event_date": day, "settlement_date": day,
            "linked_event_id": "", "flexibility": "", "minimum_allowed_amount": ""}


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

    def test_calendar_day_stepping_no_drift(self):
        # Dec 15 + 30d would be Jan 14; payroll lands on the 15th.
        self.assertEqual(_add_months(date(2025, 12, 15), 1), date(2026, 1, 15))
        self.assertEqual(_add_months(date(2026, 1, 31), 1), date(2026, 2, 28))  # clamped
        evs = [_ev(f"e{i}", d, "1000") for i, d in
               enumerate(["2025-09-15", "2025-10-15", "2025-11-15", "2025-12-15"])]
        occ = project_salary_occurrences(
            evs, [], "u", "USD", {}, {}, date(2026, 1, 3), date(2026, 4, 3))
        self.assertEqual([o["date"] for o in occ],
                         [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)])

    def test_two_earner_streams_both_projected(self):
        # Miniature of user_13: primary 15th + second 20th interleaved.
        evs = []
        for i, d in enumerate(["2023-10-15", "2023-11-15", "2023-12-15", "2024-01-15", "2024-02-15"]):
            evs.append(_ev(f"p{i}", d, "1343.54", "Primary household salary"))
        for i, d in enumerate(["2023-10-20", "2023-11-20", "2023-12-20", "2024-01-20"]):
            evs.append(_ev(f"s{i}", d, "881.45", "Second household income"))
        occ = project_salary_occurrences(
            evs, [], "u", "USD", {}, {}, date(2024, 3, 7), date(2024, 6, 5))
        days = sorted(o["date"].day for o in occ)
        self.assertIn(15, days)
        self.assertIn(20, days)

    def test_dead_stream_excluded(self):
        evs = [_ev(f"n{i}", d, "2000", "New employer payroll") for i, d in
               enumerate(["2024-01-15", "2024-02-15", "2024-03-15"])]
        evs += [_ev(f"o{i}", d, "1500", "Previous employer payroll") for i, d in
                enumerate(["2023-06-15", "2023-07-15", "2023-08-15"])]
        occ = project_salary_occurrences(
            evs, [], "u", "USD", {}, {}, date(2024, 3, 20), date(2024, 6, 18))
        self.assertTrue(occ)
        self.assertTrue(all(o["amount"] == Decimal("2000.00") for o in occ))


if __name__ == "__main__":
    unittest.main()
