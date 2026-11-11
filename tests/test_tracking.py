import unittest

from hunter import tracking as tr
from hunter.config import DEFAULTS
from hunter.models import Attr, Listing
from hunter.scoring import analyze_collection

H = 3600


def L(slug, price, coll="Pepe", model="Basic", mp=30):
    return Listing(1, coll, slug, 5000, 10000, price, None,
                   {"model": Attr("model", model, mp), "backdrop": Attr("backdrop", "Grey", 25),
                    "symbol": Attr("symbol", "Dot", 20)})


class HistoryTest(unittest.TestCase):
    def test_hourly_points_and_trend(self):
        h = {}
        for i in range(26):
            tr.record_floors(h, {"Pepe": 1000 - i * 10}, i * H)
        tr.record_floors(h, {"Pepe": 740}, 25 * H + 60)  # same hour -> overwrite
        self.assertEqual(len(h["Pepe"]), 26)
        self.assertEqual(h["Pepe"][-1][1], 740)
        self.assertAlmostEqual(tr.trend(h, "Pepe", 25 * H), 740 / 990 - 1, places=3)
        self.assertIsNone(tr.trend({"Pepe": [[0, 1000]]}, "Pepe", H))

    def test_movers(self):
        h = {"Up": [[0, 100], [24 * H, 130]], "Down": [[0, 100], [24 * H, 70]], "Flat": [[0, 100], [24 * H, 100]]}
        risers, fallers = tr.movers(h, 24 * H)
        self.assertEqual([t for t, _ in risers], ["Up"])
        self.assertEqual([t for t, _ in fallers], ["Down"])


class WatchTest(unittest.TestCase):
    def test_parse_watch(self):
        self.assertEqual(tr.parse_watch("Plush Pepe"), ("Plush Pepe", None, None))
        self.assertEqual(tr.parse_watch("Plush Pepe / Kung Fu Pepe 500000"), ("Plush Pepe", "Kung Fu Pepe", 500000))

    def test_floor_drop_alert_once(self):
        watch = {"pepe": {"collection": "Pepe", "model": None, "max_price": None}}
        price = lambda l: l.price_stars  # noqa: E731
        self.assertEqual(tr.check_watch(watch, [L("a", 1000), L("b", 1100)], price, 0.1), [])
        alerts = tr.check_watch(watch, [L("c", 850), L("b", 1100)], price, 0.1)
        self.assertEqual(len(alerts), 1)
        self.assertIn("15%", alerts[0][2])
        self.assertEqual(tr.check_watch(watch, [L("c", 850)], price, 0.1), [])  # no repeat

    def test_model_filter_and_target_price(self):
        watch = {"k": {"collection": "Pepe", "model": "Gold", "max_price": 2000}}
        price = lambda l: l.price_stars  # noqa: E731
        alerts = tr.check_watch(watch, [L("a", 500), L("g", 1900, model="Gold"), L("x", 100, coll="Other")], price, 0.1)
        self.assertEqual([a[1].slug for a in alerts], ["g"])

    def test_suggest(self):
        self.assertEqual(tr.suggest("plush pepa", ["Plush Pepe", "Durov's Cap"]), "Plush Pepe")


class ScoringExtrasTest(unittest.TestCase):
    CFG = dict(DEFAULTS, min_score=2.5)

    def test_valued_model_discount(self):
        ls = [L(f"a{i}", 1000 + i * 10) for i in range(10)]
        ls += [L(f"g{i}", 2500 + i * 500, model="Gold") for i in range(4)] + [L("cheapgold", 1900, model="Gold")]
        deals = {d.listing.slug: d for d in analyze_collection(ls, self.CFG, 200)}
        self.assertIn("cheapgold", deals)
        self.assertIn("обычно просят", deals["cheapgold"].reasons[0])

    def test_falling_collection_is_penalised(self):
        ls = [L(f"a{i}", 1000 + i * 20) for i in range(10)] + [L("cheap", 700)]
        calm = analyze_collection(ls, self.CFG, 200)[0]
        falling = analyze_collection(ls, self.CFG, 200, trend=-0.3)[0]
        self.assertLess(falling.score, calm.score)
        self.assertTrue(falling.warnings)


if __name__ == "__main__":
    unittest.main()
