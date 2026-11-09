"""Reads the Telegram gift resale market through the free MTProto API (Telethon)."""
from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl import functions, types

from .models import Attr, Listing

log = logging.getLogger(__name__)

# Newer gifts may report a rarity tier instead of an exact share; rough equivalents.
TIER_PERMILLE = {
    "StarGiftAttributeRarityUncommon": 100.0,
    "StarGiftAttributeRarityRare": 30.0,
    "StarGiftAttributeRarityEpic": 15.0,
    "StarGiftAttributeRarityLegendary": 5.0,
}


def _permille(a) -> float | None:
    r = getattr(a, "rarity", None)
    if r is None:
        pm = getattr(a, "rarity_permille", None)  # older layers
        return float(pm) if pm else None
    if isinstance(r, types.StarGiftAttributeRarity):
        return float(r.permille)
    return TIER_PERMILLE.get(type(r).__name__)


def parse_unique(u: types.StarGiftUnique, collection: str) -> Listing | None:
    attrs: dict[str, Attr] = {}
    for a in u.attributes:
        if isinstance(a, types.StarGiftAttributeModel):
            attrs["model"] = Attr("model", a.name, _permille(a))
        elif isinstance(a, types.StarGiftAttributeBackdrop):
            attrs["backdrop"] = Attr("backdrop", a.name, _permille(a))
        elif isinstance(a, types.StarGiftAttributePattern):
            attrs["symbol"] = Attr("symbol", a.name, _permille(a))

    stars = ton = None
    for amt in u.resell_amount or []:
        if isinstance(amt, types.StarsTonAmount):
            ton = amt.amount / 1e9
        elif isinstance(amt, types.StarsAmount):
            stars = amt.amount
    if stars is None and ton is None:
        return None
    return Listing(
        collection_id=u.gift_id,
        collection=collection or u.title,
        slug=u.slug,
        num=u.num,
        total=u.availability_total,
        price_stars=stars,
        price_ton=ton,
        attrs=attrs,
        ton_only=bool(u.resale_ton_only),
    )


class Market:
    def __init__(self, api_id: int, api_hash: str, session: str):
        self.client = TelegramClient(StringSession(session), api_id, api_hash)
        self.client.flood_sleep_threshold = 120

    async def __aenter__(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError("TG_SESSION недействительна — запусти `python -m hunter login` заново")
        return self

    async def __aexit__(self, *exc):
        await self.client.disconnect()

    async def collections(self) -> list[types.StarGift]:
        res = await self.client(functions.payments.GetStarGiftsRequest(hash=0))
        return [
            g
            for g in getattr(res, "gifts", [])
            if isinstance(g, types.StarGift) and (g.availability_resale or 0) > 0
        ]

    async def listings(self, gift: types.StarGift, pages: int, page_size: int) -> tuple[list[Listing], int]:
        title = gift.title or f"Gift {gift.id}"
        out: list[Listing] = []
        offset, total = "", 0
        for _ in range(pages):
            res = await self.client(
                functions.payments.GetResaleStarGiftsRequest(
                    gift_id=gift.id, offset=offset, limit=page_size, sort_by_price=True
                )
            )
            total = res.count
            for u in res.gifts:
                if isinstance(u, types.StarGiftUnique) and (l := parse_unique(u, title)):
                    out.append(l)
            if not res.next_offset:
                break
            offset = res.next_offset
        return out, total

    async def value_info(self, slug: str) -> dict | None:
        """Telegram's own estimate: floor / average / last sale for this gift."""
        try:
            v = await self.client(functions.payments.GetUniqueStarGiftValueInfoRequest(slug=slug))
        except Exception as e:  # not every gift has value info
            log.debug("value info %s: %s", slug, e)
            return None
        return {
            "currency": v.currency,
            "value": v.value,
            "floor": v.floor_price,
            "average": v.average_price,
            "last_sale": v.last_sale_price,
            "listed": v.listed_count,
        }
