from __future__ import annotations

from html import escape

from .models import KIND_RU, Deal

VERDICT_ICON = {"брать": "🟢", "присмотреться": "🟡", "пропустить": "🔴"}


def stars(x: float) -> str:
    return f"{round(x):,}".replace(",", " ") + " ⭐"


def money(amount: int | None, currency: str) -> str | None:
    if not amount:
        return None
    if currency in ("USD", "EUR", "RUB"):
        sym = {"USD": "$", "EUR": "€", "RUB": "₽"}[currency]
        return f"{sym}{amount / 100:,.2f}".replace(",", " ")
    return f"{amount} {currency}"


def format_deal(d: Deal, short: bool = False) -> str:
    l = d.listing
    price = stars(d.price)
    if l.price_ton:
        price += f" (≈ {l.price_ton:g} TON)" if l.price_stars else f" ({l.price_ton:g} TON)"
    head = f"🎁 <b>{escape(l.collection)} #{l.num}</b> — {price}"
    if short:
        return f'{head}\n<a href="{l.link}">открыть</a> · очки: {d.score:g}'

    lines = [head, f"Флор коллекции: {stars(d.floor)} ({d.premium:.2f}×) · лотов: {d.listed_in_collection}"]
    attrs = []
    for kind in ("model", "backdrop", "symbol"):
        if a := l.attrs.get(kind):
            pct = f" ({a.percent:.1f}%)" if a.percent else ""
            attrs.append(f"{KIND_RU[kind].capitalize()}: {escape(a.name)}{pct}")
    if attrs:
        lines.append(" · ".join(attrs))
    if d.reasons:
        lines.append("Почему: " + "; ".join(escape(r) for r in d.reasons))
    if d.value:
        cur = d.value.get("currency", "")
        parts = [
            f"{label} {m}"
            for label, key in (("средняя", "average"), ("последняя продажа", "last_sale"), ("оценка", "value"))
            if (m := money(d.value.get(key), cur))
        ]
        if parts:
            lines.append("Рынок Telegram: " + ", ".join(parts))
    if d.ai and d.ai.get("comment"):
        icon = VERDICT_ICON.get(d.ai["verdict"].lower().strip(), "🤖")
        lines.append(f"{icon} <b>{escape(d.ai['verdict'])}</b>: {escape(d.ai['comment'])}")
    lines.append(f'<a href="{l.link}">Открыть в Telegram</a> · очки: {d.score:g}')
    return "\n".join(lines)
