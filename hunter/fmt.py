"""Telegram HTML formatting: one fact per line, numbered reasons, tree-style blocks."""
from __future__ import annotations

from html import escape

from .models import KIND_RU, Deal

VERDICT_ICON = {"брать": "🟢", "присмотреться": "🟡", "пропустить": "🔴"}
KIND_ICON = {"model": "🧸", "backdrop": "🎨", "symbol": "🔣"}


def stars(x: float) -> str:
    return f"{round(x):,}".replace(",", " ") + " ⭐"


def money(amount: int | None, currency: str) -> str | None:
    if not amount:
        return None
    if currency in ("USD", "EUR", "RUB"):
        sym = {"USD": "$", "EUR": "€", "RUB": "₽"}[currency]
        return f"{sym}{amount / 100:,.2f}".replace(",", " ")
    return f"{amount} {currency}"


def strength(score: float) -> str:
    if score >= 7:
        return "🔥🔥🔥 очень сильная находка"
    if score >= 5.5:
        return "🔥🔥 сильная находка"
    return "🔥 хорошая находка"


def vs_floor(premium: float) -> str:
    diff = premium - 1
    if diff < 0.005:
        return "это и есть флор"
    return f"на {diff:.0%} дороже флора"


def tree(lines: list[str]) -> list[str]:
    return [("└ " if i == len(lines) - 1 else "├ ") + s for i, s in enumerate(lines)]


def format_deal(d: Deal) -> str:
    l = d.listing
    out = [
        f"💎 <b>{escape(l.collection)} #{l.num}</b>",
        strength(d.score),
        "",
        f"💰 <b>Цена:</b> {stars(d.price)}" + (f"  (≈ {l.price_ton:g} TON)" if l.price_ton else ""),
        f"📉 <b>Флор:</b> {stars(d.floor)} — {vs_floor(d.premium)}",
        f"📦 <b>Лотов в продаже:</b> {d.listed_in_collection}",
    ]

    attrs = []
    for kind in ("model", "backdrop", "symbol"):
        if a := l.attrs.get(kind):
            pct = f" — {a.percent:.1f}%" if a.percent else ""
            fire = " 🔥" if kind in d.rare_kinds else ""
            attrs.append(f"{KIND_ICON[kind]} {KIND_RU[kind].capitalize()}: <b>{escape(a.name)}</b>{pct}{fire}")
    if attrs:
        out += ["", "<b>Атрибуты</b>", *tree(attrs)]

    if d.reasons:
        out += ["", "<b>Почему это находка</b>"]
        out += [f"{i}. {escape(r[:1].upper() + r[1:])}" for i, r in enumerate(d.reasons, 1)]

    if d.value:
        cur = d.value.get("currency", "")
        market = [
            f"{label}: {m}"
            for label, key in (("Средняя цена", "average"), ("Последняя продажа", "last_sale"),
                               ("Оценка Telegram", "value"))
            if (m := money(d.value.get(key), cur))
        ]
        if market:
            out += ["", "<b>📊 Рынок Telegram</b>", *tree(market)]

    if d.ai and d.ai.get("comment"):
        verdict = d.ai["verdict"].strip()
        icon = VERDICT_ICON.get(verdict.lower(), "🤖")
        out += ["", f"{icon} <b>Мнение ИИ: {escape(verdict)}</b>",
                f"<blockquote>{escape(d.ai['comment'])}</blockquote>"]
    return "\n".join(out)


def format_top(deals: list[Deal]) -> str:
    if not deals:
        return "Пока нет находок — жду следующий скан."
    lines = ["🏆 <b>Топ находок последнего скана</b>", ""]
    for i, d in enumerate(deals, 1):
        l = d.listing
        lines.append(f'{i}. <a href="{l.link}">{escape(l.collection)} #{l.num}</a>')
        lines.append(f"    {stars(d.price)} · {vs_floor(d.premium)} · {d.score:g} очк.")
    return "\n".join(lines)


def deal_buttons(d: Deal) -> list[list[dict]]:
    return [[{"text": "🎁 Открыть подарок", "url": d.listing.link}]]
