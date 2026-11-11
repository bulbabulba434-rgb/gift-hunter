"""Pure deal-finding logic: no network, easy to test."""
from __future__ import annotations

from statistics import median

from .models import KIND_RU, Deal, Listing

RARE_RU = {"model": "редкая", "backdrop": "редкий", "symbol": "редкий"}


def estimate_ton_rate(listings: list[Listing], fallback: float) -> float:
    """Stars per 1 TON, taken from listings that show both prices."""
    ratios = [l.price_stars / l.price_ton for l in listings if l.price_stars and l.price_ton]
    return median(ratios) if ratios else fallback


def effective_price(l: Listing, ton_rate: float) -> float | None:
    if l.price_stars:
        return float(l.price_stars)
    if l.price_ton:
        return l.price_ton * ton_rate
    return None


def analyze_collection(
    listings: list[Listing],
    cfg: dict,
    ton_rate: float,
    listed_total: int | None = None,
    budget: float = 0,
    trend: float | None = None,  # collection floor change over 24h, e.g. -0.2
) -> list[Deal]:
    priced = [(p, l) for l in listings if (p := effective_price(l, ton_rate))]
    if len(priced) < 2:
        return []
    priced.sort(key=lambda x: x[0])
    floor, second = priced[0][0], priced[1][0]
    coll_median = median(p for p, _ in priced)

    # An attribute is rare if it is both under the absolute cap and clearly rarer than
    # what is typical for that attribute kind in this collection.
    typical: dict[str, float] = {}
    for kind in ("model", "backdrop", "symbol"):
        vals = [a.permille for _, l in priced if (a := l.attrs.get(kind)) and a.permille]
        if vals:
            typical[kind] = median(vals)
    thr = {k: min(cfg["rare_permille"], v * cfg["rare_ratio"]) for k, v in typical.items()}

    def rare_of(l: Listing) -> list:
        return [a for a in l.attrs.values()
                if a.permille is not None and a.permille <= thr.get(a.kind, cfg["rare_permille"])]

    rares = [rare_of(l) for _, l in priced]
    # Model drives price most, then backdrop; symbols are rare in nearly every collection.
    weights = cfg["rare_weights"]
    min_gap = cfg["min_gap"]
    max_prem = cfg["max_premium_for_rare"]
    deals: list[Deal] = []

    for i, (p, l) in enumerate(priced):
        if budget and p > budget:
            continue
        reasons: list[str] = []
        score = 0.0
        premium = p / floor

        rare = rares[i]
        for a in rare:
            w = weights.get(a.kind, 1.0)
            score += w * (1.5 if a.permille <= thr.get(a.kind, cfg["rare_permille"]) / 2 else 1.0)
            reasons.append(f"{RARE_RU[a.kind]} {KIND_RU[a.kind]} «{a.name}» ({a.percent:.1f}%)")

        # Compare with the next pricier lot of the same model that has no extra rare
        # backdrop/symbol this one lacks (those are priced higher for other reasons).
        nxt, gap, disc = None, 0.0, 0.0
        model = l.attrs.get("model")
        model_reason = None
        if model:
            mine = {(a.kind, a.name) for a in rare}
            higher = [
                q for j, (q, o) in enumerate(priced)
                if j != i and q >= p and (om := o.attrs.get("model")) and om.name == model.name
                and {(a.kind, a.name) for a in rares[j] if a.kind != "model"} <= mine
            ]
            # One other ask can be an arbitrary number; require at least two comparables.
            if len(higher) >= cfg["min_comparables"]:
                nxt = min(higher)
                gap = 1 - p / nxt

            # Price-based value: does the market pay extra for this model, and is this lot
            # well below what that model usually asks?
            same = [q for j, (q, o) in enumerate(priced)
                    if j != i and (om := o.attrs.get("model")) and om.name == model.name]
            if len(same) >= cfg["min_model_lots"]:
                model_med = median(same)
                if model_med / coll_median >= cfg["valued_model_premium"]:
                    disc = 1 - p / model_med
                    if disc >= cfg["min_model_discount"]:
                        model_reason = (f"за модель «{model.name}» обычно просят ~{round(model_med):,} ⭐ "
                                        f"(в {model_med / coll_median:.1f}× дороже типичного), "
                                        f"этот лот на {disc:.0%} дешевле").replace(",", " ")

        gap_pts = min(gap, 0.6) * 10 if gap >= min_gap else 0.0
        disc_pts = min(disc, 0.6) * 8 if model_reason else 0.0
        if gap_pts or disc_pts:
            score += max(gap_pts, disc_pts)
            reasons.append(model_reason if disc_pts > gap_pts
                           else f"на {gap:.0%} дешевле следующего лота с моделью «{model.name}»")

        floor_gap = 1 - p / second if i == 0 else 0.0
        if floor_gap >= min_gap:
            score += min(floor_gap, 0.6) * 8
            reasons.append(f"самый дешёвый в коллекции, следующий дороже на {second / p - 1:.0%}")

        low = l.num <= cfg["low_number"]
        if low:
            score += 4 if l.num <= 10 else 3
            reasons.append(f"низкий номер #{l.num}")

        # Overpay penalty. A model the market values is naturally above the collection floor,
        # so for model-price signals measure against that model's cheapest lot instead.
        ref = floor
        if (gap_pts or disc_pts) and model:
            ref = min([p] + [q for q, o in priced if (om := o.attrs.get("model")) and om.name == model.name])
        score -= max(0.0, p / ref - 1) * 1.5

        warnings: list[str] = []
        if trend is not None and trend <= -cfg["falling_trend"]:
            score -= 1.5
            warnings.append(f"флор коллекции за сутки упал на {-trend:.0%} — цена может продолжить падать")

        qualifies = (
            ((rare or low) and premium <= max_prem)
            or gap >= min_gap
            or floor_gap >= min_gap
            or disc_pts > 0
        )
        if qualifies and score >= cfg["min_score"]:
            deals.append(
                Deal(
                    listing=l,
                    price=p,
                    score=round(score, 2),
                    reasons=reasons,
                    floor=floor,
                    premium=premium,
                    next_same_model=nxt,
                    listed_in_collection=listed_total or len(priced),
                    rare_kinds=[a.kind for a in rare],
                    warnings=warnings,
                    trend=trend,
                )
            )
    return deals


def is_new(deal: Deal, seen: dict) -> bool:
    prev = seen.get(deal.listing.slug)
    return prev is None or deal.price < prev["price"] * 0.97
