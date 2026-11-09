import unittest

from telethon.tl import types

from hunter.market import parse_unique


def doc():
    return types.DocumentEmpty(id=1)


class ParseTest(unittest.TestCase):
    def test_parse_real_telethon_objects(self):
        u = types.StarGiftUnique(
            id=1, gift_id=55, title="Plush Pepe", slug="PlushPepe-123", num=123,
            availability_issued=2000, availability_total=2500,
            attributes=[
                types.StarGiftAttributeModel(name="Gold", document=doc(),
                                             rarity=types.StarGiftAttributeRarity(permille=8)),
                types.StarGiftAttributeBackdrop(name="Onyx", backdrop_id=1, center_color=0, edge_color=0,
                                                pattern_color=0, text_color=0,
                                                rarity=types.StarGiftAttributeRarityLegendary()),
                types.StarGiftAttributePattern(name="Crown", document=doc(),
                                               rarity=types.StarGiftAttributeRarity(permille=4)),
            ],
            resell_amount=[types.StarsAmount(amount=12500, nanos=0), types.StarsTonAmount(amount=45_200_000_000)],
        )
        l = parse_unique(u, "Plush Pepe")
        self.assertEqual((l.price_stars, l.price_ton, l.num, l.total), (12500, 45.2, 123, 2500))
        self.assertEqual(l.attrs["model"].permille, 8)
        self.assertEqual(l.attrs["backdrop"].permille, 5)
        self.assertEqual(l.attrs["symbol"].name, "Crown")
        self.assertEqual(l.link, "https://t.me/nft/PlushPepe-123")

    def test_unlisted_gift_is_skipped(self):
        u = types.StarGiftUnique(id=1, gift_id=55, title="X", slug="X-1", num=1, attributes=[],
                                 availability_issued=1, availability_total=1)
        self.assertIsNone(parse_unique(u, "X"))


if __name__ == "__main__":
    unittest.main()
