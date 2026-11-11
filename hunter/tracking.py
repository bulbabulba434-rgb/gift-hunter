"""Floor history, trends, watchlist alerts and the daily digest. Pure functions over State data."""
from __future__ import annotations

import difflib
from html import escape

from .fmt import stars, tree
from .models import Listing

HOUR = 3600
HISTORY_DAYS = 14


# ---------- floor history & trends ----------

def record_floors(history: dict, floors: dict[str, float], now: float) -> None:
    """Keep one floor point per collection per hour, for HISTORY_DAYS."""
    for title, floor in floors.items():
        pts = history.setdefault(title, [])
        if not pts or now - pts[-1][0] >= HOUR - 60:
            pts.append([int(now), round(floor, 2)])
        else:
            pts[-1][1] = round(floor, 2)  # same hour: keep the latest value
        cutoff = now - HISTORY_DAYS * 24 * HOUR
        while pts and pts[0][0] < cutoff:
            pts.pop(0)


def trend(history: dict, title: str, now: float, hours: int = 24) -> float | None:
    """Floor change vs ~`hours` ago (e.g. -0.12 = fell 12%). None if not enough history."""
    pts = history.get(title) or []
    if len(pts) < 2:
        return None
    target = now - hours * HOUR
    old = min(pts, key=lambda p: abs(p[0] - target))
    if abs(old[0] - target) > hours * HOUR * 0.25 or not old[1]:
        return None
    return pts[-1][1] / old[1] - 1


def movers(history: dict, now: float, n: int = 3) -> tuple[list, list]:
    ch = [(t, c) for t in history if (c := trend(history, t, now)) is not None]
    ch.sort(key=lambda x: x[1])
    fallers = [x for x in ch[:n] if x[1] < -0.01]
    risers = [x for x in reversed(ch[-n:]) if x[1] > 0.01]
    return risers, fallers


# ---------- watchlist ----------

def parse_watch(text: str) -> tuple[str, str | None, float | None]:
    """'Plush Pepe / Kung Fu Pepe 500000' -> ('Plush Pepe', 'Kung Fu Pepe', 500000)."""
    words = text.split()
    price = None
    if words and words[-1].replace(" ", "").isdigit():
        price = float(words.pop())
    rest = " ".join(words)
    coll, _, model = rest.partition("/")
    return coll.strip(), (model.strip() or None), price


def watch_key(coll: str, model: str | None) -> str:
    return f"{coll} / {model}" if model else coll


def suggest(name: str, known: list[str]) -> str | None:
    m = difflib.get_close_matches(name.lower(), [k.lower() for k in known], n=1, cutoff=0.6)
    if not m:
        return None
    return next(k for k in known if k.lower() == m[0])


def _matches(l: Listing, w: dict) -> bool:
    if l.collection.lower() != w["collection"].lower():
        return False
    m = l.attrs.get("model")
    return not w.get("model") or (m is not None and m.name.lower() == w["model"].lower())


def check_watch(watch: dict, listings: list[Listing], price_of, drop: float) -> list[tuple[dict, Listing, str]]:
    """Returns (watch item, cheapest listing, reason) for items that need an alert. Mutates refs."""
    alerts = []
    for w in watch.values():
        hits = [(price_of(l), l) for l in listings if _matches(l, w)]
        hits = [(p, l) for p, l in hits if p]
        if not hits:
            continue
        p, l = min(hits, key=lambda x: x[0])
        ref = w.get("ref_floor")
        reason = None
        if w.get("max_price") and p <= w["max_price"] and w.get("alerted_slug") != l.slug:
            reason = f"есть лот по твоей цене (до {stars(w['max_price'])})"
            w["alerted_slug"] = l.slug
        elif ref and p <= ref * (1 - drop):
            reason = f"флор упал на {1 - p / ref:.0%}: {stars(ref)} → {stars(p)}"
        if reason:
            alerts.append((w, l, reason))
            w["ref_floor"] = p
        elif ref is None or p > ref:
            w["ref_floor"] = p  # track the recent high so drops are measured from it
        w["last_floor"] = p
    return alerts


def format_watch_alert(w: dict, l: Listing, price: float, reason: str) -> str:
    return "\n".join([
        f"👀 <b>Вотчлист: {escape(watch_key(w['collection'], w.get('model')))}</b>",
        "",
        f"1. {escape(reason[:1].upper() + reason[1:])}",
        f"2. Самый дешёвый лот: <b>{escape(l.collection)} #{l.num}</b> — {stars(price)}",
    ])


def format_watchlist(watch: dict) -> str:
    if not watch:
        return ("👀 <b>Вотчлист пуст</b>\n\n"
                "Добавь коллекцию: /watch Plush Pepe\n"
                "Или модель с лимитом цены: /watch Plush Pepe / Kung Fu Pepe 500000")
    lines = ["👀 <b>Вотчлист</b>", ""]
    for i, w in enumerate(watch.values(), 1):
        extra = []
        if w.get("last_floor"):
            extra.append(f"сейчас от {stars(w['last_floor'])}")
        if w.get("max_price"):
            extra.append(f"жду до {stars(w['max_price'])}")
        lines.append(f"{i}. {escape(watch_key(w['collection'], w.get('model')))}"
                     + (f" — {', '.join(extra)}" if extra else ""))
    lines += ["", "Убрать: /unwatch номер"]
    return "\n".join(lines)


# ---------- daily digest ----------

def format_digest(day_deals: dict, history: dict, scans: int, now: float) -> str:
    out = ["🗞 <b>Сводка за сутки</b>", ""]
    top = sorted(day_deals.values(), key=lambda d: d["score"], reverse=True)[:10]
    out.append(f"<b>🏆 Лучшие находки</b> (всего: {len(day_deals)})")
    if top:
        for i, d in enumerate(top, 1):
            out.append(f'{i}. <a href="{d["link"]}">{escape(d["title"])}</a> — {stars(d["price"])} · {d["score"]:g} очк.')
    else:
        out.append("Находок не было.")

    risers, fallers = movers(history, now)
    if risers:
        out += ["", "<b>📈 Растут</b>", *tree([f"{escape(t)}: +{c:.0%}" for t, c in risers])]
    if fallers:
        out += ["", "<b>📉 Падают</b>", *tree([f"{escape(t)}: {c:.0%}" for t, c in fallers])]
    out += ["", f"Сканов за сутки: {scans}"]
    return "\n".join(out)
