"""Ranking tests: deadline-completion (rule 1) beats no-changes (rule 2)."""

import unittest
from datetime import date
from decimal import Decimal

from decide import rank_key


def _cand(completes, changes, total="100.00", start="2025-01-01", n=1, oid="payment_option_01"):
    y, m, d = map(int, start.split("-"))
    return {"completes": completes, "changes": list(changes),
            "total": Decimal(total), "start": date(y, m, d), "n": n,
            "option_id": oid}


class TestRanking(unittest.TestCase):
    def test_completes_with_changes_beats_missed_deadline_without(self):
        a = _cand(True, ["stop:event_1"])   # completes, needs changes
        b = _cand(False, [])                # misses deadline, no changes
        self.assertLess(rank_key(a), rank_key(b))
        self.assertEqual(sorted([b, a], key=rank_key)[0], a)

    def test_no_changes_wins_tie_on_deadline(self):
        a = _cand(True, [])
        b = _cand(True, ["stop:event_1"])
        self.assertLess(rank_key(a), rank_key(b))

    def test_min_total_then_earlier_then_fewer_then_option_id(self):
        base = dict(completes=True, changes=[])
        cheap = _cand(True, [], total="90.00", oid="payment_option_09")
        dear = _cand(True, [], total="100.00", oid="payment_option_01")
        self.assertLess(rank_key(cheap), rank_key(dear))
        early = _cand(True, [], start="2025-01-01", oid="payment_option_05")
        late = _cand(True, [], start="2025-02-01", oid="payment_option_01")
        self.assertLess(rank_key(early), rank_key(late))


if __name__ == "__main__":
    unittest.main()
