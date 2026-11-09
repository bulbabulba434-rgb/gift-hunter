import unittest

from hunter.config import DEFAULTS
from hunter.models import Attr, Listing
from hunter.scoring import analyze_collection, estimate_ton_rate, is_new

CFG = dict(DEFAULTS, min_score=2.5)  # tests check signals, not the production threshold


def L(slug, price, model="Basic", mp=30, bp=25, sp=20, num=5000, ton=None):
    return Listing(1, "Test", slug, num, 10000, price, ton,
                   {"model": Attr("model", model, mp), "backdrop": Attr("backdrop", "Grey", bp),
                    "symbol": Attr("symbol", "Dot", sp)})


class ScoringTest(unittest.TestCase):
    def test_plain_market_has_no_deals(self):
        ls = [L(f"a{i}", 1000 + i * 20) for i in range(20)]
        self.assertEqual(analyze_collection(ls, CFG, 200), [])

    def test_rare_near_floor_is_deal(self):
        ls = [L(f"a{i}", 1000 + i * 20) for i in range(20)] + [L("rare", 1100, bp=4)]
        deals = analyze_collection(ls, CFG, 200)
        self.assertEqual([d.listing.slug for d in deals], ["rare"])
        self.assertIn("фон", deals[0].reasons[0])

    def test_rare_but_overpriced_is_skipped(self):
        ls = [L(f"a{i}", 1000 + i * 20) for i in range(20)] + [L("rare", 5000, bp=4)]
        self.assertEqual(analyze_collection(ls, CFG, 200), [])

    def test_gap_below_same_model(self):
        ls = [L(f"a{i}", 1000 + i * 20) for i in range(10)]
        ls += [L("g1", 1500, model="Gold", mp=40), L("g2", 2500, model="Gold", mp=40),
               L("g3", 2600, model="Gold", mp=40)]
        slugs = [d.listing.slug for d in analyze_collection(ls, CFG, 200)]
        self.assertEqual(slugs, ["g1"])

    def test_floor_gap_and_low_number(self):
        ls = [L(f"a{i}", 1000 + i * 20) for i in range(10)] + [L("cheap", 800), L("low", 1010, num=7)]
        slugs = {d.listing.slug for d in analyze_collection(ls, CFG, 200)}
        self.assertEqual(slugs, {"cheap", "low"})

    def test_budget_and_ton_only(self):
        ls = [L(f"a{i}", 1000 + i * 20, ton=(1000 + i * 20) / 200) for i in range(10)]
        ls.append(Listing(1, "Test", "ton", 5000, 10000, None, 2.5,
                          {"backdrop": Attr("backdrop", "Onyx", 3)}))
        rate = estimate_ton_rate(ls, 999)
        self.assertAlmostEqual(rate, 200)
        deals = analyze_collection(ls, CFG, rate)
        self.assertEqual([d.listing.slug for d in deals], ["ton"])
        self.assertEqual(analyze_collection(ls, CFG, rate, budget=400), [])

    def test_is_new(self):
        d = analyze_collection([L(f"a{i}", 1000 + i * 20) for i in range(10)] + [L("c", 500)], CFG, 200)[0]
        self.assertTrue(is_new(d, {}))
        self.assertFalse(is_new(d, {"c": {"price": 500, "ts": 0}}))
        self.assertTrue(is_new(d, {"c": {"price": 600, "ts": 0}}))


if __name__ == "__main__":
    unittest.main()
