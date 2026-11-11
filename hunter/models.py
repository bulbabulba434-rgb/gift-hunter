from __future__ import annotations

from dataclasses import dataclass, field

KIND_RU = {"model": "модель", "backdrop": "фон", "symbol": "символ"}


@dataclass
class Attr:
    kind: str  # model / backdrop / symbol
    name: str
    permille: float | None  # how many of 1000 gifts have it; None = unknown

    @property
    def percent(self) -> float | None:
        return None if self.permille is None else self.permille / 10


@dataclass
class Listing:
    collection_id: int
    collection: str
    slug: str
    num: int
    total: int  # how many gifts of this collection exist
    price_stars: int | None
    price_ton: float | None
    attrs: dict[str, Attr] = field(default_factory=dict)
    ton_only: bool = False

    @property
    def link(self) -> str:
        return f"https://t.me/nft/{self.slug}"

    @property
    def rarity(self) -> float | None:
        """Chance that a random gift of the collection has this exact combo (0..1)."""
        known = [a.permille for a in self.attrs.values() if a.permille]
        if not known:
            return None
        p = 1.0
        for pm in known:
            p *= pm / 1000
        return p


@dataclass
class Deal:
    listing: Listing
    price: float  # effective price in Stars
    score: float
    reasons: list[str]
    floor: float
    premium: float  # price / floor
    next_same_model: float | None
    listed_in_collection: int
    value: dict | None = None  # Telegram's own price stats for this gift
    ai: dict | None = None  # {"verdict": ..., "comment": ...}
    rare_kinds: list[str] = field(default_factory=list)  # which attributes counted as rare
    warnings: list[str] = field(default_factory=list)  # risks worth showing next to the deal
    trend: float | None = None  # collection floor change over 24h
